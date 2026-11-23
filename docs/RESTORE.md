# Restoring the nightly database backup (drill)

The `backup.yml` workflow uploads an **encrypted** `pg_dump` (artifact `db-backup`, kept 14 days).
A backup you have never restored is only a hope, so do this drill once and note the date in the README.
**Never restore into the live Supabase database** — use a throw-away local PostgreSQL.

1. Download the newest `db-backup` artifact from GitHub → Actions → "Nightly DB backup" and unzip it.
2. Decrypt (the key/passphrase stays on your computer; never paste it anywhere):
   * age:  `age -d -i my-age-key.txt -o backup.sql.gz greenfield-*.sql.gz.age`
   * gpg:  `gpg --decrypt -o backup.sql.gz greenfield-*.sql.gz.gpg`   (asks for the passphrase)
3. Start an empty PostgreSQL 17 (Docker):
   `docker run -d --name gf-restore -e POSTGRES_PASSWORD=drill -p 55432:5432 postgres:17`
4. Load it:
   `gunzip -c backup.sql.gz | docker exec -i gf-restore psql -U postgres -v ON_ERROR_STOP=1`
5. Check it is real data:
   `docker exec gf-restore psql -U postgres -c "SELECT (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM farms) AS farms;"`
   The counts should match the live app (demo users excluded).
6. Optional: run the app against it — `DATABASE_URL=postgresql://postgres:drill@localhost:55432/postgres python app.py` — and log in.
7. Clean up: `docker rm -f gf-restore`, then securely delete `backup.sql.gz`.

Status: **not yet performed** (the steps above are written but untested against a real backup).
