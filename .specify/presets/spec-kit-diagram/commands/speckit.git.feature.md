---
description: "Create the exact Diagram-derived Feature branch through the lower Git command"
---

# Git Feature Branch with The Diagram

This conditional wrapper participates only when a compatible Git extension supplies the lower command layer. It may establish the shared handoff before the wrapped Specify command starts.

## Identity Preamble

Invoke `speckit.spec-kit-diagram.spec-identity` with the exact original feature description. Require one structured success document, then load and validate the private handoff and attempt record. Require `git` in expected consumers and require `branch_name` to equal the canonical `<CANONICAL-ID>-<slug>` target.

If the attempt is already `complete`, require the current exact branch association and return the retained result without entering the lower command or acknowledging Git again. If `git` is already listed in completed consumers on a still-materializing attempt, reuse that acknowledgement and return without recreating the branch.

Set `GIT_BRANCH_NAME` to that exact value for the lower command process only. Do not pass any independent identity option, scan repository identities, alter the name, or create the branch directly.

## Lower Git Workflow

{CORE_TEMPLATE}

The lower Git command remains the sole branch creator. After it succeeds, require the checked-out branch to be exactly `GIT_BRANCH_NAME` and require the handoff and target claim still to agree.

Invoke the packaged helper through the same pinned trusted Python interpreter with fixed argv:

```text
<pinned-python3> .specify/extensions/spec-kit-diagram/scripts/python/diagram_spec_identity.py acknowledge --repo <absolute-repository-root> --workflow-token <token> --consumer git
```

Validate its one JSON response. This marks only the Git consumer acknowledgement; the core consumer remains independently responsible for spec metadata and completion. An existing branch is reusable only when the retained recovery evidence proves the same attempt.
