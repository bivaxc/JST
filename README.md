# JST OMC Portal

## Local run

```bash
python server.py
```

Open http://127.0.0.1:8000/index.html#account.

For a fresh local database, set `JST_ADMIN_PASSWORD` to a unique password of at least 16 characters before the first startup. The initial administrator email is `admin@jst.local`. The password is never printed by the application.

## Render deployment

This repository includes a Render Blueprint in `render.yaml`.

1. Sign in to Render and choose **New > Blueprint**.
2. Connect this GitHub repository and select the `render-deployment` branch.
3. When prompted, provide a unique `JST_ADMIN_PASSWORD` of at least 16 characters. Store it in a password manager.
4. Review the service configuration and create the Blueprint.
5. Wait for the deploy to become live. The health endpoint is `/healthz`.

The service listens on `0.0.0.0:$PORT`. This Blueprint uses Render's Free web-service plan for a temporary demonstration. SQLite is stored on the service's ephemeral filesystem, so registrations and orders can be lost whenever the service spins down, restarts, or redeploys. Free services also spin down after 15 minutes without inbound traffic and can take about a minute to wake up. Do not use this setup for data that must be retained. A paid web service with a persistent disk, or a properly configured external database, is required for durable storage.

## Important: demonstration only

The portal is a prototype. A public URL does **not** make it an approved UNOC system, and submitted orders are not transmitted to UNOC, do not reserve stock, and do not authorize collection.

Use dummy company names, TINs, contacts, and orders for demonstrations only. Do not enter real OMC or customer information.

Before handling real data or operational orders, the application still needs a security and operational review, including at minimum:
- CSRF protection and rate limiting for authentication and registration endpoints.
- A secure administrator password reset and account recovery process.
- Audit logging for approvals, rejections, and order status changes.
- Encryption and access controls appropriate for TINs and other personal/business data.
- Authoritative company/TIN verification and a defined data-retention policy.
- Tested backups and restore procedures.
- UNOC authorization, fulfilment integration, operational ownership, and incident response.

The current prototype stores TINs in SQLite as ordinary values. Do not use production data until these controls are implemented and independently tested.
