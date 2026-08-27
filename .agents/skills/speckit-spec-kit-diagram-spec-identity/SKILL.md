---
name: speckit-spec-kit-diagram-spec-identity
description: Reserve or recover one Diagram-authoritative Feature identity handoff
compatibility: Requires spec-kit project structure with .specify/ directory
metadata:
  author: github-spec-kit
  source: spec-kit-diagram:commands/speckit.spec-kit-diagram.spec-identity.md
---

# Establish a Diagram Spec Identity

Establish or reuse the private Diagram handoff for one Feature creation request. This command is a capability used by the `spec-kit-diagram` preset; it does not author `spec.md`, create a Git branch, publish an Issue, or transition lifecycle state.

## User Input

```text
$ARGUMENTS
```

The input is the exact feature description. Derive one lowercase ASCII kebab-case slug of at most 80 characters using meaningful words from the description. Do not add an identity, sequence, clock value, prefix, or random suffix to the slug.

## Resolve the Fixed Inputs

1. Resolve the repository root as the canonical absolute directory containing `.specify/`. Fail before staging content if it cannot be established.
2. Read `.specify/extensions/spec-kit-diagram/local-config.yml` only when it exists. Accept exactly an optional mapping `database` containing exactly optional key `path`. The value must be either absent/null or one non-empty absolute string. Reject unknown keys, YAML aliases/tags, environment interpolation, CLI fragments, relative paths, and duplicate keys as `invalid_configuration`. When absent, omit `--database-file`; this deliberately preserves The Diagram's default database path.
3. Locate `python3` through the process executable search path without evaluating shell text. Canonicalize all symlinks. Require a regular executable owned by the effective user or root, not group- or other-writable, with no other-writable canonical parent unless the parent is root-owned and sticky. Invoke that exact path with fixed argv `-c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'`. Record its device and inode. A failed check is `incompatible_integration` and MUST occur before recovery or repository mutation.

## Stage the Description Privately

Acquire the advisory lock at `.specify/state/spec-kit-diagram/spec-identity/checkout.lock` before accepting source content. While holding it, validate and safely scavenge only abandoned integration-owned temporary entries according to the recovery contract.

Create `.specify/state/spec-kit-diagram/spec-identity/tmp/` and a unique child directory with mode `0700`. Write the exact `$ARGUMENTS` bytes followed by exactly one serialization LF to `description.txt` with mode `0600`. Do not put the description in argv, stdin, the environment, logs, persistent JSON, or diagnostic output.

Immediately before execution, restat the pinned Python path and require the same device and inode and all original trust predicates. Invoke it with fixed argv and no shell evaluation:

```text
<pinned-python3> .specify/extensions/spec-kit-diagram/scripts/python/diagram_spec_identity.py prepare --repo <absolute-repository-root> --description-file <absolute-private-description-file> --slug <slug> [--database-file <absolute-path>] [--git]
```

Include `--git` only when the active materialized command set contains the compatible wrapped `speckit.git.feature` layer. The helper owns the 30-second Diagram subprocess timeout and bounded output rules.

Remove the unique invocation directory after success, rejection, timeout, normal failure, or any catchable interruption. Never follow or remove a symlink or unsafe entry during cleanup.

## Validate and Return the Handoff

Parse helper stdout as exactly one JSON document. On failure, preserve its exact `code`, `message`, `next_action`, optional `cause`, and attempt-record reference; do not invent an ID or retry with another attempt. On success, load the returned private `handoff_file` and its `attempt_record`, then verify schema version 1, workflow token, fingerprint version, canonical ID, Feature kind, target, and consumer set agree with stdout.

Return the validated success document to the caller. The canonical directory is exactly `specs/<CANONICAL-ID>-<slug>`. A subsequent identical call reuses this handoff; it never reserves another identity.