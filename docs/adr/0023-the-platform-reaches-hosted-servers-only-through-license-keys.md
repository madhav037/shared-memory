# The platform is private and sets a hosted server's plan only through license keys

The platform, which handles sign-up, Paddle billing, provisioning, monitoring and signing license keys, lives in a separate private repository. Self-hosters never receive billing or provisioning code, and the license-signing key never sits near the public code. A hosted server learns its plan the same way a self-hosted one does: from a license key that it checks offline. The platform signs a short-lived key for each hosted server and renews it while the team pays. A plan change, a lapse or a renewal is just a new key, and a hosted server keeps working while the platform is down. Beyond keys, the platform touches a hosted server in only three ways: the provisioner's commands on its host, the sign-ins it hands over (#471), and polling `/health`. It never reads or writes a team's memory.

## Considered options

- **The platform sets the server's settings and restarts it** would be a second way of setting plans, alongside the license key, and every plan change would cost a restart.
- **The server asks the platform for its plan** keeps the plan live, but makes every hosted server depend on the platform staying up.
- **Keeping the platform in the public repository** means one CI, but vendor-only code would ship to every self-hoster.
