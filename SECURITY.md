# Security Policy

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through
[GitHub's private vulnerability reporting](https://github.com/nithishtrystuffs/teams-listener/security/advisories/new).
You'll get a reply as soon as possible, and credit in the fix if you'd like.

## Supported versions

Only the latest release on `main` gets security fixes.

## Scope notes

Teams Listener runs entirely on your PC. Things worth reporting include: the renderer reaching files or
commands outside the allow-listed IPC, path traversal through meeting folders or `app-audio://` URLs,
and anything that could send audio or transcripts off the machine.
