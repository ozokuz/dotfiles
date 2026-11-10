# Apply configuration explicitly to selected hosts

This repository will manage individually configured Linux and Windows hosts, including separate WSL instances, with shared configuration across selected hosts. Configuration changes are applied explicitly to selected hosts; changes made locally are captured back into the repository explicitly. Hosts that return online with outdated configuration must notify Ozoku without silently applying queued changes.

An agent's authority follows the requested task and named hosts. Installing programs and changing user settings within that request is permitted; system changes, removals, service interruptions, and reboots require explicit authorization. Being online does not itself authorize changes.

Fresh-install setup starts with an installed OS, working networking, and an accessible user account. It installs tools, applies configuration, and identifies remaining manual steps; OS installation, disk partitioning, personal-file restoration, and application account logins are outside its initial scope.
