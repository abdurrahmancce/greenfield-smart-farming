# Security deployment and verification

This change is based on commit `37c6fa410c20540d17c728c3e904bc6ec2d0c946`.
It has been tested with isolated SQLite databases. It is not proof that the live
service is safe, and it does not establish that a breach has happened.

## Before deploying

1. Take an encrypted database backup and verify a restore into a separate staging
   database. The workflow now fails on missing configuration/dump errors, but its
   encryption and restoration must still be exercised with your own infrastructure.
2. Configure an independent random `SECRET_KEY` (at least 32 characters),
   `FLASK_ENV=production`, and the real HTTPS `APP_BASE_URL`. Set the Google callback
   URL to that same host. Rotating the session key signs everyone out.
3. Keep `DATABASE_URL` and API/OAuth/SMTP/VAPID/cron credentials in the hosting
   environment. Never put them in Git, a report, a screenshot or a shared ZIP.
   If any credential was previously exposed, rotate it at its provider; changing
   source code cannot revoke it. The old hardcoded session-key fallback remains
   in Git history. Its presence alone does not prove production used it.
4. Configure working SMTP before relying on password recovery. The app no longer
   prints recovery links. Suppress or redact `/reset-password/<token>` in upstream
   access logs, analytics and error monitoring too. Historical logs need review.
5. `TRUST_RENDER_PROXY=1` is set in the supplied Render blueprint. Use it only when
   requests arrive through Render's public edge, which overwrites `CF-Connecting-IP`.
   Leave it unset on directly exposed servers. Confirm two independent clients have
   different quota buckets on staging. Do not blindly trust `X-Forwarded-For`.
   Sources: https://render.com/articles/host-pocketbase-on-render and
   https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/X-Forwarded-For
6. Validate PostgreSQL migrations on staging. New shared quota table:
   `security_limits`; new audit-log column: `activity_log.user_id`. No runtime
   database file is included in the source distribution. Use persistent PostgreSQL
   for production, not an ephemeral SQLite filesystem.

## Staging acceptance checks

- Install `requirements.lock.txt`; run `python -m pytest -q`,
  `node --test tests/security-browser.test.cjs`, and `pip-audit -r requirements.lock.txt`.
- Register two accounts. Create/edit/delete farms, notes, growth, irrigation,
  expenses and fertilizer records. Confirm account B cannot read or attach to A's
  farm. Export each account and check isolation.
- Test password login, Google new-user and existing-linked-user login, email change,
  password change, reset-link expiry and single use. A cookie saved immediately
  after login must stop working after another device changes the password.
- Confirm all forms and AJAX requests include CSRF tokens. Cron is the sole CSRF
  exemption and still requires `X-Cron-Token`.
- Install the PWA. Visit private pages, disconnect, and confirm only the public
  offline shell appears. Upgrade an existing v4 installation and check that legacy
  page caches and `gf-disease` IndexedDB are removed. Old open tabs should reload.
- Verify Firefox/Chrome/Safari push subscriptions and redirect rejection with
  real devices. Unsupported push hosts deliberately receive 400. Account switching
  on one device may require unsubscribing/re-enabling notifications; subscriptions
  are not silently transferred between accounts.
- Verify SMTP/Google/AI/weather using staging provider credentials. AI models and
  agricultural recommendation quality were not validated by the security tests.
- Check HTTPS, host validation, Secure/HttpOnly/SameSite cookies, no-store responses,
  dependency audit, quotas under multiple workers, and backup restoration.

## Existing data and history

New ownership checks prevent bad associations; owner-qualified JOINs hide existing
cross-owner rows. They do not delete old rows automatically. Review and repair
invalid associations on a backed-up staging copy first. For each of `crop_growth`,
`irrigation_log`, `expense_log`, and `crop_notes`, this read-only query counts them
(replace `crop_growth` only with a table name from this fixed list):

```sql
SELECT COUNT(*)
FROM crop_growth r
LEFT JOIN farms f ON f.id = r.farm_id AND f.user_id = r.user_id
WHERE f.id IS NULL;
```

Also review disease scans whose nonzero farm ID belongs to a different user and
rows belonging to already-deleted accounts. Old `activity_log` entries have no
owner identifier, so a reliable per-account purge cannot be inferred automatically.
New entries omit free-text personal details and carry the authenticated user ID.
Review legacy logs and backup retention separately; account deletion does not erase
older backups, Git objects, screenshots, or third-party provider records.

The committed database in the supplied history had no users in the three versions
inspected, but some farm/note/calculation records. Removing it in this patch does
not erase old Git objects, forks or clones. Decide whether those records are demo
or sensitive. If sensitive, coordinate a history rewrite/removal with GitHub and
collaborators after credential rotation; do not force-push blindly.

## Intentional behavior changes and remaining limits

- Logout is POST with a confirmation screen; a GET does not log someone out.
- Private HTML/photos/API responses are no-store. Offline photos are memory-only;
  reloading or closing a tab loses pending photos. Existing cached content on
  devices that never reconnect cannot be remotely erased.
- Google requires verified email and does not automatically link password accounts.
  Existing password users should use password login/reset; no new linking UI was
  added. Live OAuth provider behavior still needs a staging smoke test.
- Invalid numeric/date/type inputs return 400; foreign farm associations return 404.
- Shared quotas use fixed windows: short boundary bursts remain possible. Edge
  rate limits and monitoring are still needed for volumetric attacks.
- CSP currently restricts objects, framing, base URLs and form targets. It is not
  a complete script-src policy; inline scripts/CDN dependencies need a separate
  nonce/SRI/self-hosting migration.
- Images are decoded, dimension-limited and metadata-stripped. Photos/crop/notes
  still intentionally go to the configured AI provider, locations to mapping and
  weather providers, and notification data to push providers. This is not a
  zero-third-party-data-transfer application.
- Financial/nutrient calculations are internally consistent now; agronomic rates
  are existing reference estimates, not newly validated scientific guidance.
- No live database, provider secrets, cloud IAM/firewall, backup restore, real push
  delivery, full browser end-to-end run, or incident logs were tested in this audit.

## Rollback

Keep the backup and the preceding deployment available. These schema additions
are additive. Roll back the application only if necessary; do not restore the
known hardcoded secret or private page caching. A rollback to vulnerable handlers
reintroduces the reported issues. Never overwrite production with a bundled demo
SQLite database.
