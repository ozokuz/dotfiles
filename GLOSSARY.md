# Environment Configuration

The vocabulary for managing Ozoku's working environments and their shared configuration.

## Language

**Host**:
An individually managed physical machine, virtual machine, or WSL instance with its own intended configuration and installed programs.
_Avoid_: Environment when referring to a specific managed target

**Shared configuration**:
Configuration intended to be used by a selected set of hosts. Sharing preferences does not require those hosts to have identical setups.

**Bundle**:
A reusable selection of tools and settings that a host can choose alongside individual selections. Bundles do not contain other bundles.

**Host exception**:
A managed file intentionally left under local control on a particular host until management of that file is explicitly re-enabled.

**Enrollment**:
The explicit authorization of a host's repository access and decryption identity for the configuration and secrets it needs.

**Outdated host**:
A host whose applied configuration is behind the configuration currently intended for it. An offline host can become outdated and must notify Ozoku when it comes online.
