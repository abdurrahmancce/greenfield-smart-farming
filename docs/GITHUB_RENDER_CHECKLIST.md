# Settings to switch on yourself (they cannot be set from code)

## GitHub → repository → Settings
1. **Code security** → turn on: Dependency graph, Dependabot alerts, Dependabot security updates, **Secret scanning** and **Push protection** (blocks a commit that contains a key).
2. **Branches → Add rule for `main`**: require the "CI" status check to pass; block force-pushes and deletions. (Solo developer: leave "require pull request" off if you want to keep pushing directly.)
3. **Actions → General → Workflow permissions**: "Read repository contents" only.
4. **Security → Private vulnerability reporting**: enable (the Contact line in `security.txt` points to it).
5. Your GitHub account: two-factor authentication ON (authenticator app or passkey); remove unused personal access tokens/SSH keys.

## Render → service → Environment
1. Delete `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_PORT` (old Gmail SMTP; Brevo API is used now).
2. `SECRET_KEY` must exist and be long and random (Render can generate it). Changing it signs everyone out — fine.
3. Keep `APP_BASE_URL=https://greenfield-smart-farming-1.onrender.com` (used for reset links and Google sign-in).
4. Turn on "Auto-deploy" only for `main`; turn on 2FA for your Render account.

## Other accounts
- Google account → revoke the old Gmail App Password; turn on 2-step verification.
- Brevo → API key only with *Transactional email*; rotate it if it was ever shown in a screenshot.
- Supabase → database password rotated if it was ever shown; "Network restrictions" if your plan has them.
