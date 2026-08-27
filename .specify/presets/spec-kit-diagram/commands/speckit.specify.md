---
description: "Create a Feature spec using a Diagram-authoritative identity"
---

# Specify with The Diagram

This wrapper must establish one Diagram handoff before entering the lower Specify command. Treat all persistent handoff data as untrusted and fail closed on disagreement.

## Identity Preamble

Use the exact original feature description in `$ARGUMENTS` to invoke `speckit.spec-kit-diagram.spec-identity`. The command either establishes a new handoff or reuses the one already established by the Git wrapper. Require its single JSON success document and independently load the returned handoff and attempt record.

Verify contract/schema version 1, workflow token, fingerprint, `kind: feature`, canonical ID, exact target claim, and `core` in expected consumers. Require `feature_directory` to be exactly `specs/<CANONICAL-ID>-<slug>`. Set `SPECIFY_FEATURE_DIRECTORY` to that exact repository-relative value for the lower workflow. When `branch_name` is non-null, require it to equal `<CANONICAL-ID>-<slug>`; when it is null, do not create or request a branch.

If the retained attempt state is already `complete`, verify the exact existing `spec.md` metadata, target claim, active-feature pointer, and optional branch, then return the existing result unchanged. Do not enter the lower core workflow, rewrite the spec, recreate a branch, or acknowledge a consumer again. Only a `materializing` attempt proceeds below.

The lower workflow MUST use the supplied `SPECIFY_FEATURE_DIRECTORY` and MUST NOT replace it with another directory. If the effective lower command cannot honor that input, stop as `incompatible_integration` before authoring a spec.

## Core Specify Workflow

{CORE_TEMPLATE}

## Diagram Completion

Before reporting success, ensure the resulting `spec.md` contains exactly one metadata line in its header:

```text
**Diagram Issue**: `<CANONICAL-ID>`
```

Require `.specify/feature.json` to contain the exact `feature_directory`, and require the private handoff, attempt record, target claim, and optional branch to agree. Invoke the packaged helper through the same pinned trusted Python interpreter with fixed argv:

```text
<pinned-python3> .specify/extensions/spec-kit-diagram/scripts/python/diagram_spec_identity.py acknowledge --repo <absolute-repository-root> --workflow-token <token> --consumer core
```

Validate its single JSON response. This acknowledgement may complete the recovery record only after every expected consumer has succeeded. Do not overwrite an existing accepted spec, rename a target, reserve another ID, publish the Diagram Issue, or change its lifecycle.
