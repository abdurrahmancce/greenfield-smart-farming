# Security notes — GreenField Smart Farming

Last full review: 2026-11-17 (code audit + attack tests + dependency scan). Regression tests live in `tests/test_security.py`.

## What is protected
- Passwords: salted hashes (werkzeug); login/registration/reset are rate-limited; reset tokens are random, stored hashed, single-use, expire in 1 h.
- Sessions: HttpOnly + SameSite=Lax (+ Secure on HTTPS); changing/resetting a password signs out every device.
- Cross-site requests: every POST must come from this same site (Origin / Referer / Sec-Fetch-Site).
- Data isolation: every record query is filtered by `user_id`; `farm_id` sent by a form is checked to belong to the user.
- Uploads: file type is checked from the real bytes, max 2 MB.
- Push alerts: only real browser push services are accepted as destinations; max 5 devices per user.
- Soil-sensor API (`/api/sensor/ingest`): the only endpoint without a login. Each sensor has a random secret token (shown once, only its SHA-256 hash is stored, never exported); wrong tokens are throttled per IP, readings per device (120/hour), payload max 2 KB, values range-checked, data older than 30 days is deleted. Deleting a sensor revokes its token at once.
- Headers: strict CSP - scripts only from this site (`'self'`) or with a per-request nonce; no inline event handlers, no `eval`, no third-party scripts (Chart.js, Leaflet and Font Awesome are served from `static/vendor/`). Plus `frame-ancestors`, `base-uri`, `object-src`, `form-action`, nosniff, Referrer-Policy, HSTS on HTTPS.

## Known limits (accepted / future work)
- No e-mail verification at sign-up (needs a mail provider). Mitigated: Google login only accepts verified Google e-mails and replaces any password that was set before the first Google sign-in.
- Sensor tokens travel in an HTTP header over HTTPS; anyone who obtains a token can add readings for that one sensor (not read any data) until it is deleted. The example ESP32 sketch uses `setInsecure()` for a first test and has not been run on real hardware.
- Rate-limit counters live in memory (per worker); a restart resets them.
- `style-src` still allows inline styles (the pages use many `style=` attributes) and Google Fonts; styles cannot run code, so this is a low risk. Map tiles come from OpenStreetMap (`img-src https:`).
- Sign-up tells you if an e-mail is already registered (common trade-off for a friendly UX).

## Reporting
Please open a private security advisory on GitHub (Security tab) instead of a public issue.
