# JST OMC Portal — local demo

## Run

From this folder, start the local server:

```powershell
python server.py
```

Open <http://127.0.0.1:8000/index.html#account>. Sign in to the OMC Account area with the administrator details provided in the Codex conversation. Stop the server with `Ctrl+C`.

New installations create `admin@jst.local` with a random password and print that password once in the server console. The current workspace already has its administrator seeded.

## OMC workflow

An OMC submits its registered business name, 10-digit TIN, registration number, contact details, and password. The account is pending until an administrator approves it. Approved OMC users can submit PMS or AGO requests. The administrator can review and approve or decline account applications and order requests.

## Local-only scope

This demo stores data in the ignored `jst_portal.sqlite3` file. Passwords are PBKDF2 hashes; sessions use HttpOnly, SameSite cookies; the web server binds only to `127.0.0.1`; and the database and bootstrap credential path are not served as static files. TINs are stored as ordinary SQLite values, and company registration is manually reviewed rather than checked against URA or URSB. Use dummy business details for demos. Before handling real TINs, deploying beyond localhost, or treating orders as operational, add encrypted data-at-rest storage, HTTPS, CSRF/rate limiting, secure admin password reset, audit logging, authoritative registry verification, backups, and UNOC fulfilment integrations.

## Smoke test

With a local database already initialized, set `JST_ADMIN_PASSWORD` to the administrator password in PowerShell, then run `python test_backend.py`. The smoke test creates and removes its temporary OMC account and request.
