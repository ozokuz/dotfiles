# Use native local setup with an internal file engine

Every host must be able to set itself up without another managed host being online. Use chezmoi internally for home-file rendering/application and focused native package/system actions behind repository commands; Ansible's native Windows controller limitation conflicts with that autonomy requirement. The user and agent operate the repository interface rather than chezmoi directly.

A Python 3.11+ standard-library entry point coordinates selections, conflict policy, state, secrets, and native commands, with Bash and PowerShell bootstrap scripts. This adds one bootstrapped runtime but avoids separate orchestration implementations per OS, another package ecosystem, a permanent controller, or a custom template language. Chezmoi owns file rendering/application; the repository supplies the explicit local-edit and host-exception policy.
