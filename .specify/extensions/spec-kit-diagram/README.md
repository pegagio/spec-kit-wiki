# spec-kit-diagram Extension

This repository-owned Spec Kit extension provides reusable local integration with The Diagram. Its first capability reserves or recovers the canonical Feature identity used by the matching `spec-kit-diagram` preset.

The source tree intentionally does not contain a compiled executable. Packaging adds exactly one Darwin/ARM64 `diagram` binary and `checksums.json` beneath `bin/darwin-arm64/`; consumers execute that canonical packaged path rather than PATH content.

The extension supports Spec Kit `>=1.0.1,<1.1.0` and requires a trusted Python 3.11-or-newer interpreter. Installing it exposes `speckit.spec-kit-diagram.spec-identity`; it does not alter the core Specify workflow until the matching preset is activated.

The default database selection is The Diagram's default. To override it, set one absolute local path in ignored `.specify/extensions/spec-kit-diagram/local-config.yml`:

```yaml
database:
  path: /absolute/path/to/diagram.db
```

Recovery records under `.specify/state/spec-kit-diagram/` are private machine-local evidence. Refreshing, disabling, or removing the extension must not delete them or any existing spec, branch, active-feature pointer, or Diagram reservation.

Use `mise run spec-kit:validate` for dirty-checkout source validation and `mise run spec-kit:package` only from a clean release checkout. Install the staged extension with the exact local path printed by packaging, install and enable the matching preset, and inspect the composed commands before the first reservation. No activation step creates or upgrades a database.

Disable the extension only to stop new capability invocations. Remove it with `specify extension remove spec-kit-diagram --keep-config --force` so ignored local configuration remains beside the independently retained recovery records. Preserve both unless a future explicit, separately reviewed pruning workflow says otherwise; reinstall relies on that evidence to recover an interrupted attempt safely.
