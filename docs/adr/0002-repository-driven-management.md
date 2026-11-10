# Manage hosts from repository checkouts without a central server

An agent will inspect and configure selected reachable hosts from an authorized repository checkout; no central management server will operate the fleet. Hosts independently check for outdated configuration, keeping notifications available when a management checkout is offline. This avoids a permanently operated controller, at the cost of requiring direct authenticated access for remote management and host access to the intended configuration for update checks.
