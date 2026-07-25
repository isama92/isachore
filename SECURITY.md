# Security policy

## Reporting a vulnerability

Please report privately, not in a public issue.

Use GitHub's private reporting: **[Security > Report a vulnerability](https://github.com/isama92/isachore/security/advisories/new)**.
That opens a channel visible only to you and the maintainer, and it lets a fix and
an advisory be prepared before anything is public.

Useful things to include: what an attacker gains, the steps to reproduce it, and
the commit or image digest you saw it on. A proof of concept helps a lot.

This is a hobby project maintained by one person in their spare time. There is no
bounty and no guaranteed response time. Reports are read and taken seriously, but
please assume days rather than hours.

## What is supported

Only `main`, and the `latest` images built from it:

- `ghcr.io/isama92/isachore-backend:latest`
- `ghcr.io/isama92/isachore-frontend:latest`

There are no release branches and no backports. `latest` is the only published
tag, so a fix reaches you by pulling again. Older digests are never patched.

## Known and accepted, please do not report these

Two properties look like findings but are deliberate, and both are documented with
their reasoning in [README.md](README.md):

- **Avatar images are served without authentication.** Each URL is a capability:
  the filename is 128 random bits, the directory has no listing, and the name is
  handed out only by endpoints behind authentication (or, on the public account
  confirmation route, behind a single-use emailed token, where a brand new account
  cannot have an avatar yet). Uploads are re-encoded to WebP
  with metadata stripped. The accepted downside is that anyone holding a URL can
  fetch that image until the avatar is replaced or deleted.
- **`docker/compose.prod.http.yml` serves plain HTTP.** It exists for a local
  smoke test on a trusted network and says so in its header. The TLS and Traefik
  modes are the internet-facing ones.

A report showing either of these is worse than documented, or reachable in a way
the reasoning did not anticipate, is very welcome.

## If you are deploying this

Worth knowing, because the app cannot enforce them for you:

- **Terminate TLS in front of it.** Auth cookies are `Secure` by default and the
  backend refuses to boot outside a dev environment with `COOKIES_SECURE=false`.
- **Set a real `APP_KEY` and a real `POSTGRES_PASSWORD`.** The backend refuses to
  boot on a missing or malformed key, or on a `DATABASE_URL` whose password is
  empty or one of the publicly known placeholders or common defaults.
- **Create the first admin with `python -m app.cli init`** and nothing else. There
  is no self-registration; every other account is created by an admin.
- Keep your `.env` and `volumes/certs` outside any git checkout.

The production checklist in [README.md](README.md#production-checklist) covers all
of this in detail.
