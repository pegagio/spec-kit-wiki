#!/usr/bin/env python3
"""Reserve and recover Diagram-authoritative Spec Kit Feature identities."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import platform
import re
import secrets
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterator

CONTRACT_VERSION = 1
SCHEMA_VERSION = 1
FINGERPRINT_VERSION = 1
DIAGRAM_TIMEOUT_SECONDS = 30
STDOUT_LIMIT_BYTES = 1024 * 1024
STDERR_LIMIT_BYTES = 64 * 1024
CANONICAL_ID = re.compile(r"^([A-Z][A-Z0-9]{1,9})-([1-9][0-9]*)$")
PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ATTEMPT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class IntegrationFailure(Exception):
    """A classified, safe failure for the command's JSON boundary."""

    def __init__(self, code: str, message: str, next_action: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action
        self.details = details


NEXT_ACTIONS = {
    "invalid_configuration": "Correct or remove the invalid override, then retry.",
    "unknown_project": "Register the repository or select the correct ready database, then retry the same request.",
    "diagram_unavailable": "Restore runtime availability, then retry the same attempt.",
    "database_not_found": "Run explicit database creation, then retry the same attempt.",
    "upgrade_required": "Run explicit database upgrade, then retry the same attempt.",
    "invalid_diagram_response": "Repair compatibility and inspect the original attempt before retrying.",
    "ambiguous_prior_outcome": "Restore inspection capability and inspect the original attempt; never allocate another attempt.",
    "identity_conflict": "Preserve existing content and inspect ownership evidence.",
    "pending_attempt_conflict": "Resume the pending request.",
    "unsupported_platform": "Use a supported target-specific bundle.",
    "incompatible_integration": "Install a compatible trusted integration before retrying.",
}


def fail(code: str, message: str, **details: Any) -> IntegrationFailure:
    return IntegrationFailure(code, message, NEXT_ACTIONS[code], **details)


def emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def failure_payload(error: IntegrationFailure) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "ok": False,
        "code": error.code,
        "message": error.message,
        "next_action": error.next_action,
        **error.details,
    }


def require_python() -> None:
    if sys.version_info < (3, 11):
        raise fail("incompatible_integration", "The integration requires Python 3.11 or newer.")


def require_platform() -> None:
    if sys.platform != "darwin" or platform.machine().lower() != "arm64":
        raise fail("unsupported_platform", "This integration bundle supports only Darwin on ARM64.")


def canonical_directory(raw: str, label: str, *, must_contain: Path | None = None) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise fail("invalid_configuration", f"{label} must be an absolute path.")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise fail("invalid_configuration", f"{label} does not identify an existing directory.") from None
    if not resolved.is_dir():
        raise fail("invalid_configuration", f"{label} must identify a directory.")
    if must_contain is not None and resolved != must_contain and must_contain not in resolved.parents:
        raise fail("identity_conflict", f"{label} escapes the expected repository boundary.")
    return resolved


