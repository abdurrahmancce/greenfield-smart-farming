# Loaded automatically by gunicorn (even if Render's Start Command is just "gunicorn app:app").
# The default 30 s worker timeout was killing photo-analysis requests (AI answers can take 10-40 s).
import os
bind = "0.0.0.0:" + os.environ.get("PORT", "10000")
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = 4            # several requests at once, so a slow AI call does not block the site
timeout = 120
graceful_timeout = 30
preload_app = True     # initialise the DB once at boot -> faster wake-up

# Do not include request paths, query strings or Referer: reset URLs carry bearer tokens.
access_log_format = '%(h)s %(t)s "%(m)s" %(s)s %(b)s %(L)s'
