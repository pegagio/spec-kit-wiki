# spec-kit-diagram Preset

This required opt-in preset composes core Spec Kit commands with capabilities supplied by the matching `spec-kit-diagram` extension. Feature identity is its first composition: the wrapper establishes one Diagram handoff before delegating to the core Specify command.

With a compatible Git extension (`>=1.0.0,<1.1.0`), the Git wrapper may run first and establish the same handoff. It supplies the exact Diagram-derived branch name while the lower Git command remains the sole branch creator. Without Git, the Specify wrapper uses the no-branch flow. An installed incompatible integration fails closed.

The preset supports Spec Kit `>=1.0.1,<1.1.0`. Install the extension and activate this preset as one local bundle; installing the extension alone does not replace core behavior. Disabling or removing the preset stops new integrated creation but preserves all historical repository and Diagram state.

After local installation, enable this preset and resolve both composed commands before creating a Feature. Python 3.11 or newer and the matching extension are required; an incompatible Spec Kit, extension, Python, or installed Git layer fails closed rather than reverting to another identity.

Disable the preset to suspend new Diagram-aware creation. Remove it explicitly with `specify preset remove spec-kit-diagram`; remove the extension separately with its config-preserving option. Removal or reinstall must preserve existing specs, branches, active-feature state, ignored local configuration, recovery associations, and Diagram reservations byte-for-byte.
