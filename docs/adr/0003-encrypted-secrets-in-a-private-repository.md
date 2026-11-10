# Store encrypted machine secrets in a separate private GitHub repository

The system must be free, support seven environments, and centralize machine secrets without an operated secrets server. Use SOPS + age to encrypt secrets in a separate private GitHub repository; the configuration repository holds references rather than secret values. Bitwarden Secrets Manager's free tier cannot provide seven independent machine accounts, and sharing accounts would weaken the proposed access boundaries.

Git history retains encrypted previous values. Removing a recipient cannot retract already accessible secrets, so compromise recovery requires rotating affected application credentials as well as updating encryption recipients. Each host has its own decryption identity, with automated generation and recipient maintenance plus a separately retained recovery identity; enrollment must stay simple without a custom key-management service.

The configuration repository records its expected secrets-repository revision. A coordinated update workflow maintains that reference so application and recovery use a known combination of revisions rather than independently moving branches.
