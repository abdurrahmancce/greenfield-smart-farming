# Security notes — GreenField Smart Farming

Last full review: 2026-11-17 (code audit + attack tests + dependency scan). Regression tests live in `tests/test_security.py`.

## What is protected
- Passwords: salted hashes (werkzeug); login/registration/reset are rate-limited; reset tokens are random, stored hashed, single-use, expire in 1 h.
- Sessions: HttpOnly + SameSite=Lax (+ Secure on HTTPS); changing/resetting a password signs out every device.
- Cross-site requests: every POST must come from this same site (Origin / Referer / Sec-Fetch-Site).
- Data isolation: every record query is filtered by `user_id`; `farm_id` sent by a form is checked to belong to the user.
- Uploads: file type is checked from the real bytes, max 2 MB.
- Push alerts: only real browser push services are accepted as destinations; max 5 devices per user.
- Headers: strict CSP - scripts only from this site (`'self'`) or with a per-request nonce; no inline event handlers, no `eval`, no third-party scripts (Chart.js, Leaflet and Font Awesome are served from `static/vendor/`). Plus `frame-ancestors`, `base-uri`, `object-src`, `form-action`, nosniff, Referrer-Policy, HSTS on HTTPS.

## Known limits (accepted / future work)
- No e-mail verification at sign-up (needs a mail provider). Mitigated: Google login only accepts verified Google e-mails and replaces any password that was set before the first Google sign-in.
- Rate-limit counters live in memory (per worker); a restart resets them.
- `style-src` still allows inline styles (the pages use many `style=` attributes) and Google Fonts; styles cannot run code, so this is a low risk. Map tiles come from OpenStreetMap (`img-src https:`).
- Sign-up tells you if an e-mail is already registered (common trade-off for a friendly UX).

## Reporting
Please open a private security advisory on GitHub (Security tab) instead of a public issue.
