# Security Policy

## Supported versions

| Component | Supported |
|-----------|-----------|
| **SDK** (`cortexops` on PyPI) — latest published release and current `main` | Yes |
| **Backend API / dashboard** — code on current `main`, and the production deployment at `*.getcortexops.com` | Yes |
| Older SDK releases or older backend revisions | Best effort |

Security fixes are cut for the current line first. Backports to older SDK versions are considered case-by-case for high-severity issues.

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email **[contact@getcortexops.com](mailto:contact@getcortexops.com)** with:

- A description of the issue
- Steps to reproduce (if possible)
- Impact assessment (if known)
- Your preferred contact for follow-up

### Response

We aim to **acknowledge** reports within **48 hours** and will keep you updated on remediation. That acknowledgement target is defined only in this file — other docs should link here rather than restating it.

## Scope

**In scope:** CortexOps SDK, backend API, dashboard auth/API keys, CI secrets handling in this repository, and hosted services under `*.getcortexops.com`.

**Out of scope:** third-party dependencies with no CortexOps-specific exploit path (please report those upstream), and social-engineering / physical attacks.
