# Security notes — GreenField Smart Farming

Last full review: 2026-11-24 (code audit + attack tests + dependency scan + static scan). Regression tests live in `tests/test_security.py`.

## What is protected
- Passwords: salted hashes (werkzeug); login/registration/reset are rate-limited; reset tokens are random, stored hashed, single-use, expire in 1 h.
- Sessions: HttpOnly + SameSite=Lax (+ Secure on HTTPS); changing/resetting a password signs out every device.
- Cross-site requests: every POST must come from this same site (Origin / Referer / Sec-Fetch-Site).
- Data isolation: every record query is filtered by `user_id`; `farm_id` sent by a form is checked to belong to the user.
- Uploads: file type is checked from the real bytes, max 2 MB.
- Push alerts: only real browser push services are accepted as destinations; max 5 devices per user.
- Soil-sensor API (`/api/sensor/ingest`): the only endpoint without a login. Each sensor has a random secret token (shown once, only its SHA-256 hash is stored, never exported); wrong tokens are throttled per IP, readings per device (120/hour), payload max 2 KB, values range-checked, data older than 30 days is deleted. Deleting a sensor revokes its token at once.
- Demo accounts (`POST /demo`): each click makes its own temporary account with sample data (random password nobody knows, e-mail `…@demo.invalid`), so visitors never share data. Limited to 6 per network per hour and 150 in total; deleted with all their data after 24 h; they cannot change e-mail/password, delete the account, or use the paid AI photo scan and push alerts; they are not counted in the admin numbers.
- Headers: strict CSP - scripts only from this site (`'self'`) or with a per-request nonce; no inline event handlers, no `eval`, no third-party scripts (Chart.js, Leaflet and Font Awesome are served from `static/vendor/`). Plus `frame-ancestors`, `base-uri`, `object-src`, `form-action`, nosniff, Referrer-Policy, HSTS on HTTPS.

- Weak passwords: a list of very common passwords, one-character repeats and "same as your name/e-mail" are refused at sign-up, reset and change.
- Extra isolation headers: `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-site`; request line/header size limits in gunicorn.
- Google sign-in redirect and password-reset links are built from the configured `APP_BASE_URL`, not from the request's Host header.
- `/.well-known/security.txt` tells researchers where to report problems.
- Automatic checks on every push: tests (incl. a test that SQL is only built from placeholders, and one that fails if a key/token/private key is committed), `pip-audit` (known-vulnerable dependencies), `bandit` (static scan), CodeQL (weekly + on pushes), Dependabot (weekly update PRs).

## Known limits (accepted / future work)
- No e-mail verification at sign-up (needs a mail provider). Mitigated: Google login only accepts verified Google e-mails and replaces any password that was set before the first Google sign-in.
- Sensor tokens travel in an HTTP header over HTTPS; anyone who obtains a token can add readings for that one sensor (not read any data) until it is deleted. The example ESP32 sketch uses `setInsecure()` for a first test and has not been run on real hardware.
- A POST with no Origin, Referer or Sec-Fetch-Site header (not sent by normal browsers) is not blocked by the same-site check; SameSite=Lax cookies still cover that case. A per-form CSRF token would be the next step.
- Rate-limit counters live in memory (per worker); a restart resets them.
- `style-src` still allows inline styles (the pages use many `style=` attributes) and Google Fonts; styles cannot run code, so this is a low risk. Map tiles come from OpenStreetMap (`img-src https:`).
- Sign-up tells you if an e-mail is already registered (common trade-off for a friendly UX).

## Reporting
Please open a private security advisory on GitHub (Security tab) instead of a public issue.
