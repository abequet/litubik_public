# Security policy

## Reporting a vulnerability

Please report privately, through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository — *Security → Report a vulnerability*. It creates a private
advisory only the maintainers can see.

Do not open a public issue for a vulnerability. LitUbik instances hold
unpublished reviews, reviewer identities and, on some deployments, institutional
library credentials; a public report exposes every running instance at once.

What helps: the version or commit, how the instance is deployed (packaged
executable, `start.bat`, Docker), and the smallest sequence that reproduces the
problem. A proof of concept is welcome but never required.

Expect an acknowledgement within a week. There is no bounty — this is an
academic project with no budget — but you will be credited in the release notes
unless you prefer otherwise.

## What is in scope

The application as distributed: the FastAPI backend, the React frontend, the
packaged executable, and the synchronisation format exchanged between instances.

Findings that are **already known and documented**, so not worth a report:

- **The first account created on a fresh instance becomes the application
  administrator.** This is how an instance is bootstrapped. Restricted
  registration (the default, `LITUBIK_ALLOW_REGISTRATION=false`) limits it to
  the case where no account exists yet; on a demo instance with an allowlist
  (`LITUBIK_TRUSTED_EMAILS`), the first account must also be on it.
- **A demo instance (`LITUBIK_DEMO=true`) lets anyone open a guest session.**
  That is its purpose. Guest sessions are sandboxes: rate-limited per address,
  capped in number, purged daily, kept away from stored keys, institutional
  access, synchronisation and the server's file system, and given a capped AI
  budget. A way for a guest to get past one of these limits *is* in scope.
- **A snapshot imported in "create" mode cannot be authenticated.** The project
  does not exist locally, so there is no passphrase to verify the archive
  against. The import reports which pending accounts an archive will create.
- **The first signed contribution package from an author establishes the key
  binding**, and therefore cannot itself be authenticated — trust on first use.
  Later packages must match. See `backend/app/services/sync/signing.py`.

## Deploying safely

LitUbik is designed to be run by the team that owns the data. If you expose an
instance beyond a trusted network:

- put HTTPS in front of it — the session cookie is a 12-hour bearer credential;
- set `LITUBIK_SECRET_KEY` explicitly and keep it. It signs sessions **and**
  encrypts every stored API key and institutional password: if it changes, those
  become permanently unreadable. On a container platform, this also means the
  data directory must be on a persistent volume;
- leave `LITUBIK_ALLOW_REGISTRATION` at its default. Restricted mode still lets
  in allowlisted addresses, people a project admin has added to a team, and open
  project invitations;
- think twice before storing institutional credentials server-side. The
  per-user, browser-held path exists precisely so one person's library account
  never has to live on someone else's server.
