# Secrets rotation (do this yourself - never paste secrets in chat)
1. Supabase: Project Settings > Database > Reset database password. Copy the new session-pooler URL -> Render > Environment > DATABASE_URL. Also update the GitHub secret SUPABASE_DB_URL.
2. GitHub: Settings > Developer settings > Personal access tokens - delete old tokens, create a new one only if needed.
3. OpenWeather: API keys page - delete the exposed key, create a new one -> Render OPENWEATHER_API_KEY.
4. Google OAuth: Cloud Console > Credentials > your OAuth client > reset/add a new client secret -> Render GOOGLE_CLIENT_SECRET.
5. Gemini: AI Studio - delete the old key, create a new one -> Render GEMINI_API_KEY.
6. Render > Environment: add SECRET_KEY = a long random string (python -c "import secrets;print(secrets.token_hex(32))").
7. Optional alerts: python tools/gen_vapid.py -> Render VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_SUBJECT, plus CRON_TOKEN (random). GitHub secrets: APP_URL, CRON_TOKEN.
8. Optional backups: GitHub secrets SUPABASE_DB_URL and BACKUP_PASSPHRASE (keep the passphrase safe - without it backups cannot be opened).