def validate_database(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {"mode": "default", "path": None}
    if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
        raise fail("invalid_configuration", "database.path must be one non-empty absolute path.")
    normalized = os.path.normpath(raw)
    return {"mode": "override", "path": normalized}


def validate_trusted_executable(path: Path, allowed_root: Path | None = None) -> tuple[int, int]:
    try:
        canonical = path.resolve(strict=True)
        info = canonical.stat()
    except OSError:
        raise fail("incompatible_integration", "The packaged Diagram executable is unavailable.") from None
    if allowed_root is not None:
        canonical_root = allowed_root.resolve(strict=True)
        if canonical_root != canonical and canonical_root not in canonical.parents:
            raise fail("incompatible_integration", "The packaged Diagram executable escapes the extension root.")
    if not stat.S_ISREG(info.st_mode) or not os.access(canonical, os.X_OK):
        raise fail("incompatible_integration", "The packaged Diagram path must be a canonical executable regular file.")
    if info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022:
        raise fail("incompatible_integration", "The packaged Diagram executable has unsafe ownership or permissions.")
    current = canonical.parent
    while True:
        parent_info = current.stat()
        unsafe_other_write = bool(parent_info.st_mode & stat.S_IWOTH)
        sticky_root = parent_info.st_uid == 0 and bool(parent_info.st_mode & stat.S_ISVTX)
        if unsafe_other_write and not sticky_root:
            raise fail("incompatible_integration", "A parent of the packaged Diagram executable is unsafe.")
        if current.parent == current:
            break
        current = current.parent
    return info.st_dev, info.st_ino


def strict_json_document(data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8", errors="strict")
        decoder = json.JSONDecoder()
        value, end = decoder.raw_decode(text.lstrip())
        leading = len(text) - len(text.lstrip())
        if text[leading + end :].strip() or not isinstance(value, dict):
            raise ValueError("multiple or non-object JSON")
        return value
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise fail("invalid_diagram_response", "The Diagram emitted an invalid structured response.") from None


def run_bounded(arguments: list[str], cwd: Path, environment: dict[str, str]) -> tuple[int, bytes, bytes]:
    try:
        process = subprocess.Popen(
            arguments,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
        )
    except OSError:
        raise fail("diagram_unavailable", "The packaged Diagram process could not be started.") from None
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, ("stdout", STDOUT_LIMIT_BYTES))
    selector.register(process.stderr, selectors.EVENT_READ, ("stderr", STDERR_LIMIT_BYTES))
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + DIAGRAM_TIMEOUT_SECONDS
    breached = False
    timed_out = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            events = selector.select(remaining)
            if not events:
                timed_out = True
                break
            for key, _ in events:
                stream_name, limit = key.data
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                captured[stream_name].extend(chunk)
                if len(captured[stream_name]) > limit:
                    breached = True
                    break
            if breached:
                break
        if breached or timed_out:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            if timed_out:
                raise fail("diagram_unavailable", "The Diagram invocation exceeded 30 seconds.")
            raise fail("invalid_diagram_response", "The Diagram invocation exceeded a bounded output limit.")
        return process.wait(), bytes(captured["stdout"]), bytes(captured["stderr"])
    finally:
        selector.close()


def diagram_arguments(executable: Path, command: list[str], database: dict[str, Any]) -> list[str]:
    result = [str(executable), *command, "--json"]
    if database["mode"] == "override":
        result.extend(["--file", database["path"]])
    return result


DOMAIN_CODES = {
    "database_not_found": "database_not_found",
    "upgrade_required": "upgrade_required",
    "database_upgrade_required": "upgrade_required",
    "project_not_registered": "unknown_project",
    "project_declaration_not_found": "unknown_project",
    "project_declaration_repository_conflict": "unknown_project",
    "project_registration_ambiguous": "unknown_project",
}


def invoke_diagram(executable: Path, command: list[str], database: dict[str, Any], repo: Path) -> dict[str, Any]:
    exit_code, stdout, _stderr = run_bounded(diagram_arguments(executable, command, database), repo, os.environ.copy())
    if exit_code < 0:
        raise fail("diagram_unavailable", "The Diagram process was terminated by a signal.")
    value = strict_json_document(stdout)
    if value.get("contract_version") != 1:
        raise fail("invalid_diagram_response", "The Diagram response uses an unsupported contract version.")
    if exit_code == 0:
        return value
    error = value.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    mapped = DOMAIN_CODES.get(code)
    if mapped:
        raise fail(mapped, f"The Diagram rejected the operation with {code}.")
    if code == "reservation_not_found":
        raise IntegrationFailure("reservation_not_found", "The original attempt has no reservation.", "Reserve with the same attempt.")
    raise fail("invalid_diagram_response", "The Diagram returned an unrecognized structured failure.")


def normalized_description(description_file: str) -> str:
    path = Path(description_file)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o177:
                raise fail("invalid_configuration", "The description file must be a private user-owned regular file.")
            raw = os.read(descriptor, STDOUT_LIMIT_BYTES + 1)
        finally:
            os.close(descriptor)
    except IntegrationFailure:
        raise
    except OSError:
        raise fail("invalid_configuration", "The description file cannot be read safely.") from None
    if len(raw) > STDOUT_LIMIT_BYTES:
        raise fail("invalid_configuration", "The feature description exceeds the supported size.")
    try:
        value = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise fail("invalid_configuration", "The feature description must be strict UTF-8.") from None
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    if not value.endswith("\n"):
        raise fail("invalid_configuration", "The description file lacks its serialization newline.")
    return value[:-1]


def fingerprint(project_key: str, description: str, slug: str) -> str:
    value = {
        "description": description,
        "fingerprint_version": FINGERPRINT_VERSION,
        "kind": "feature",
        "project_key": project_key,
        "slug": slug,
    }
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def state_root(repo: Path) -> Path:
    return repo / ".specify" / "state" / "spec-kit-diagram" / "spec-identity"


def scavenge_temporary_directories(root: Path, protected_description: Path) -> None:
    """Remove only old, private, shallow invocation directories without following links."""
    temporary_root = root / "tmp"
    ensure_private_directory(temporary_root)
    protected = protected_description.absolute().parent
    cutoff = time.time() - (DIAGRAM_TIMEOUT_SECONDS * 2)
    for entry in temporary_root.iterdir():
        info = entry.lstat()
        if entry.absolute() == protected:
            continue
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise fail("identity_conflict", "Temporary recovery state contains an unsafe entry.")
        if info.st_mtime > cutoff:
            continue
        children = list(entry.iterdir())
        for child in children:
            child_info = child.lstat()
            if not stat.S_ISREG(child_info.st_mode) or child_info.st_uid != os.geteuid() or child_info.st_mode & 0o177:
                raise fail("identity_conflict", "An abandoned temporary directory contains an unsafe entry.")
        for child in children:
            os.unlink(child)
        os.rmdir(entry)


def ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise fail("identity_conflict", "Integration recovery state has unsafe ownership or permissions.")


@contextlib.contextmanager
def recovery_lock(root: Path) -> Iterator[None]:
    ensure_private_directory(root)
    path = root / "checkout.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise fail("identity_conflict", "The recovery lock is not a private regular file.")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def atomic_json(path: Path, value: dict[str, Any], *, private_parent: bool = True, private_file: bool = True) -> None:
    if private_parent:
        ensure_private_directory(path.parent)
    else:
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        unsafe_mode = info.st_mode & (0o077 if private_file else 0o022)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or unsafe_mode:
            raise fail("identity_conflict", "A recovery record has an unsafe type, owner, or mode.")
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        contents = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        os.write(descriptor, contents)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def load_json(path: Path) -> dict[str, Any]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError("unsafe record")
            data = os.read(descriptor, STDOUT_LIMIT_BYTES + 1)
        finally:
            os.close(descriptor)
        value = strict_json_document(data)
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported schema")
        return value
    except IntegrationFailure:
        raise
    except (OSError, ValueError):
        raise fail("identity_conflict", "A retained recovery record is invalid or unsafe.") from None


def attempt_path(root: Path, attempt: str) -> Path:
    digest = hashlib.sha256(attempt.encode("utf-8")).hexdigest()
    return root / "attempts" / f"{digest}.json"


def find_pending_attempt(root: Path) -> tuple[Path, dict[str, Any]] | None:
    attempts = root / "attempts"
    ensure_private_directory(attempts)
    pending: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(attempts.iterdir(), key=lambda candidate: candidate.name):
        if path.suffix != ".json":
            raise fail("identity_conflict", "The attempt directory contains an unexpected entry.")
        record = load_json(path)
        attempt = record.get("attempt")
        state = record.get("state")
        if not isinstance(attempt, str) or not ATTEMPT.fullmatch(attempt) or path != attempt_path(root, attempt):
            raise fail("identity_conflict", "An attempt record does not match its retained identity.")
        if state not in {"prepared", "reserved", "materializing", "complete"}:
            raise fail("identity_conflict", "An attempt record has an invalid recovery transition.")
        if state != "complete":
            pending.append((path, record))
    if len(pending) > 1:
        raise fail("identity_conflict", "This checkout contains more than one pending creation attempt.")
    return pending[0] if pending else None


def same_request(record: dict[str, Any], request_fingerprint: str, slug: str, database: dict[str, Any], project_key: str) -> bool:
    return (
        record.get("request_fingerprint_version") == 1
        and record.get("request_fingerprint") == request_fingerprint
        and record.get("slug") == slug
        and record.get("database") == database
        and record.get("project_key") == project_key
        and record.get("kind") == "feature"
    )


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def validate_project(value: dict[str, Any]) -> str:
    project = value.get("project")
    key = project.get("key") if isinstance(project, dict) else None
    if value.get("result") != "registered" or not isinstance(key, str) or not PROJECT_KEY.fullmatch(key):
        raise fail("invalid_diagram_response", "The Diagram project response is incomplete or invalid.")
    return key


def validate_database_version(value: dict[str, Any]) -> None:
    database_version = value.get("database_version")
    upgrade_version = value.get("upgrade_version")
    if database_version != 4 or upgrade_version != 4:
        raise fail("invalid_diagram_response", "The Diagram database version response is incompatible with this bundle.")


def validate_reservation(value: dict[str, Any], project_key: str, attempt: str) -> dict[str, Any]:
    reservation = value.get("reservation")
    if not isinstance(reservation, dict):
        raise fail("invalid_diagram_response", "The Diagram reservation response is missing.")
    expected = {
        "project_key": project_key,
        "kind": "feature",
        "attempt": attempt,
    }
    if any(reservation.get(key) != wanted for key, wanted in expected.items()):
        raise fail("invalid_diagram_response", "The Diagram reservation response does not match the original attempt.")
    identity = reservation.get("id")
    status = reservation.get("status")
    match = CANONICAL_ID.fullmatch(identity) if isinstance(identity, str) else None
    if match is None or match.group(1) != project_key or status not in {"reserved", "published"}:
        raise fail("invalid_diagram_response", "The Diagram reservation facts are invalid.")
    return {
        "contract_version": 1,
        "id": identity,
        "project_key": project_key,
        "kind": "feature",
        "attempt": attempt,
        "status": status,
    }


def claim_target(repo: Path, identity: str, slug: str, attempt: str, request_fingerprint: str, git_enabled: bool) -> dict[str, Any]:
    if not SLUG.fullmatch(slug) or len(slug) > 80:
        raise fail("invalid_configuration", "The normalized slug is invalid.")
    name = f"{identity}-{slug}"
    specs = repo / "specs"
    specs.mkdir(mode=0o755, exist_ok=True)
    for child in specs.iterdir():
        if child.name.casefold() == name.casefold() and child.name != name:
            raise fail("identity_conflict", "The canonical target has a case-insensitive path collision.")
    target = specs / name
    if target.is_symlink():
        raise fail("identity_conflict", "The canonical target traverses a symbolic link.")
    target.mkdir(mode=0o755, exist_ok=True)
    resolved = target.resolve(strict=True)
    if repo != resolved and repo not in resolved.parents:
        raise fail("identity_conflict", "The canonical target escapes the repository.")
    claim = target / ".spec-kit-diagram-claim.json"
    claim_value = {
        "schema_version": 1,
        "attempt": attempt,
        "canonical_id": identity,
        "request_fingerprint": request_fingerprint,
        "slug": slug,
        "claim_nonce": secrets.token_hex(16),
    }
    if claim.exists():
        prior = load_json(claim)
        for key in ("attempt", "canonical_id", "request_fingerprint", "slug"):
            if prior.get(key) != claim_value[key]:
                raise fail("identity_conflict", "The canonical target belongs to a different creation attempt.")
        claim_value = prior
    elif any(target.iterdir()):
        raise fail("identity_conflict", "The canonical target already contains unrelated content.")
    else:
        atomic_json(claim, claim_value, private_parent=False)
    relative = f"specs/{name}"
    return {
        "feature_directory": relative,
        "spec_path": f"{relative}/spec.md",
        "branch_name": name if git_enabled else None,
        "claim_nonce": claim_value["claim_nonce"],
    }


def persist_active_feature(repo: Path, feature_directory: str) -> None:
    path = repo / ".specify" / "feature.json"
    path.parent.mkdir(mode=0o755, exist_ok=True)
    atomic_json(path, {"feature_directory": feature_directory}, private_parent=False, private_file=False)


def validate_replay(repo: Path, record: dict[str, Any], git_enabled: bool) -> None:
    if record.get("state") not in {"materializing", "complete"}:
        raise fail("identity_conflict", "The retained attempt has an invalid recovery transition.")
    reservation = record.get("reservation")
    target = record.get("target")
    if not isinstance(reservation, dict) or not isinstance(target, dict):
        raise fail("identity_conflict", "The retained attempt lacks its reservation or target association.")
    expected = claim_target(
        repo,
        reservation["id"],
        record["slug"],
        record["attempt"],
        record["request_fingerprint"],
        git_enabled,
    )
    for key in ("feature_directory", "spec_path", "branch_name", "claim_nonce"):
        if expected.get(key) != target.get(key):
            raise fail("identity_conflict", "The retained repository target has drifted.")
    if record["state"] == "complete":
        spec_path = repo / target["spec_path"]
        try:
            contents = spec_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise fail("identity_conflict", "The completed spec is unavailable or invalid.") from None
        marker = f"**Diagram Issue**: `{reservation['id']}`"
        if contents.count(marker) != 1:
            raise fail("identity_conflict", "The completed spec metadata no longer matches its Diagram identity.")


def handoff_payload(root: Path, record_path: Path, record: dict[str, Any]) -> dict[str, Any]:
    target = record["target"]
    return {
        "schema_version": 1,
        "attempt_record": record_path.relative_to(root.parent.parent.parent.parent).as_posix(),
        "canonical_id": record["reservation"]["id"],
        "feature_directory": target["feature_directory"],
        "branch_name": target["branch_name"],
        "workflow_token": record["workflow_token"],
        "consumers": record["consumers"],
    }


def success_payload(root: Path, record: dict[str, Any], recovered: bool) -> dict[str, Any]:
    target = record["target"]
    return {
        "contract_version": 1,
        "ok": True,
        "attempt": record["attempt"],
        "canonical_id": record["reservation"]["id"],
        "project_key": record["project_key"],
        "kind": "feature",
        "feature_directory": target["feature_directory"],
        "spec_path": target["spec_path"],
        "branch_name": target["branch_name"],
        "handoff_file": (root / "handoff.json").relative_to(root.parent.parent.parent.parent).as_posix(),
        "workflow_token": record["workflow_token"],
        "recovered": recovered,
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    require_platform()
    repo = canonical_directory(args.repo, "Repository root")
    if not (repo / ".specify").is_dir():
        raise fail("invalid_configuration", "Repository root is not an initialized Spec Kit project.")
    if not SLUG.fullmatch(args.slug) or len(args.slug) > 80:
        raise fail("invalid_configuration", "The normalized slug is invalid.")
    database = validate_database(args.database_file)
    description = normalized_description(args.description_file)
    extension_root = Path(__file__).resolve().parents[2]
    executable = extension_root / "bin" / "darwin-arm64" / "diagram"
    identity = validate_trusted_executable(executable, extension_root)
    validate_database_version(invoke_diagram(executable, ["database", "version"], database, repo))
    project_key = validate_project(invoke_diagram(executable, ["project", "status"], database, repo))
    request_fingerprint = fingerprint(project_key, description, args.slug)
    root = state_root(repo)
    with recovery_lock(root):
        scavenge_temporary_directories(root, Path(args.description_file))
        current_identity = validate_trusted_executable(executable, extension_root)
        if current_identity != identity:
            raise fail("incompatible_integration", "The packaged Diagram executable changed during invocation.")
        handoff_path = root / "handoff.json"
        record: dict[str, Any] | None
        record_path: Path | None
        recovered = False
        record = None
        record_path = None
        if handoff_path.exists():
            handoff = load_json(handoff_path)
            handoff_record_path = repo / str(handoff.get("attempt_record", ""))
            record_path = handoff_record_path
            if repo != record_path.resolve().parent and repo not in record_path.resolve().parents:
                raise fail("identity_conflict", "The handoff attempt record escapes the repository.")
            record = load_json(record_path)
            if same_request(record, request_fingerprint, args.slug, database, project_key):
                recovered = True
            elif record.get("state") == "complete":
                record = None
                record_path = None
            else:
                raise fail("pending_attempt_conflict", "This checkout already owns a different pending creation request.", attempt_record=handoff_record_path.relative_to(repo).as_posix())
            if record is not None and record.get("state") in {"materializing", "complete"}:
                validate_replay(repo, record, args.git)
                persist_active_feature(repo, record["target"]["feature_directory"])
                atomic_json(handoff_path, handoff_payload(root, record_path, record))
                return success_payload(root, record, True)
        if record is None:
            pending = find_pending_attempt(root)
            if pending is not None:
                record_path, record = pending
                if not same_request(record, request_fingerprint, args.slug, database, project_key):
                    raise fail("pending_attempt_conflict", "This checkout already owns a different pending creation request.", attempt_record=record_path.relative_to(repo).as_posix())
                recovered = True
                if record.get("state") == "materializing":
                    validate_replay(repo, record, args.git)
                    persist_active_feature(repo, record["target"]["feature_directory"])
                    atomic_json(handoff_path, handoff_payload(root, record_path, record))
                    return success_payload(root, record, True)
        if record is None:
            attempt = "spec-" + secrets.token_hex(16)
            if not ATTEMPT.fullmatch(attempt):
                raise AssertionError("generated attempt is invalid")
            now = utc_now()
            record = {
                "schema_version": 1,
                "state": "prepared",
                "attempt": attempt,
                "project_key": project_key,
                "kind": "feature",
                "request_fingerprint_version": 1,
                "request_fingerprint": request_fingerprint,
                "database": database,
                "slug": args.slug,
                "reservation": None,
                "target": None,
                "workflow_token": secrets.token_hex(32),
                "consumers": {"expected": ["core", *(["git"] if args.git else [])], "completed": []},
                "created_at": now,
                "updated_at": now,
            }
            record_path = attempt_path(root, attempt)
            atomic_json(record_path, record)
        assert record_path is not None
        attempt = record["attempt"]
        try:
            inspected = invoke_diagram(executable, ["issue", "reservation", "--attempt", attempt], database, repo)
            reservation = validate_reservation(inspected, project_key, attempt)
        except IntegrationFailure as error:
            if error.code != "reservation_not_found":
                if error.code in {"diagram_unavailable", "invalid_diagram_response"} and recovered:
                    raise fail("ambiguous_prior_outcome", "The original reservation cannot currently be reconciled.", cause=error.code, attempt_record=record_path.relative_to(repo).as_posix())
                raise
            try:
                reserved = invoke_diagram(executable, ["issue", "reserve", "--kind", "feature", "--attempt", attempt], database, repo)
                reservation = validate_reservation(reserved, project_key, attempt)
            except IntegrationFailure as reserve_error:
                if reserve_error.code in {"diagram_unavailable", "invalid_diagram_response"}:
                    raise fail("ambiguous_prior_outcome", "The reserve outcome is ambiguous and must be inspected.", cause=reserve_error.code, attempt_record=record_path.relative_to(repo).as_posix())
                raise
        record["reservation"] = reservation
        record["state"] = "reserved"
        record["updated_at"] = utc_now()
        atomic_json(record_path, record)
        record["target"] = claim_target(repo, reservation["id"], args.slug, attempt, request_fingerprint, args.git)
        record["state"] = "materializing"
        record["updated_at"] = utc_now()
        atomic_json(record_path, record)
        persist_active_feature(repo, record["target"]["feature_directory"])
        atomic_json(handoff_path, handoff_payload(root, record_path, record))
        return success_payload(root, record, recovered)


def acknowledge(args: argparse.Namespace) -> dict[str, Any]:
    repo = canonical_directory(args.repo, "Repository root")
    root = state_root(repo)
    with recovery_lock(root):
        handoff_path = root / "handoff.json"
        handoff = load_json(handoff_path)
        if not secrets.compare_digest(str(handoff.get("workflow_token", "")), args.workflow_token):
            raise fail("identity_conflict", "The workflow token does not match the active handoff.")
        record_path = repo / str(handoff.get("attempt_record", ""))
        record = load_json(record_path)
        expected = record.get("consumers", {}).get("expected", [])
        if args.consumer not in expected:
            raise fail("identity_conflict", "The consumer is not expected by this handoff.")
        if args.consumer == "core":
            spec_path = repo / record["target"]["spec_path"]
            try:
                contents = spec_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                raise fail("identity_conflict", "The expected spec file is unavailable or invalid.") from None
            marker = f"**Diagram Issue**: `{record['reservation']['id']}`"
            if contents.count(marker) != 1:
                raise fail("identity_conflict", "The spec does not contain exactly one matching Diagram Issue field.")
        completed = record["consumers"]["completed"]
        if args.consumer not in completed:
            completed.append(args.consumer)
        if set(completed) == set(expected):
            record["state"] = "complete"
        record["updated_at"] = utc_now()
        atomic_json(record_path, record)
        atomic_json(handoff_path, handoff_payload(root, record_path, record))
        return success_payload(root, record, True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="reserve or recover one Feature identity handoff")
    prepare_parser.add_argument("--repo", required=True)
    prepare_parser.add_argument("--description-file", required=True)
    prepare_parser.add_argument("--slug", required=True)
    prepare_parser.add_argument("--database-file")
    prepare_parser.add_argument("--git", action="store_true", help="include the optional Git consumer")
    acknowledge_parser = commands.add_parser("acknowledge", help="acknowledge one successful handoff consumer")
    acknowledge_parser.add_argument("--repo", required=True)
    acknowledge_parser.add_argument("--workflow-token", required=True)
    acknowledge_parser.add_argument("--consumer", required=True, choices=("core", "git"))
    return result


def main() -> int:
    try:
        require_python()
        args = parser().parse_args()
        outcome = prepare(args) if args.command == "prepare" else acknowledge(args)
        emit(outcome)
        return 0
    except IntegrationFailure as error:
        emit(failure_payload(error))
        return 1
    except (KeyboardInterrupt, BrokenPipeError):
        error = fail("diagram_unavailable", "The identity workflow was interrupted before completion.")
        emit(failure_payload(error))
        return 1
    except Exception:
        error = fail("invalid_diagram_response", "The integration encountered an unexpected internal failure.")
        emit(failure_payload(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
