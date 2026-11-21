"""
GreenField Smart Farming App — app.py v7
Flask 3 | SQLite (local) / PostgreSQL (production) | Auth | Google OAuth | Profile Photo | Full CRUD
"""
import os
import requests, sqlite3, json, hashlib, hmac, secrets, base64, string
from datetime import datetime, timedelta, timezone
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (Flask, render_template, request, redirect,
                   url_for, jsonify, flash, session, Response, abort,
                   g, has_request_context, make_response)
import i18n
import vision
import farm_tasks
import time

# ── Google OAuth ──────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_OAUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

if GOOGLE_OAUTH_ENABLED:
    from authlib.integrations.flask_client import OAuth

# ── OpenWeather ───────────────────────────────────────────────────
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY", "")

# ── Email (for password reset) ─────────────────────────────────────
# If these env vars are not set, reset links are printed to the server
# log instead of emailed — useful for local development/testing.
MAIL_SERVER   = os.environ.get("MAIL_SERVER", "")
MAIL_PORT     = int(os.environ.get("MAIL_PORT", "587"))
MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
# Render's free plan blocks SMTP ports (25/465/587), so the recommended way is an HTTPS mail API (Brevo).
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
MAIL_FROM     = os.environ.get("MAIL_FROM", "") or MAIL_USERNAME      # must be a sender verified at Brevo
MAIL_ENABLED  = bool(BREVO_API_KEY and MAIL_FROM) or bool(MAIL_SERVER and MAIL_USERNAME and MAIL_PASSWORD)
APP_BASE_URL  = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000")

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024    # photo uploads (profile photo / disease photo)
_sk = os.environ.get("SECRET_KEY", "")
if not _sk:
    # No SECRET_KEY configured: never fall back to a key that is public in the source code.
    _seed = os.environ.get("DATABASE_URL", "")
    if _seed:
        _sk = hashlib.sha256(("gf-session-v1|" + _seed).encode()).hexdigest()   # stable, not guessable
    else:
        _sk = secrets.token_hex(32)                                              # local dev: fresh per start
    print("[security] SECRET_KEY not set - derived a private key. Set SECRET_KEY in the environment.")
app.secret_key = _sk
_IS_HTTPS = os.environ.get("APP_BASE_URL", "").startswith("https://") or bool(os.environ.get("RENDER"))
_IS_PROD  = _IS_HTTPS or os.environ.get("FLASK_ENV") == "production"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_IS_HTTPS,
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
)

# ── Google OAuth setup ─────────────────────────────────────────────
if GOOGLE_OAUTH_ENABLED:
    oauth = OAuth(app)
    google = oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

# ── Database backend selection ─────────────────────────────────────
# Render provides DATABASE_URL when a PostgreSQL instance is attached.
# This is persistent storage — data survives redeploys and sleep cycles,
# unlike the free-tier filesystem which resets on every deploy.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    # Render's DATABASE_URL sometimes starts with postgres:// — psycopg2 needs postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    # Local development fallback — SQLite file on disk
    _render_disk = "/data"
    if os.path.isdir(_render_disk):
        DB_PATH = os.path.join(_render_disk, "farming.db")
    else:
        DB_PATH = os.path.join(os.path.dirname(__file__), "database", "farming.db")

# ══════════════════════════════════════════════════════════════════
#  DATABASE — dual backend (SQLite local / PostgreSQL production)
# ══════════════════════════════════════════════════════════════════
class _DictRow(dict):
    """Makes psycopg2 rows behave like sqlite3.Row: supports both
    dict-style access (row['col']), attribute access (row.col), AND
    positional integer access (row[0]) — the same as sqlite3.Row.
    RealDictCursor only gives plain dicts (string keys only), so
    without this override any `row[0]` in the codebase (e.g. reading
    a bare COUNT(*) result) raises KeyError: 0 on PostgreSQL."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __getitem__(self, key):
        if isinstance(key, int):
            # Python dicts preserve insertion order (3.7+), and
            # RealDictCursor preserves column order, so this matches
            # sqlite3.Row's positional indexing behaviour.
            return list(self.values())[key]
        return super().__getitem__(key)

class PGConnWrapper:
    """Wraps a psycopg2 connection so the rest of the app can call
    conn.execute(...) exactly like it does with sqlite3, without
    rewriting every single query in the codebase."""
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, query, params=()):
        # SQLite uses "?" placeholders, PostgreSQL uses "%s"
        pg_query = query.replace("?", "%s")
        # SQLite's AUTOINCREMENT / datetime('now') need PG equivalents
        pg_query = pg_query.replace("AUTOINCREMENT", "")
        pg_query = pg_query.replace("datetime('now')", "NOW()::text")
        pg_query = pg_query.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(pg_query, params)
        return _CursorWrapper(cur, self._conn)

    def executescript(self, script):
        cur = self._conn.cursor()
        # Split on ; but keep statements intact — PostgreSQL runs one at a time via psycopg2
        for stmt in script.replace("AUTOINCREMENT", "").split(";"):
            stmt = stmt.strip()
            if not stmt or stmt.startswith("--"):
                continue
            stmt = stmt.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
            stmt = stmt.replace("datetime('now')", "NOW()::text")
            stmt = stmt.replace("TEXT", "TEXT")  # no-op, kept for clarity
            try:
                cur.execute(stmt)
            except Exception:
                self._conn.rollback()
                continue
        self._conn.commit()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

class _CursorWrapper:
    """Wraps a psycopg2 cursor so .fetchone()/.fetchall() return
    sqlite3.Row-like objects and lastrowid works like sqlite3."""
    def __init__(self, cur, conn):
        self._cur = cur
        self._conn = conn

    def fetchone(self):
        row = self._cur.fetchone()
        return _DictRow(row) if row is not None else None

    def fetchall(self):
        return [_DictRow(r) for r in self._cur.fetchall()]

    @property
    def lastrowid(self):
        # psycopg2 doesn't support .lastrowid natively.
        # Routes that need the new row's id should use "... RETURNING id"
        # and read it via fetchone() instead (see save_fertilizer for example).
        try:
            row = self._cur.fetchone()
            return row["id"] if row else None
        except Exception:
            return None


def get_db():
    """Returns a connection object. Same .execute()/.commit()/.close()
    interface regardless of which database backend is active.
    Every connection opened during a web request is closed again when the request ends,
    even if the view crashed (otherwise errors would leak connections / keep DB locks)."""
    if USE_POSTGRES:
        conn = PGConnWrapper(psycopg2.connect(DATABASE_URL))
    else:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
    try:
        if has_request_context():
            g.setdefault("_gf_conns", []).append(conn)
    except Exception:
        pass
    return conn

@app.teardown_request
def _close_leaked_connections(exc):
    for c in g.pop("_gf_conns", []):
        try:
            c.rollback() if exc else None
        except Exception:
            pass
        try:
            c.close()
        except Exception:
            pass


def migrate_db(conn):
    """Safely add new columns to existing databases — works on both backends."""
    new_cols = [
        ("users", "phone",        "TEXT DEFAULT ''"),
        ("users", "bio",          "TEXT DEFAULT ''"),
        ("users", "location",     "TEXT DEFAULT ''"),
        ("users", "farm_name",    "TEXT DEFAULT ''"),
        ("users", "avatar_color", "TEXT DEFAULT '#2E7D32'"),
        ("users", "avatar_photo", "TEXT DEFAULT ''"),
        ("users", "google_id",    "TEXT DEFAULT ''"),
        ("users", "account_id",   "TEXT"),
        ("disease_scans", "photo_key", "TEXT DEFAULT ''"),
        ("users", "sess_ver", "INTEGER DEFAULT 0"),
        ("price_history", "user_id", "INTEGER"),
        ("price_history", "source", "TEXT DEFAULT 'live'"),
    ]
    for table, col, definition in new_cols:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass


_ACCOUNT_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "01OIL")

def _new_account_id(conn):
    """Random, human-friendly, unique ID such as GF-7K4Q9XMA."""
    for _ in range(20):
        code = "GF-" + "".join(secrets.choice(_ACCOUNT_ALPHABET) for _ in range(8))
        if not conn.execute("SELECT 1 FROM users WHERE account_id=?", (code,)).fetchone():
            return code
    return "GF-" + secrets.token_hex(6).upper()

def ensure_account_id(conn, uid):
    """Give a user an Account ID if they do not have one yet; return it."""
    row = conn.execute("SELECT account_id FROM users WHERE id=?", (uid,)).fetchone()
    if row and row["account_id"]:
        return row["account_id"]
    code = _new_account_id(conn)
    conn.execute("UPDATE users SET account_id=? WHERE id=?", (code, uid))
    conn.commit()
    return code

def backfill_account_ids(conn):
    """Assign IDs to every existing account that has none, then enforce uniqueness."""
    try:
        rows = conn.execute("SELECT id FROM users WHERE account_id IS NULL OR account_id=''").fetchall()
        for r in rows:
            ensure_account_id(conn, r["id"])
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account_id ON users(account_id)")
        conn.commit()
    except Exception as e:
        print("[account_id backfill]", e)
        try: conn.rollback()
        except Exception: pass


def init_db():
    if not USE_POSTGRES:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    migrate_db(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            email        TEXT    NOT NULL UNIQUE,
            password     TEXT    NOT NULL,
            role         TEXT    NOT NULL DEFAULT 'farmer',
            phone        TEXT    DEFAULT '',
            bio          TEXT    DEFAULT '',
            location     TEXT    DEFAULT '',
            farm_name    TEXT    DEFAULT '',
            avatar_color TEXT    DEFAULT '#2E7D32',
            avatar_photo TEXT    DEFAULT '',
            google_id    TEXT    DEFAULT '',
            account_id   TEXT,
            created_at   TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS password_resets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            token      TEXT    NOT NULL UNIQUE,
            expires_at TEXT    NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS farms (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            farm_name     TEXT    NOT NULL,
            crop_type     TEXT    NOT NULL,
            location      TEXT    NOT NULL,
            area          REAL    NOT NULL,
            planting_date TEXT    NOT NULL,
            status        TEXT    NOT NULL DEFAULT 'Active',
            created_at    TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS crop_notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            farm_id    INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            title      TEXT    NOT NULL DEFAULT 'Observation',
            note       TEXT    NOT NULL,
            category   TEXT    NOT NULL DEFAULT 'General',
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS fertilizer_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            crop_type  TEXT    NOT NULL,
            area       REAL    NOT NULL,
            n_kg       REAL    NOT NULL,
            p_kg       REAL    NOT NULL,
            k_kg       REAL    NOT NULL,
            total_kg   REAL    NOT NULL,
            urea_kg    REAL    NOT NULL,
            label      TEXT    DEFAULT '',
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            action     TEXT    NOT NULL,
            target     TEXT    NOT NULL,
            detail     TEXT    DEFAULT '',
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS crop_growth (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            farm_id        INTEGER NOT NULL,
            user_id        INTEGER NOT NULL,
            planting_date  TEXT    NOT NULL,
            expected_days  INTEGER NOT NULL DEFAULT 90,
            harvest_date   TEXT    DEFAULT '',
            growth_stage   TEXT    NOT NULL DEFAULT 'Seedling',
            notes          TEXT    DEFAULT '',
            created_at     TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS irrigation_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            farm_id      INTEGER NOT NULL,
            user_id      INTEGER NOT NULL,
            date         TEXT    NOT NULL,
            water_liters REAL    NOT NULL DEFAULT 0,
            method       TEXT    NOT NULL DEFAULT 'Manual',
            duration_min INTEGER NOT NULL DEFAULT 0,
            notes        TEXT    DEFAULT '',
            created_at   TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS disease_scans (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            farm_id       INTEGER NOT NULL DEFAULT 0,
            crop          TEXT    DEFAULT '',
            diagnosis     TEXT    DEFAULT '',
            health_status TEXT    DEFAULT '',
            confidence    INTEGER DEFAULT 0,
            severity      TEXT    DEFAULT '',
            result_json   TEXT    NOT NULL,
            thumb         TEXT    DEFAULT '',
            lang          TEXT    DEFAULT 'en',
            photo_key     TEXT    DEFAULT '',
            created_at    TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS price_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            crop       TEXT    NOT NULL,
            price      REAL    NOT NULL,
            unit       TEXT    DEFAULT 'kg',
            day        TEXT    NOT NULL,
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS push_subs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            endpoint   TEXT    NOT NULL UNIQUE,
            p256dh     TEXT    NOT NULL,
            auth       TEXT    NOT NULL,
            lang       TEXT    DEFAULT 'en',
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS offline_sync (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            cid     TEXT    NOT NULL,
            UNIQUE (user_id, cid)
        );
        CREATE TABLE IF NOT EXISTS push_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task_id TEXT    NOT NULL,
            day     TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS expense_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            farm_id     INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            type        TEXT    NOT NULL DEFAULT 'expense',
            category    TEXT    NOT NULL DEFAULT 'Other',
            amount      REAL    NOT NULL,
            description TEXT    DEFAULT '',
            date        TEXT    NOT NULL,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sensor_devices (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            farm_id    INTEGER NOT NULL,
            name       TEXT    NOT NULL,
            token_hash TEXT    NOT NULL UNIQUE,
            token_hint TEXT    DEFAULT '',
            created_at TEXT    DEFAULT '',
            last_seen  TEXT    DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id  INTEGER NOT NULL,
            farm_id    INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            moisture   REAL    NOT NULL,
            temp       REAL,
            source     TEXT    DEFAULT 'device',
            created_at TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sensor_readings_farm ON sensor_readings (farm_id, id);
        CREATE INDEX IF NOT EXISTS idx_sensor_readings_dev ON sensor_readings (device_id, id);
        CREATE TABLE IF NOT EXISTS forecast_inputs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL,
            farm_id        INTEGER NOT NULL,
            yield_per_acre REAL,
            price_per_kg   REAL,
            remaining_cost REAL,
            updated_at     TEXT DEFAULT '',
            UNIQUE (user_id, farm_id)
        );
    """)
    migrate_db(conn)          # re-run: adds any column a pre-existing table is missing
    backfill_account_ids(conn)  # every account gets a unique Account ID
    conn.commit()
    conn.close()


def log_activity(action, target, detail=""):
    try:
        conn = get_db()
        conn.execute("INSERT INTO activity_log (action,target,detail) VALUES (?,?,?)",
                     (action, target, detail))
        conn.commit()
        conn.close()
    except Exception:
        pass


def send_reset_email(to_email, name, reset_link):
    """
    Sends the password reset link via SMTP if MAIL_* env vars are configured.
    If email is not configured (e.g. local dev), the link is printed to the
    server log instead so the flow can still be tested end-to-end.
    """
    if not MAIL_ENABLED:
        if _IS_PROD:
            # A reset link is a password: never write it to production logs.
            print("[PASSWORD RESET] Email is not configured - no link was sent (set MAIL_* to enable resets).")
            return False
        print("=" * 60)
        print(f"[PASSWORD RESET] Email not configured (dev mode) - link for {to_email}:")
        print(reset_link)
        print("=" * 60)
        return True

    import smtplib, html as _html
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    name = _html.escape(str(name or ""))[:80]
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Reset your GreenField password"
        msg["From"] = MAIL_FROM or MAIL_USERNAME
        msg["To"] = to_email

        text_body = f"""Hi {name},

We received a request to reset your GreenField password.
Click the link below to set a new password (valid for 1 hour):

{reset_link}

If you didn't request this, you can safely ignore this email.

— GreenField Smart Farming
"""
        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto">
          <h2 style="color:#2E7D32">🌱 Reset your password</h2>
          <p>Hi {name},</p>
          <p>We received a request to reset your GreenField password.
          Click the button below (valid for 1 hour):</p>
          <p style="text-align:center;margin:28px 0">
            <a href="{reset_link}" style="background:#2E7D32;color:#fff;
              padding:12px 28px;border-radius:8px;text-decoration:none;
              font-weight:bold">Reset Password</a>
          </p>
          <p style="color:#777;font-size:13px">If you didn't request this,
          you can safely ignore this email.</p>
        </div>
        """
        if BREVO_API_KEY and MAIL_FROM:
            r = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": BREVO_API_KEY, "accept": "application/json"},
                json={"sender": {"name": "GreenField", "email": MAIL_FROM},
                      "to": [{"email": to_email}],
                      "subject": "Reset your GreenField password",
                      "htmlContent": html_body, "textContent": text_body},
                timeout=10)
            if r.status_code in (200, 201, 202):
                return True
            try:                                   # Brevo explains the refusal ("unauthorized", "invalid_parameter"...); no secrets in it
                why = str((r.json() or {}).get("message", ""))[:160]
            except Exception:
                why = ""
            print(f"[PASSWORD RESET] Mail API refused the message: HTTP {r.status_code} {why}")
            return False
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT, timeout=10) as server:
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_USERNAME, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[PASSWORD RESET] Email send failed: {type(e).__name__}")
        if not _IS_PROD:
            print(f"[PASSWORD RESET] Fallback link for {to_email}: {reset_link}")
        return False

# ══════════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ══════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
#  SECURITY HELPERS
# ══════════════════════════════════════════════════════════════════
from markupsafe import escape as _esc
import threading
from urllib.parse import urlparse

_throttle_lock = threading.Lock()
_throttle_hits = {}          # key -> [timestamps]

def client_ip():
    """Render's proxy appends the real client address as the LAST X-Forwarded-For entry."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[-1].strip()[:64]
    return (request.remote_addr or "?")[:64]

def throttle_blocked(key, limit, window):
    """True if `key` already has `limit` hits within `window` seconds (read-only check)."""
    now = time.time()
    with _throttle_lock:
        hits = [t for t in _throttle_hits.get(key, []) if now - t < window]
        _throttle_hits[key] = hits
        return len(hits) >= limit

def throttle_hit(key):
    with _throttle_lock:
        _throttle_hits.setdefault(key, []).append(time.time())
        if len(_throttle_hits) > 5000:                      # keep memory bounded
            cutoff = time.time() - 3600
            for k in [k for k, v in _throttle_hits.items() if not v or v[-1] < cutoff]:
                _throttle_hits.pop(k, None)

def throttle_clear(key):
    with _throttle_lock:
        _throttle_hits.pop(key, None)

def safe_next(url):
    """Only allow redirects to a path on this same site (blocks open-redirect via ?next=)."""
    if not url or not isinstance(url, str):
        return None
    if not url.startswith("/") or url.startswith("//") or "\\" in url:
        return None
    p = urlparse(url)
    return url if not p.netloc and not p.scheme else None

def hash_token(t):
    return hashlib.sha256(t.encode()).hexdigest()

MIN_PASSWORD = 8
_DUMMY_HASH = generate_password_hash("gf-dummy-password-for-timing")

@app.before_request
def check_session_version():
    """Password change/reset bumps users.sess_ver - every older login is signed out."""
    if "user_id" not in session or request.path.startswith("/static") or request.path in ("/healthz", "/sw.js", "/offline"):
        return None
    try:
        conn = get_db()
        row = conn.execute("SELECT sess_ver FROM users WHERE id=?", (session["user_id"],)).fetchone()
        conn.close()
    except Exception:
        return None                                   # never lock people out because of a DB hiccup
    if not row:
        session.clear()
        return None
    cur = int(row["sess_ver"] or 0)
    if "sv" not in session:
        session["sv"] = cur                           # sessions that pre-date this feature adopt the current version
    elif session["sv"] != cur:
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"error": "Session expired. Please log in again."}), 401
        flash("Your password was changed - please log in again.", "error")
        return redirect(url_for("login"))
    return None

def sniff_image(b):
    """Look at the real file bytes (not the client's claim). Returns a MIME type or None."""
    if b[:3] == b"\xff\xd8\xff": return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n": return "image/png"
    if b[:6] in (b"GIF87a", b"GIF89a"): return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP": return "image/webp"
    return None

def bump_sessions(conn, uid):
    conn.execute("UPDATE users SET sess_ver=COALESCE(sess_ver,0)+1 WHERE id=?", (uid,))
    r = conn.execute("SELECT sess_ver FROM users WHERE id=?", (uid,)).fetchone()
    return int(r["sess_ver"] or 0)

# ── input validation helpers ──────────────────────────────────────
import math
def clip(v, n):
    """Trim a text input to at most n characters."""
    return (v or "").strip()[:n] if isinstance(v, str) or v is None else str(v)[:n]

def to_float(v, lo=None, hi=None, default=None):
    """Parse a finite number inside [lo, hi]; anything else -> default."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x) or (lo is not None and x < lo) or (hi is not None and x > hi):
        return default
    return x

def to_int(v, lo=None, hi=None, default=None):
    x = to_float(v, lo, hi, None)
    return default if x is None else int(x)

def valid_date(v):
    """Return the date as YYYY-MM-DD if it is a real date in a sensible range, else None."""
    try:
        d = datetime.strptime((v or "").strip(), "%Y-%m-%d")
    except ValueError:
        return None
    return d.strftime("%Y-%m-%d") if 1990 <= d.year <= 2100 else None

def owned_farm_id(conn, uid, raw):
    """The farm id as int - but only if it belongs to this user (blocks IDOR), else None."""
    fid = to_int(raw, 1, 2**31 - 1)
    if fid is None:
        return None
    row = conn.execute("SELECT id FROM farms WHERE id=? AND user_id=?", (fid, uid)).fetchone()
    return fid if row else None

def delete_user_data(conn, uid):
    """Remove EVERYTHING that belongs to a user (used by 'delete account')."""
    u = conn.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    for t in ("expense_log", "irrigation_log", "crop_growth", "crop_notes", "disease_scans",
              "fertilizer_history", "push_log", "push_subs", "password_resets", "price_history", "offline_sync",
              "sensor_readings", "sensor_devices", "forecast_inputs"):
        conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
    if u and u["email"]:                              # the activity log mentions the e-mail address
        conn.execute("DELETE FROM activity_log WHERE detail LIKE ?", ("%" + u["email"] + "%",))
    conn.execute("DELETE FROM farms WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))

@app.before_request
def csrf_origin_check():
    """CSRF defence: a state-changing browser request must come from this same site."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        src = request.headers.get("Origin") or request.headers.get("Referer")
        if src:
            if urlparse(src).netloc.lower() != request.host.lower():
                return jsonify({"error": "Blocked: cross-site request."}), 403
        elif request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify({"error": "Blocked: cross-site request."}), 403

@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=(self)")
    nonce = g.get("csp_nonce")
    script_src = "script-src 'self'" + (f" 'nonce-{nonce}'" if nonce else "")
    resp.headers.setdefault("Content-Security-Policy", "; ".join([
        "default-src 'self'",
        script_src,                                   # no CDN scripts, no inline handlers, no eval
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: blob: https:",          # OpenStreetMap tiles, Google profile photos
        "connect-src 'self' https://nominatim.openstreetmap.org",
        "worker-src 'self'", "manifest-src 'self'", "media-src 'self' blob:",
        "base-uri 'self'", "object-src 'none'", "frame-ancestors 'self'", "form-action 'self'"]))
    if request.path.startswith(("/account/", "/profile")) or "attachment" in resp.headers.get("Content-Disposition", ""):
        resp.headers["Cache-Control"] = "no-store"
    if _IS_HTTPS:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp

def login_required(f):
    """Decorator — redirects to /login if not logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            if request.headers.get("X-GF-Fetch"):          # called by our own JavaScript, not a page visit
                return jsonify({"ok": False, "msg": "login"}), 401
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

def current_user():
    """Return the logged-in user row, or None."""
    if "user_id" not in session:
        return None
    conn = get_db()
    user = conn.execute(
        "SELECT id, name, email, role, created_at, avatar_color, avatar_photo, account_id FROM users WHERE id=?",
        (session["user_id"],)
    ).fetchone()
    if user and not user["account_id"]:
        ensure_account_id(conn, user["id"])
        user = conn.execute(
            "SELECT id, name, email, role, created_at, avatar_color, avatar_photo, account_id FROM users WHERE id=?",
            (session["user_id"],)
        ).fetchone()
    conn.close()
    return user

# Inject user into every template automatically
def _csp_nonce():
    """One random nonce per request; templates put it on their inline <script> tags."""
    if "csp_nonce" not in g:
        g.csp_nonce = secrets.token_urlsafe(16)
    return g.csp_nonce

@app.context_processor
def inject_user():
    lang = session.get("lang", "en")
    user = current_user()
    avatar_url = ""
    if user and user["avatar_photo"]:
        photo = user["avatar_photo"]
        ver = hashlib.md5((str(len(photo)) + photo[-200:]).encode(), usedforsecurity=False).hexdigest()[:8]
        avatar_url = url_for("avatar", uid=user["id"], v=ver)
    return {"csp_nonce": _csp_nonce(), 
        "current_user": user,
        "lang": lang,
        "is_bn": lang == "bn",
        "avatar_url": avatar_url,
        "is_admin": is_admin(user),
        "storage_label": "Secure Cloud Database (PostgreSQL)" if USE_POSTGRES else "Local SQLite Database",
    }

# ── Language layer: every page is authored in English, translated on the way out ──
@app.after_request
def apply_language(resp):
    try:
        if (resp.status_code == 200 and resp.mimetype == "text/html"
                and not resp.direct_passthrough and request.endpoint not in (None, "static")):
            body = resp.get_data(as_text=True)
            if session.get("lang") == "bn":
                body = i18n.translate_html(body).replace('<html lang="en"', '<html lang="bn"', 1)
            else:
                body = i18n.polish_html(body)
            resp.set_data(body)
    except Exception as e:
        print("[language layer]", e)
    return resp

# ── Profile photo, served as a cacheable image instead of inlined base64 ──
@app.route("/avatar/<int:uid>")
def avatar(uid):
    if session.get("user_id") != uid:
        abort(404)
    conn = get_db()
    row = conn.execute("SELECT avatar_photo FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    data = (row["avatar_photo"] if row else "") or ""
    if not data.startswith("data:") or ";base64," not in data:
        abort(404)
    head, b64 = data.split(",", 1)
    mime = head[5:].split(";")[0] or "image/jpeg"
    resp = Response(base64.b64decode(b64), mimetype=mime)
    resp.headers["Cache-Control"] = "private, max-age=2592000, immutable"
    return resp

# ══════════════════════════════════════════════════════════════════
#  DOMAIN HELPERS
# ══════════════════════════════════════════════════════════════════
CROP_ICONS = {"rice":"seedling","wheat":"wheat-awn","maize":"leaf",
              "tomato":"apple-alt","potato":"circle","jute":"spa",
              "mustard":"sun","other":"leaf"}
def crop_icon(c): return CROP_ICONS.get(c.lower(),"leaf")
app.jinja_env.globals["crop_icon"] = crop_icon

CROP_WATER    = {"rice":"35–40 mm/wk","wheat":"20–25 mm/wk","maize":"25–30 mm/wk",
                 "tomato":"30–35 mm/wk","potato":"28–32 mm/wk",
                 "jute":"15–20 mm/wk","mustard":"18–22 mm/wk"}
CROP_INTERVAL = {"rice":3,"wheat":5,"maize":4,"tomato":3,"potato":4,"jute":6,"mustard":5}

CROP_NPK = {
    "rice":{"N":60,"P":30,"K":20},    "wheat":{"N":80,"P":40,"K":30},
    "maize":{"N":100,"P":50,"K":40},  "tomato":{"N":120,"P":60,"K":80},
    "potato":{"N":90,"P":70,"K":100}, "jute":{"N":50,"P":20,"K":15},
    "mustard":{"N":40,"P":20,"K":15}, "default":{"N":60,"P":30,"K":30},
}
def calc_fertilizer(crop, area):
    r = CROP_NPK.get(crop.lower(), CROP_NPK["default"])
    return {"N":round(r["N"]*area,1),"P":round(r["P"]*area,1),"K":round(r["K"]*area,1),
            "total":round((r["N"]+r["P"]+r["K"])*area,1),
            "urea":round(r["N"]*area/0.46,1),"dap":round(r["P"]*area/0.46,1)}

# ══════════════════════════════════════════════════════════════════
#  WEATHER
# ══════════════════════════════════════════════════════════════════
def _owm_icon(code):
    if code.startswith("01"): return "sun"
    if code.startswith("02"): return "cloud-sun"
    if code.startswith(("03","04")): return "cloud"
    if code.startswith(("09","10")): return "cloud-rain"
    if code.startswith("11"): return "bolt"
    if code.startswith("13"): return "snowflake"
    if code.startswith("50"): return "smog"
    return "cloud-sun"

def _owm_tip(d):
    t,h,w = d["temperature"],d["humidity"],d["wind_speed"]
    if t>=35:  return "Extreme heat — water at dawn and dusk only."
    if t<=10:  return "Cold stress risk — protect seedlings tonight."
    if h>=85:  return "High humidity — watch for fungal disease."
    if h<=35:  return "Low humidity — increase irrigation frequency."
    if w>=40:  return "Strong winds — delay spraying and secure tall crops."
    return "Conditions look good for field operations today."

_wx_cache = {}
def get_weather(city="Chittagong"):
    city = clip(city, 60) or "Chittagong"
    k = city.lower()
    hit = _wx_cache.get(k)
    if hit and time.time() - hit[0] < 600:
        return dict(hit[1])
    data = _get_weather_uncached(city)
    if len(_wx_cache) > 300:
        _wx_cache.clear()
    _wx_cache[k] = (time.time(), data)
    return dict(data)

def _get_weather_uncached(city="Chittagong"):
    import urllib.request, urllib.parse
    if OPENWEATHER_KEY:
        try:
            q = urllib.parse.quote(city)
            with urllib.request.urlopen(
                f"https://api.openweathermap.org/data/2.5/weather"
                f"?q={q}&appid={OPENWEATHER_KEY}&units=metric", timeout=5) as r:
                raw = json.loads(r.read())
            with urllib.request.urlopen(
                f"https://api.openweathermap.org/data/2.5/forecast"
                f"?q={q}&appid={OPENWEATHER_KEY}&units=metric&cnt=40", timeout=5) as r:
                fr = json.loads(r.read())

            # UV Index requires lat/lon via the free "uvi" endpoint —
            # falls back to "—" only if this specific call fails,
            # not the whole weather fetch.
            uv_index = "—"
            try:
                lat, lon = raw["coord"]["lat"], raw["coord"]["lon"]
                with urllib.request.urlopen(
                    f"https://api.openweathermap.org/data/2.5/uvi"
                    f"?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}", timeout=4) as r2:
                    uv_data = json.loads(r2.read())
                    uv_index = round(uv_data.get("value", 0), 1)
            except Exception:
                pass  # UV endpoint unavailable on some free-tier keys — keep dash rather than fail the whole request

            # OpenWeather's free plan gives 3-hourly data for ~5 days: group it by calendar day.
            days_map, order = {}, []
            for item in fr.get("list", []):
                d = item["dt_txt"][:10]
                if d not in days_map:
                    days_map[d] = []; order.append(d)
                days_map[d].append(item)
            forecast = []
            for d in order[:6]:
                its = days_map[d]
                pick = min(its, key=lambda x: abs(int(x["dt_txt"][11:13]) - 12))      # slot closest to midday
                rain = sum((x.get("rain") or {}).get("3h", 0) or 0 for x in its)
                forecast.append({"day": datetime.strptime(d, "%Y-%m-%d").strftime("%a"),
                                 "temp": round(max(x["main"]["temp_max"] for x in its)),
                                 "lo": round(min(x["main"]["temp_min"] for x in its)),
                                 "rain": round(rain, 1),
                                 "icon": _owm_icon(pick["weather"][0]["icon"]),
                                 "desc": pick["weather"][0]["main"]})
            data = {"city":raw.get("name",city),"country":raw["sys"].get("country",""),
                    "temperature":round(raw["main"]["temp"]),"feels_like":round(raw["main"]["feels_like"]),
                    "temp_min":round(raw["main"]["temp_min"]),"temp_max":round(raw["main"]["temp_max"]),
                    "humidity":raw["main"]["humidity"],"wind_speed":round(raw["wind"]["speed"]*3.6),
                    "condition":raw["weather"][0]["main"],"description":raw["weather"][0]["description"].capitalize(),
                    "icon":_owm_icon(raw["weather"][0]["icon"]),
                    "visibility":round(raw.get("visibility",10000)/1000,1),
                    "pressure":raw["main"]["pressure"],"uv_index":uv_index,"clouds":raw.get("clouds",{}).get("all",0),
                    "sunrise":datetime.fromtimestamp(raw["sys"]["sunrise"]).strftime("%H:%M"),
                    "sunset":datetime.fromtimestamp(raw["sys"]["sunset"]).strftime("%H:%M"),
                    "forecast":forecast,"source":"live","fetched_at":datetime.now().strftime("%H:%M:%S")}
            data["tip"] = _owm_tip(data)
            return data
        except Exception as e:
            print("[weather] live fetch failed:", type(e).__name__); m = _mock_weather(city); m["api_error"] = True; return m
    return _mock_weather(city)

def _mock_weather(city="Chittagong"):
    seed = int(hashlib.md5(city.lower().encode(), usedforsecurity=False).hexdigest()[:4],16) % 20
    cond = ["Partly Cloudy","Sunny","Overcast","Light Rain"][seed%4]
    imap = {"Partly Cloudy":"cloud-sun","Sunny":"sun","Overcast":"cloud","Light Rain":"cloud-rain"}
    t    = 27+seed%8
    days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    ic   = ["cloud-sun","sun","cloud","cloud-rain","sun","sun","cloud-sun"]
    forecast = [{"day":days[i],"temp":t+(i%3)-1,"icon":ic[i],"desc":cond,"lo":t-5,"rain":0} for i in range(5)]
    data = {"city":city,"country":"BD","temperature":t,"feels_like":t+2,"temp_min":t-2,"temp_max":t+4,
            "humidity":62+seed%20,"wind_speed":10+seed%14,"condition":cond,
            "description":"Good conditions for farming today.","icon":imap[cond],
            "visibility":8+seed%5,"pressure":1010+seed%8,"uv_index":4+seed%5,"clouds":seed*3,
            "sunrise":"06:12","sunset":"18:34","forecast":forecast,
            "source":"mock","fetched_at":datetime.now().strftime("%H:%M:%S")}
    data["tip"] = _owm_tip(data)
    return data

# ══════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════════════
@app.route("/register", methods=["GET","POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name     = request.form.get("name","").strip()
        email    = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        confirm  = request.form.get("confirm","")
        errors   = []
        if not name:              errors.append("Full name is required.")
        if not email:             errors.append("Email is required.")
        if len(password) < MIN_PASSWORD: errors.append(f"Password must be at least {MIN_PASSWORD} characters.")
        if throttle_blocked("reg:" + client_ip(), 10, 3600):
            errors.append("Too many sign-up attempts from this network. Please try again later.")
        if password != confirm:   errors.append("Passwords do not match.")
        if not errors:
            throttle_hit("reg:" + client_ip())
            conn = get_db()
            if conn.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone():
                errors.append("An account with this email already exists.")
            else:
                conn.execute(
                    "INSERT INTO users (name,email,password) VALUES (?,?,?)",
                    (name, email, generate_password_hash(password))
                )
                conn.commit()
                user = conn.execute("SELECT id,name FROM users WHERE email=?",(email,)).fetchone()
                ensure_account_id(conn, user["id"])
                session["user_id"]   = user["id"]
                session["user_name"] = user["name"]
                session["sv"]        = 0                  # brand-new account: session version 0
                conn.close()
                session.permanent = True
                flash(f"🌱 Welcome to GreenField, <strong>{_esc(name)}</strong>! Your account is ready.", "success")
                return redirect(url_for("dashboard"))
            conn.close()
        for e in errors: flash(e, "error")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email    = request.form.get("email","").strip().lower()[:200]
        password = request.form.get("password","")[:1000]
        ip       = client_ip()
        k_ip, k_em = "login-ip:" + ip, "login-em:" + email
        if throttle_blocked(k_ip, 25, 900) or throttle_blocked(k_em, 6, 900):
            log_activity("blocked", "login", f"throttled {email}")
            flash("Too many failed sign-in attempts. Please wait 15 minutes and try again, "
                  "or use “Forgot password”.", "error")
            return render_template("login.html", google_enabled=GOOGLE_OAUTH_ENABLED), 429
        conn     = get_db()
        user     = conn.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        conn.close()
        # Always run one password hash check so timing does not reveal whether the email exists.
        ok = check_password_hash(user["password"] if user else _DUMMY_HASH, password) and bool(user)
        if ok:
            throttle_clear(k_em)
            _lang = session.get("lang")
            session.clear()
            if _lang: session["lang"] = _lang
            session.permanent = True
            session["user_id"]   = user["id"]
            session["user_name"] = user["name"]
            try: session["sv"] = int(user["sess_ver"] or 0)
            except Exception: pass
            flash(f"👋 Welcome back, <strong>{_esc(user['name'])}</strong>!", "success")
            return redirect(safe_next(request.args.get("next")) or url_for("dashboard"))
        throttle_hit(k_ip); throttle_hit(k_em)
        flash("Invalid email or password. Please try again.", "error")
    return render_template("login.html", google_enabled=GOOGLE_OAUTH_ENABLED)

@app.route("/logout")
def logout():
    _lang = session.get("lang")
    session.clear()
    if _lang: session["lang"] = _lang
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ── Try-demo accounts ───────────────────────────────────────────────
# Every click makes its OWN short-lived account filled with sample data, so visitors can look around without
# registering, nobody shares a password, and nobody sees anyone else's edits. Demo accounts are deleted after
# DEMO_TTL_HOURS, cannot change e-mail/password, and cannot use the paid AI photo scan or push alerts.
DEMO_TTL_HOURS = 24
DEMO_MAX_USERS = 150          # hard cap so the demo can never fill the free database
DEMO_PER_IP    = 6            # new demo accounts per network per hour

def is_demo():
    return bool(session.get("demo"))

def demo_block_json():
    return jsonify({"error": "This feature is switched off in the demo account. Register a free account to use it."}), 403

def purge_old_demos(conn):
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=DEMO_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    for r in conn.execute("SELECT id FROM users WHERE role='demo' AND created_at<?", (cutoff,)).fetchall():
        delete_user_data(conn, r["id"])

def seed_demo_data(conn, uid):
    """Sample farms, costs, logs and a dry-soil sensor so every page has something real-looking to show."""
    today = datetime.now(timezone.utc).replace(tzinfo=None).date()
    def d(days_ago): return (today - timedelta(days=days_ago)).isoformat()
    farms = [("Hurricane Plot", "Rice",   "Chittagong", 8.0, 70, "Active"),
             ("Cactus Field",   "Tomato", "Sylhet",     5.5, 35, "Planted"),
             ("North Block",    "Wheat",  "Barishal",   4.0, 50, "Planted")]
    ids = []
    for name, crop, loc, area, age, status in farms:
        conn.execute("INSERT INTO farms (user_id,farm_name,crop_type,location,area,planting_date,status) VALUES (?,?,?,?,?,?,?)",
                     (uid, name, crop, loc, area, d(age), status))
        ids.append(conn.execute("SELECT id FROM farms WHERE user_id=? AND farm_name=?", (uid, name)).fetchone()["id"])
    rice, tomato, wheat = ids
    for fid, typ, cat, amt, desc, ago in [
            (rice, "expense", "Seeds", 6500, "Seed paddy", 68), (rice, "expense", "Fertilizer", 14200, "Urea + TSP", 40),
            (rice, "expense", "Labour", 18000, "Transplanting crew", 62),
            (tomato, "expense", "Seeds", 4200, "Seedlings", 33), (tomato, "expense", "Pesticide", 3100, "Fungicide spray", 12),
            (wheat, "expense", "Fertilizer", 7600, "Basal dose", 45), (wheat, "income", "Sale", 5000, "Early green sale", 3)]:
        conn.execute("INSERT INTO expense_log (farm_id,user_id,type,category,amount,description,date) VALUES (?,?,?,?,?,?,?)",
                     (fid, uid, typ, cat, amt, desc, d(ago)))
    for fid, ago, liters, method, mins in [(rice, 9, 9000, "Flood", 120), (rice, 14, 8500, "Flood", 110),
                                           (tomato, 4, 1800, "Drip", 45), (tomato, 8, 1700, "Drip", 45)]:
        conn.execute("INSERT INTO irrigation_log (farm_id,user_id,date,water_liters,method,duration_min,notes) VALUES (?,?,?,?,?,?,?)",
                     (fid, uid, d(ago), liters, method, mins, "Demo entry"))
    for fid, ago, days, stage in [(rice, 70, 120, "Vegetative"), (tomato, 35, 90, "Flowering"), (wheat, 50, 110, "Vegetative")]:
        conn.execute("INSERT INTO crop_growth (farm_id,user_id,planting_date,expected_days,harvest_date,growth_stage,notes) VALUES (?,?,?,?,?,?,?)",
                     (fid, uid, d(ago), days, (today + timedelta(days=days - ago)).isoformat(), stage, "Demo entry"))
    conn.execute("INSERT INTO crop_notes (farm_id,user_id,title,note,category) VALUES (?,?,?,?,?)",
                 (rice, uid, "Water level", "Field was drying at the edges; top up this week.", "Irrigation"))
    # a soil sensor whose last reading is dry -> shows the "Soil is dry" task and the chart
    conn.execute("INSERT INTO sensor_devices (user_id,farm_id,name,token_hash,token_hint,created_at,last_seen) VALUES (?,?,?,?,?,?,?)",
                 (uid, tomato, "Demo probe", hash_token(secrets.token_urlsafe(32)), "demo", _utcnow_str(), _utcnow_str()))
    dev = conn.execute("SELECT id FROM sensor_devices WHERE user_id=?", (uid,)).fetchone()["id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i, (m, t) in enumerate([(46, 27.5), (42, 28.4), (39, 29.6), (35, 30.1), (31, 29.2), (27, 28.0), (24, 26.8), (22, 26.1)]):
        ts = (now - timedelta(minutes=(7 - i) * 30)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO sensor_readings (device_id,farm_id,user_id,moisture,temp,source,created_at) VALUES (?,?,?,?,?,?,?)",
                     (dev, tomato, uid, m, t, "device", ts))
    # sample forecast inputs (illustrative numbers, shown as the farmer's own)
    for fid, y, price, rem in [(rice, 1700, 34, 22000), (tomato, 6000, 22, 12000), (wheat, 1100, 45, 6000)]:
        conn.execute("INSERT INTO forecast_inputs (user_id,farm_id,yield_per_acre,price_per_kg,remaining_cost,updated_at) VALUES (?,?,?,?,?,?)",
                     (uid, fid, y, price, rem, _utcnow_str()))

@app.route("/demo", methods=["POST"])
def start_demo():
    ip = client_ip()
    if throttle_blocked("demo:" + ip, DEMO_PER_IP, 3600):
        flash("Too many demo sessions from this network. Please try again in a while.", "error")
        return redirect(url_for("login"))
    conn = get_db()
    purge_old_demos(conn)
    if conn.execute("SELECT COUNT(*) FROM users WHERE role='demo'").fetchone()[0] >= DEMO_MAX_USERS:
        conn.commit(); conn.close()
        flash("The demo is very busy right now. Please try again shortly, or register a free account.", "error")
        return redirect(url_for("login"))
    throttle_hit("demo:" + ip)
    tag = secrets.token_hex(5)
    conn.execute("INSERT INTO users (name,email,password,role) VALUES (?,?,?,?)",
                 ("Demo Farmer", f"demo-{tag}@demo.invalid", generate_password_hash(secrets.token_urlsafe(32)), "demo"))
    uid = conn.execute("SELECT id FROM users WHERE email=?", (f"demo-{tag}@demo.invalid",)).fetchone()["id"]
    ensure_account_id(conn, uid)
    seed_demo_data(conn, uid)
    conn.commit(); conn.close()
    _lang = session.get("lang")
    session.clear()
    if _lang: session["lang"] = _lang
    session["user_id"] = uid; session["user_name"] = "Demo Farmer"; session["sv"] = 0; session["demo"] = True
    session.permanent = False                       # ends when the browser closes
    flash("👋 You are in a demo account with sample data. It is deleted after 24 hours. "
          "<a href='/register'>Register</a> to keep your own farms.", "success")
    return redirect(url_for("dashboard"))


# ── Google OAuth Routes ─────────────────────────────────────────────
@app.route("/login/google")
def google_login():
    if not GOOGLE_OAUTH_ENABLED:
        flash("Google login is not configured.", "error")
        return redirect(url_for("login"))
    redirect_uri = url_for("google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/login/google/callback")
def google_callback():
    if not GOOGLE_OAUTH_ENABLED:
        return redirect(url_for("login"))
    try:
        token = google.authorize_access_token()
        user_info = token.get("userinfo")
        if not user_info:
            flash("Could not get user info from Google.", "error")
            return redirect(url_for("login"))
        google_id = user_info.get("sub", "")
        email     = user_info.get("email", "").lower()
        if not google_id or not email or user_info.get("email_verified") is not True:
            flash("Your Google email is not verified, so we cannot sign you in with it.", "error")
            return redirect(url_for("login"))
        name      = user_info.get("name", "Google User")
        picture   = user_info.get("picture", "")

        conn = get_db()
        # Check if user exists by google_id or email
        existing = conn.execute("SELECT * FROM users WHERE google_id=?", (google_id,)).fetchone()
        if not existing:
            existing = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if existing and existing["google_id"]:
                conn.close()                       # that email belongs to a different Google account
                flash("This email is already linked to another Google account.", "error")
                return redirect(url_for("login"))

        if existing:
            # First Google sign-in on an account that was created with email + password.
            # Anyone could have registered this address earlier (nothing verified it), so the
            # old password is thrown away: the verified Google owner now owns the account.
            if not existing["google_id"]:
                conn.execute("UPDATE users SET google_id=?, password=? WHERE id=?",
                             (google_id, generate_password_hash(secrets.token_hex(32)), existing["id"]))
                bump_sessions(conn, existing["id"])
                conn.commit()
            uid  = existing["id"]
            uname = existing["name"]
        else:
            # Register new user via Google
            fake_pw = generate_password_hash(secrets.token_hex(32))
            conn.execute(
                "INSERT INTO users (name, email, password, google_id) VALUES (?,?,?,?)",
                (name, email, fake_pw, google_id)
            )
            conn.commit()
            new_user = conn.execute("SELECT id, name FROM users WHERE email=?", (email,)).fetchone()
            ensure_account_id(conn, new_user["id"])
            uid   = new_user["id"]
            uname = new_user["name"]

        sv_row = conn.execute("SELECT sess_ver FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
        session.clear()                            # fresh session (no fixation)
        session["sv"] = int((sv_row["sess_ver"] if sv_row else 0) or 0)
        session["user_id"]   = uid
        session["user_name"] = uname
        session["user_email"]= email
        session.permanent = True
        flash(f"✅ Logged in with Google as {_esc(uname)}.", "success")
        return redirect(url_for("dashboard"))
    except Exception as e:
        flash("Google login failed. Please try again.", "error")
        return redirect(url_for("login"))


# ── Forgot / Reset Password ─────────────────────────────────────────
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:200]
        k = "forgot:" + client_ip()
        if throttle_blocked(k, 6, 3600):
            flash("Too many reset requests. Please try again in an hour.", "error")
            return render_template("forgot_password.html"), 429
        throttle_hit(k)
        conn  = get_db()
        user  = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        # Always show the same message whether or not the email exists —
        # this prevents attackers from discovering which emails are registered.
        if user:
            token      = secrets.token_urlsafe(32)
            expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
            conn.execute("UPDATE password_resets SET used=1 WHERE user_id=? AND used=0", (user["id"],))  # old links die
            conn.execute(
                "INSERT INTO password_resets (user_id, token, expires_at, used) VALUES (?,?,?,0)",
                (user["id"], hash_token(token), expires_at)          # only a hash is stored
            )
            conn.commit()
            reset_link = f"{APP_BASE_URL}/reset-password/{token}"
            send_reset_email(user["email"], user["name"], reset_link)
            log_activity("requested", "password_reset", f"For {email}")

        conn.close()
        flash("If that email is registered, a reset link has been sent. Check your inbox.", "success")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    conn = get_db()
    reset_row = conn.execute(
        "SELECT * FROM password_resets WHERE token=?", (hash_token(token),)
    ).fetchone()

    valid = False
    if reset_row and not reset_row["used"]:
        try:
            expires = datetime.fromisoformat(reset_row["expires_at"])
            valid = datetime.now() < expires
        except Exception:
            valid = False

    if not valid:
        conn.close()
        flash("This reset link is invalid or has expired. Please request a new one.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_pw  = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        if len(new_pw) < MIN_PASSWORD:
            flash(f"Password must be at least {MIN_PASSWORD} characters.", "error")
        elif new_pw != confirm:
            flash("Passwords do not match.", "error")
        else:
            conn.execute(
                "UPDATE users SET password=? WHERE id=?",
                (generate_password_hash(new_pw), reset_row["user_id"])
            )
            conn.execute(
                "UPDATE password_resets SET used=1 WHERE user_id=?", (reset_row["user_id"],)
            )
            bump_sessions(conn, reset_row["user_id"])
            conn.commit()
            conn.close()
            log_activity("reset", "password", f"user_id={reset_row['user_id']}")
            flash("✅ Password reset successfully. Please sign in.", "success")
            return redirect(url_for("login"))

    conn.close()
    return render_template("reset_password.html", token=token)

# ── Profile — full CRUD ───────────────────────────────────────────
@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    user = current_user()
    uid  = user["id"]
    if request.method == "POST":
        action = request.form.get("action","")
        if is_demo() and action in ("change_email", "change_password", "delete_account", "upload_photo"):
            flash("That option is switched off in the demo account. Register a free account to use it.", "error")
            return redirect(url_for("profile"))
        conn   = get_db()

        if action == "update_info":
            name      = request.form.get("name","").strip()
            phone     = request.form.get("phone","").strip()
            bio       = request.form.get("bio","").strip()
            location  = request.form.get("location","").strip()
            farm_name = request.form.get("farm_name","").strip()
            color     = request.form.get("avatar_color","#2E7D32").strip()
            if not name:
                flash("Name cannot be empty.", "error")
            else:
                conn.execute(
                    "UPDATE users SET name=?,phone=?,bio=?,location=?,farm_name=?,avatar_color=? WHERE id=?",
                    (name, phone, bio, location, farm_name, color, uid)
                )
                conn.commit()
                session["user_name"] = name
                log_activity("updated","profile", f"{name} updated profile info")
                flash("✅ Profile updated successfully.", "success")

        elif action == "change_email":
            new_email = request.form.get("new_email","").strip().lower()
            password  = request.form.get("password_confirm","")
            db_user   = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not check_password_hash(db_user["password"], password):
                flash("Incorrect password — email not changed.", "error")
            elif not new_email or "@" not in new_email:
                flash("Enter a valid email address.", "error")
            elif conn.execute("SELECT id FROM users WHERE email=? AND id!=?", (new_email, uid)).fetchone():
                flash("That email is already in use.", "error")
            else:
                conn.execute("UPDATE users SET email=? WHERE id=?", (new_email, uid))
                conn.commit()
                session["user_email"] = new_email
                flash("✅ Email updated.", "success")

        elif action == "change_password":
            current_pw = request.form.get("current_password","")
            new_pw     = request.form.get("new_password","")
            confirm_pw = request.form.get("confirm_password","")
            db_user    = conn.execute("SELECT password FROM users WHERE id=?", (uid,)).fetchone()
            if not check_password_hash(db_user["password"], current_pw):
                flash("Current password is incorrect.", "error")
            elif len(new_pw) < MIN_PASSWORD:
                flash(f"New password must be at least {MIN_PASSWORD} characters.", "error")
            elif new_pw != confirm_pw:
                flash("Passwords do not match.", "error")
            else:
                conn.execute("UPDATE users SET password=? WHERE id=?",
                             (generate_password_hash(new_pw), uid))
                session["sv"] = bump_sessions(conn, uid)      # other devices are signed out, this one stays
                conn.commit()
                log_activity("updated","profile","Password changed")
                flash("✅ Password changed.", "success")

        elif action == "upload_photo":
            photo = request.files.get("profile_photo")
            if photo and photo.filename:
                allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
                if photo.content_type not in allowed:
                    flash("Only JPG, PNG, GIF or WebP images allowed.", "error")
                else:
                    photo_bytes = photo.read(2 * 1024 * 1024)  # max 2MB
                    real = sniff_image(photo_bytes)
                    if len(photo_bytes) >= 2 * 1024 * 1024:
                        flash("Image too large. Maximum size is 2 MB.", "error")
                    elif not real:
                        flash("That file is not a real JPG, PNG, GIF or WebP image.", "error")
                    else:
                        b64 = base64.b64encode(photo_bytes).decode("utf-8")
                        data_url = f"data:{real};base64,{b64}"
                        conn.execute("UPDATE users SET avatar_photo=? WHERE id=?", (data_url, uid))
                        conn.commit()
                        flash("✅ Profile photo updated.", "success")
            else:
                flash("No photo selected.", "error")

        elif action == "remove_photo":
            conn.execute("UPDATE users SET avatar_photo='' WHERE id=?", (uid,))
            conn.commit()
            flash("✅ Profile photo removed.", "success")

        elif action == "delete_account":
            confirm_pw = request.form.get("delete_password","")
            confirm_txt= request.form.get("delete_confirm","")
            db_user    = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not check_password_hash(db_user["password"], confirm_pw):
                flash("Incorrect password — account not deleted.", "error")
            elif confirm_txt.strip().upper() != "DELETE":
                flash("Type DELETE to confirm account deletion.", "error")
            else:
                # Manually cascade — remove all data linked to this account first
                delete_user_data(conn, uid)
                conn.commit()
                conn.close()
                session.clear()
                flash("Your account has been permanently deleted.", "success")
                return redirect(url_for("register"))

        conn.close()
        return redirect(url_for("profile"))

    # GET — load full profile + stats
    conn = get_db()
    full_user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    stats = {
        "farms":    conn.execute("SELECT COUNT(*) FROM farms WHERE user_id=?",(uid,)).fetchone()[0],
        "notes":    conn.execute("SELECT COUNT(*) FROM crop_notes WHERE user_id=?",(uid,)).fetchone()[0],
        "area":     round(conn.execute("SELECT COALESCE(SUM(area),0) FROM farms WHERE user_id=?",(uid,)).fetchone()[0],1),
        "calcs":    conn.execute("SELECT COUNT(*) FROM fertilizer_history WHERE user_id=?",(uid,)).fetchone()[0],
        "recent_farms": conn.execute(
            "SELECT farm_name,crop_type,area,status FROM farms WHERE user_id=? ORDER BY created_at DESC LIMIT 3",(uid,)
        ).fetchall(),
    }
    conn.close()
    return render_template("profile.html", user=full_user, stats=stats)

# ══════════════════════════════════════════════════════════════════
#  PAGE ROUTES  (all protected)
# ══════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    """Public landing page — always visible, logged-in users see extra CTA."""
    return render_template("index.html")

@app.route("/dashboard")
@login_required
def dashboard():
    uid  = session["user_id"]
    conn = get_db()
    total_farms = conn.execute("SELECT COUNT(*) FROM farms WHERE user_id=?",(uid,)).fetchone()[0]
    total_crops = conn.execute("SELECT COUNT(DISTINCT crop_type) FROM farms WHERE user_id=?",(uid,)).fetchone()[0]
    total_area  = round(conn.execute("SELECT COALESCE(SUM(area),0) FROM farms WHERE user_id=?",(uid,)).fetchone()[0],1)
    total_notes = conn.execute("SELECT COUNT(*) FROM crop_notes WHERE user_id=?",(uid,)).fetchone()[0]
    recent_farms = conn.execute(
        "SELECT * FROM farms WHERE user_id=? ORDER BY created_at DESC LIMIT 5",(uid,)).fetchall()
    recent_notes = conn.execute("""
        SELECT cn.title,cn.note,cn.category,cn.created_at,f.farm_name
        FROM crop_notes cn JOIN farms f ON cn.farm_id=f.id
        WHERE cn.user_id=? ORDER BY cn.created_at DESC LIMIT 5""",(uid,)).fetchall()
    crop_dist = conn.execute(
        "SELECT crop_type,COUNT(*) as cnt FROM farms WHERE user_id=? GROUP BY crop_type",(uid,)).fetchall()
    conn.close()
    return render_template("dashboard.html",
        total_farms=total_farms, total_crops=total_crops,
        total_area=total_area,   total_notes=total_notes,
        recent_farms=recent_farms, recent_notes=recent_notes,
        crop_dist=crop_dist,     weather=get_weather(), push_enabled=PUSH_ENABLED)

@app.route("/farms")
@login_required
def farms():
    uid  = session["user_id"]
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM farms WHERE user_id=? ORDER BY created_at DESC",(uid,)).fetchall()
    conn.close()
    return render_template("farms.html", farms=rows,
        crop_water=CROP_WATER, crop_interval=CROP_INTERVAL)

# ── Farm CRUD ─────────────────────────────────────────────────────
@app.route("/farms/add", methods=["POST"])
@login_required
def add_farm():
    uid=session["user_id"]; d=request.form
    name=clip(d.get("farm_name"),100); crop=clip(d.get("crop_type"),60)
    loc=clip(d.get("location"),120);   pdate=valid_date(d.get("planting_date"))
    status=clip(d.get("status","Active"),20) or "Active"
    errors=[]
    if not name:  errors.append("Farm name is required.")
    if not crop:  errors.append("Crop type is required.")
    if not loc:   errors.append("Location is required.")
    if not pdate: errors.append("Planting date is required (a real date).")
    area_f=to_float(d.get("area","0"),0.0001,1e6)
    if area_f is None:
        errors.append("Area must be a positive number.")
    if errors:
        for e in errors: flash(e,"error")
        return redirect(url_for("farms"))
    conn=get_db()
    conn.execute(
        "INSERT INTO farms (user_id,farm_name,crop_type,location,area,planting_date,status) VALUES (?,?,?,?,?,?,?)",
        (uid,name,crop,loc,area_f,pdate,status))
    conn.commit(); conn.close()
    flash(f"🌱 Farm <strong>{_esc(name)}</strong> added!", "success")
    return redirect(url_for("farms"))

@app.route("/farms/edit/<int:fid>", methods=["POST"])
@login_required
def edit_farm(fid):
    uid=session["user_id"]; conn=get_db()
    if not conn.execute("SELECT id FROM farms WHERE id=? AND user_id=?",(fid,uid)).fetchone():
        conn.close(); flash("Farm not found or access denied.","error")
        return redirect(url_for("farms"))
    d=request.form
    name=clip(d.get("farm_name"),100); crop=clip(d.get("crop_type"),60)
    loc=clip(d.get("location"),120);   pdate=valid_date(d.get("planting_date"))
    status=clip(d.get("status","Active"),20) or "Active"
    area_f=to_float(d.get("area","1"),0.0001,1e6,1.0)
    if not (name and crop and loc and pdate):
        conn.close(); flash("Name, crop, location and a real planting date are required.","error")
        return redirect(url_for("farms"))
    conn.execute(
        "UPDATE farms SET farm_name=?,crop_type=?,location=?,area=?,planting_date=?,status=? WHERE id=? AND user_id=?",
        (name,crop,loc,area_f,pdate,status,fid,uid))
    conn.commit(); conn.close()
    flash(f"✅ Farm <strong>{_esc(name)}</strong> updated.", "success")
    return redirect(url_for("farms"))

@app.route("/farms/delete/<int:fid>", methods=["POST"])
@login_required
def delete_farm(fid):
    uid=session["user_id"]; conn=get_db()
    row=conn.execute("SELECT farm_name FROM farms WHERE id=? AND user_id=?",(fid,uid)).fetchone()
    if not row:
        conn.close(); flash("Farm not found or access denied.","error")
        return redirect(url_for("farms"))
    # Manually cascade — remove everything attached to this farm, then the farm itself
    for t in ("crop_notes","crop_growth","irrigation_log","expense_log","sensor_readings","sensor_devices","forecast_inputs"):
        conn.execute(f"DELETE FROM {t} WHERE farm_id=? AND user_id=?",(fid,uid))
    conn.execute("DELETE FROM farms WHERE id=? AND user_id=?",(fid,uid))
    conn.commit(); conn.close()
    flash(f"🗑️ Farm <strong>{_esc(row['farm_name'])}</strong> deleted.", "success")
    return redirect(url_for("farms"))

# ── Notes CRUD ────────────────────────────────────────────────────
@app.route("/notes")
@login_required
def notes():
    uid=session["user_id"]; conn=get_db()
    farm_list=conn.execute(
        "SELECT id,farm_name FROM farms WHERE user_id=? ORDER BY farm_name",(uid,)).fetchall()
    rows=conn.execute("""
        SELECT cn.id,cn.title,cn.note,cn.category,cn.created_at,f.farm_name,f.id as farm_id
        FROM crop_notes cn JOIN farms f ON cn.farm_id=f.id
        WHERE cn.user_id=? ORDER BY cn.created_at DESC""",(uid,)).fetchall()
    conn.close()
    return render_template("notes.html", notes=rows, farms=farm_list)

@app.route("/notes/add", methods=["POST"])
@login_required
def add_note():
    uid=session["user_id"]
    farm_id=request.form.get("farm_id","").strip()
    title=request.form.get("title","Observation").strip() or "Observation"
    note=request.form.get("note","").strip()
    category=request.form.get("category","General").strip()
    if not farm_id or not note:
        flash("Farm and note text are required.","error")
        return redirect(url_for("notes"))
    conn=get_db()
    if not conn.execute("SELECT id FROM farms WHERE id=? AND user_id=?",(farm_id,uid)).fetchone():
        conn.close(); flash("Invalid farm.","error"); return redirect(url_for("notes"))
    conn.execute("INSERT INTO crop_notes (farm_id,user_id,title,note,category) VALUES (?,?,?,?,?)",
                 (farm_id,uid,title,note,category))
    conn.commit(); conn.close()
    flash("📝 Note saved!", "success")
    return redirect(url_for("notes"))

@app.route("/notes/edit/<int:nid>", methods=["POST"])
@login_required
def edit_note(nid):
    uid=session["user_id"]
    title=request.form.get("title","Observation").strip() or "Observation"
    note=request.form.get("note","").strip()
    category=request.form.get("category","General").strip()
    conn=get_db()
    conn.execute(
        "UPDATE crop_notes SET title=?,note=?,category=? WHERE id=? AND user_id=?",
        (title,note,category,nid,uid))
    conn.commit(); conn.close()
    flash("✅ Note updated.", "success")
    return redirect(url_for("notes"))

@app.route("/notes/delete/<int:nid>", methods=["POST"])
@login_required
def delete_note(nid):
    uid=session["user_id"]; conn=get_db()
    conn.execute("DELETE FROM crop_notes WHERE id=? AND user_id=?",(nid,uid))
    conn.commit(); conn.close()
    flash("🗑️ Note deleted.", "success")
    return redirect(url_for("notes"))

# ── Fertilizer History CRUD ───────────────────────────────────────
@app.route("/fertilizer")
@login_required
def fertilizer():
    uid  = session["user_id"]
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM fertilizer_history WHERE user_id=? ORDER BY created_at DESC",
        (uid,)
    ).fetchall()
    conn.close()
    return render_template("fertilizer.html", history=rows)

@app.route("/fertilizer/save", methods=["POST"])
@login_required
def save_fertilizer():
    uid  = session["user_id"]
    d    = request.get_json(silent=True) or {}
    crop = clip(d.get("crop_type",""), 40)
    area = to_float(d.get("area", 1), 0.0001, 1e6)
    label= clip(d.get("label",""), 100)
    if not crop or area is None:
        return jsonify({"error": "Invalid data"}), 400
    result = calc_fertilizer(crop, area)
    conn = get_db()
    if USE_POSTGRES:
        cur = conn.execute(
            """INSERT INTO fertilizer_history
               (user_id,crop_type,area,n_kg,p_kg,k_kg,total_kg,urea_kg,label)
               VALUES (?,?,?,?,?,?,?,?,?) RETURNING id""",
            (uid, crop, area, result["N"], result["P"], result["K"],
             result["total"], result["urea"], label)
        )
        row = cur.fetchone()
        rid = row["id"] if row else None
    else:
        cur = conn.execute(
            """INSERT INTO fertilizer_history
               (user_id,crop_type,area,n_kg,p_kg,k_kg,total_kg,urea_kg,label)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (uid, crop, area, result["N"], result["P"], result["K"],
             result["total"], result["urea"], label)
        )
        rid = cur.lastrowid
    conn.commit(); conn.close()
    return jsonify({"id": rid, "message": "Saved!", **result})

@app.route("/fertilizer/edit/<int:rid>", methods=["POST"])
@login_required
def edit_fertilizer(rid):
    uid  = session["user_id"]
    d    = request.form
    crop = d.get("crop_type","").strip()
    label= d.get("label","").strip()
    try:   area = float(d.get("area","1"))
    except: area = 1.0
    result = calc_fertilizer(crop, area)
    conn = get_db()
    conn.execute(
        """UPDATE fertilizer_history
           SET crop_type=?,area=?,n_kg=?,p_kg=?,k_kg=?,total_kg=?,urea_kg=?,label=?
           WHERE id=? AND user_id=?""",
        (crop, area, result["N"], result["P"], result["K"],
         result["total"], result["urea"], label, rid, uid)
    )
    conn.commit(); conn.close()
    flash("✅ Calculation updated.", "success")
    return redirect(url_for("fertilizer"))

@app.route("/fertilizer/delete/<int:rid>", methods=["POST"])
@login_required
def delete_fertilizer(rid):
    uid  = session["user_id"]
    conn = get_db()
    conn.execute(
        "DELETE FROM fertilizer_history WHERE id=? AND user_id=?", (rid, uid)
    )
    conn.commit(); conn.close()
    flash("🗑️ Record deleted.", "success")
    return redirect(url_for("fertilizer"))

@app.route("/api/fertilizer/history")
@login_required
def api_fertilizer_history():
    uid  = session["user_id"]
    conn = get_db()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM fertilizer_history WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        (uid,)
    ).fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/api/fertilizer/record/<int:rid>")
@login_required
def api_fertilizer_record(rid):
    uid  = session["user_id"]
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM fertilizer_history WHERE id=? AND user_id=?", (rid, uid)
    ).fetchone()
    conn.close()
    return (jsonify(dict(row)), 200) if row else (jsonify({"error":"not found"}), 404)

@app.route("/weather")
@login_required
def weather():
    city=request.args.get("city","Chittagong").strip() or "Chittagong"
    return render_template("weather.html", weather=get_weather(city), city=city)

@app.route("/analytics")
@login_required
def analytics():
    uid=session["user_id"]; conn=get_db()
    ph = "%s" if USE_POSTGRES else "?"
    farms_data =conn.execute(f"SELECT farm_name,crop_type,area FROM farms WHERE user_id={ph}",(uid,)).fetchall()
    status_data=conn.execute(f"SELECT status,COUNT(*) as cnt FROM farms WHERE user_id={ph} GROUP BY status",(uid,)).fetchall()

    # ── Real irrigation data: monthly water usage (last 7 months) ──
    from datetime import date, timedelta
    today_d = date.today()
    month_labels, water_real = [], []
    for i in range(6, -1, -1):
        # First day of each month going back
        yr  = (today_d.replace(day=1) - timedelta(days=i*30)).year
        mo  = (today_d.replace(day=1) - timedelta(days=i*30)).month
        lbl = date(yr, mo, 1).strftime("%b")
        month_labels.append(lbl)
        mo_str = f"{yr}-{mo:02d}"
        row = conn.execute(
            f"SELECT COALESCE(SUM(water_liters),0) as total FROM irrigation_log "
            f"WHERE user_id={ph} AND date LIKE {ph}",
            (uid, mo_str + "%")
        ).fetchone()
        water_real.append(int(row["total"]))

    # ── Real expense data: monthly spend (last 7 months) ──
    expense_real = []
    for lbl in month_labels:
        # find year/month from label
        from calendar import month_abbr
        abbr_list = list(month_abbr)  # ['', 'Jan', 'Feb', ...]
        mo_num = abbr_list.index(lbl)
        yr_now = today_d.year if mo_num <= today_d.month else today_d.year - 1
        mo_str2 = f"{yr_now}-{mo_num:02d}"
        row = conn.execute(
            f"SELECT COALESCE(SUM(amount),0) as total FROM expense_log "
            f"WHERE user_id={ph} AND type='expense' AND date LIKE {ph}",
            (uid, mo_str2 + "%")
        ).fetchone()
        expense_real.append(int(row["total"]))

    # ── Real income data ──
    income_real = []
    for lbl in month_labels:
        from calendar import month_abbr
        abbr_list = list(month_abbr)
        mo_num = abbr_list.index(lbl)
        yr_now = today_d.year if mo_num <= today_d.month else today_d.year - 1
        mo_str3 = f"{yr_now}-{mo_num:02d}"
        row = conn.execute(
            f"SELECT COALESCE(SUM(amount),0) as total FROM expense_log "
            f"WHERE user_id={ph} AND type='income' AND date LIKE {ph}",
            (uid, mo_str3 + "%")
        ).fetchone()
        income_real.append(int(row["total"]))

    # Total stats
    total_water  = conn.execute(f"SELECT COALESCE(SUM(water_liters),0) as t FROM irrigation_log WHERE user_id={ph}",(uid,)).fetchone()["t"]
    total_income = conn.execute(f"SELECT COALESCE(SUM(amount),0) as t FROM expense_log WHERE user_id={ph} AND type='income'",(uid,)).fetchone()["t"]
    total_expense= conn.execute(f"SELECT COALESCE(SUM(amount),0) as t FROM expense_log WHERE user_id={ph} AND type='expense'",(uid,)).fetchone()["t"]
    last_harvest = conn.execute(
        f"SELECT harvest_date FROM crop_growth WHERE user_id={ph} AND growth_stage='Harvested' ORDER BY harvest_date DESC LIMIT 1",(uid,)
    ).fetchone()

    conn.close()
    labels=[f["farm_name"] for f in farms_data]
    areas =[f["area"]      for f in farms_data]
    crops =[f["crop_type"] for f in farms_data]
    return render_template("analytics.html",
        labels=labels, areas=areas, crops=crops,
        months=month_labels,
        water=water_real,
        expense_monthly=expense_real,
        income_monthly=income_real,
        total_water=int(total_water),
        total_income=int(total_income),
        total_expense=int(total_expense),
        last_harvest=last_harvest["harvest_date"] if last_harvest else "—",
        status_data=status_data)

# ── JSON API (auth-protected) ─────────────────────────────────────
@app.route("/api/farm/<int:fid>")
@login_required
def api_farm(fid):
    uid=session["user_id"]; conn=get_db()
    row=conn.execute("SELECT * FROM farms WHERE id=? AND user_id=?",(fid,uid)).fetchone()
    conn.close()
    return (jsonify(dict(row)),200) if row else (jsonify({"error":"not found"}),404)

@app.route("/api/note/<int:nid>")
@login_required
def api_note(nid):
    uid=session["user_id"]; conn=get_db()
    row=conn.execute("SELECT * FROM crop_notes WHERE id=? AND user_id=?",(nid,uid)).fetchone()
    conn.close()
    return (jsonify(dict(row)),200) if row else (jsonify({"error":"not found"}),404)

@app.route("/api/farms")
@login_required
def api_farms():
    uid=session["user_id"]; conn=get_db()
    rows=[dict(r) for r in conn.execute("SELECT * FROM farms WHERE user_id=?",(uid,)).fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/api/weather")
@login_required
def api_weather():
    k = "wx:%s" % session["user_id"]
    if throttle_blocked(k, 60, 600):
        return jsonify({"error": "Too many requests. Please slow down."}), 429
    throttle_hit(k)
    return jsonify(get_weather(request.args.get("city","Chittagong")))

@app.route("/api/fertilizer", methods=["POST"])
@login_required
def api_fertilizer():
    d = request.get_json(silent=True) or {}
    area = to_float(d.get("area", 1), 0.0001, 1e6)
    if area is None:
        return jsonify({"error": "Area must be a positive number."}), 400
    return jsonify(calc_fertilizer(clip(d.get("crop_type", "rice"), 40) or "rice", area))

# ── Disease Detection ─────────────────────────────────────────────
DISEASE_DB = {
    "rice": [
        {"name":"Rice Blast","symptoms":["brown spots","gray center","diamond shaped lesion","white lesion","blast"],"severity":"High","treatment":"Apply Tricyclazole or Carbendazim fungicide. Remove infected leaves. Ensure proper spacing.","prevention":"Use resistant varieties. Avoid excess nitrogen. Maintain proper water level.","emoji":"🍚"},
        {"name":"Brown Spot","symptoms":["brown circular spots","yellow halo","dark brown","circular brown","brown spot"],"severity":"Medium","treatment":"Apply Mancozeb or Iprobenfos. Improve soil nutrition with potassium.","prevention":"Use certified seeds. Balanced fertilization. Proper water management.","emoji":"🟤"},
        {"name":"Bacterial Leaf Blight","symptoms":["water soaked","yellow stripe","wilting","yellow edge","leaf edge yellow","blight"],"severity":"High","treatment":"No effective chemical. Remove infected plants. Use copper-based bactericide.","prevention":"Use resistant varieties. Avoid flood irrigation. Balanced nitrogen.","emoji":"⚡"},
        {"name":"Sheath Blight","symptoms":["oval lesion","water soaked sheath","white center sheath","gray lesion sheath","sheath"],"severity":"Medium","treatment":"Apply Hexaconazole or Validamycin. Reduce plant density.","prevention":"Avoid dense planting. Reduce nitrogen. Drain fields periodically.","emoji":"🌾"},
    ],
    "wheat": [
        {"name":"Wheat Rust","symptoms":["rust colored pustules","orange powder","rust","pustules","orange spots"],"severity":"High","treatment":"Apply Propiconazole or Tebuconazole fungicide immediately.","prevention":"Use rust-resistant varieties. Early planting. Remove volunteer plants.","emoji":"🟠"},
        {"name":"Powdery Mildew","symptoms":["white powder","powdery coating","white fungus","powdery","white coat"],"severity":"Medium","treatment":"Apply sulfur-based fungicide or Triadimefon.","prevention":"Avoid dense planting. Reduce humidity. Use resistant varieties.","emoji":"⬜"},
        {"name":"Loose Smut","symptoms":["black powder","smut","black dust","black spores","dark powder"],"severity":"High","treatment":"Use carboxin or thiram seed treatment.","prevention":"Plant certified disease-free seeds. Hot water seed treatment.","emoji":"⬛"},
    ],
    "tomato": [
        {"name":"Early Blight","symptoms":["dark spots","concentric rings","target spot","brown lesion","early blight"],"severity":"Medium","treatment":"Apply Chlorothalonil or Mancozeb. Remove infected lower leaves.","prevention":"Crop rotation. Mulching. Avoid overhead irrigation.","emoji":"🍅"},
        {"name":"Late Blight","symptoms":["water soaked","dark brown","white mold underside","late blight","greasy spots"],"severity":"High","treatment":"Apply Metalaxyl or Cymoxanil immediately. Destroy infected plants.","prevention":"Avoid overhead watering. Good air circulation. Use resistant varieties.","emoji":"💧"},
        {"name":"Leaf Curl","symptoms":["curling leaves","leaf curl","upward curl","twisted leaves","curled"],"severity":"Medium","treatment":"Control whitefly vectors with imidacloprid. Remove infected plants.","prevention":"Use virus-free seedlings. Control insect vectors. Reflective mulch.","emoji":"🌀"},
        {"name":"Fusarium Wilt","symptoms":["wilting","yellowing","brown stem","vascular discoloration","wilt"],"severity":"High","treatment":"No chemical cure. Remove infected plants. Soil solarization.","prevention":"Use resistant varieties. Crop rotation. Sterilize tools.","emoji":"🥀"},
    ],
    "potato": [
        {"name":"Late Blight","symptoms":["water soaked","dark lesion","white mold","brown patch","late blight"],"severity":"High","treatment":"Apply Metalaxyl or Mancozeb. Destroy infected tubers.","prevention":"Use certified seed potato. Avoid overhead irrigation. Good drainage.","emoji":"🥔"},
        {"name":"Early Blight","symptoms":["dark brown spots","concentric rings","yellow halo","angular spots","early blight"],"severity":"Medium","treatment":"Apply Chlorothalonil or Iprodione fungicide.","prevention":"Crop rotation. Remove plant debris. Balanced fertilization.","emoji":"🟫"},
        {"name":"Blackleg","symptoms":["black stem base","soft rot","wilting","black leg","stem rot"],"severity":"High","treatment":"No effective treatment. Remove and destroy infected plants.","prevention":"Use certified seed. Good drainage. Avoid injuring stems.","emoji":"🖤"},
    ],
    "maize": [
        {"name":"Northern Corn Leaf Blight","symptoms":["long gray lesion","cigar shaped","long lesion","gray streak","leaf blight"],"severity":"Medium","treatment":"Apply Propiconazole. Remove infected debris after harvest.","prevention":"Use resistant hybrids. Crop rotation. Proper spacing.","emoji":"🌽"},
        {"name":"Common Rust","symptoms":["rust","orange pustules","brick red","rust colored","powdery orange"],"severity":"Medium","treatment":"Apply Mancozeb or Trifloxystrobin fungicide.","prevention":"Use resistant varieties. Early planting. Proper plant nutrition.","emoji":"🟤"},
        {"name":"Stalk Rot","symptoms":["stalk rot","soft stalk","lodging","stalk discoloration","stem rot"],"severity":"High","treatment":"No effective chemical. Harvest early to prevent loss.","prevention":"Balanced fertilization. Avoid stress. Control insects.","emoji":"🌿"},
    ],
    "general": [
        {"name":"Nutrient Deficiency","symptoms":["yellowing","pale leaves","yellow","chlorosis","light green","pale"],"severity":"Low","treatment":"Apply balanced NPK fertilizer. Soil test to identify specific deficiency.","prevention":"Regular soil testing. Balanced fertilization. Proper pH management.","emoji":"🌱"},
        {"name":"Overwatering / Root Rot","symptoms":["wilting","yellow","soggy soil","root rot","overwater","drooping"],"severity":"Medium","treatment":"Reduce watering. Improve drainage. Apply fungicide to roots.","prevention":"Well-draining soil. Avoid waterlogging. Monitor soil moisture.","emoji":"💧"},
        {"name":"Fungal Infection","symptoms":["mold","fungus","white growth","black growth","fuzzy","spores"],"severity":"Medium","treatment":"Apply broad-spectrum fungicide (Mancozeb or Copper oxychloride).","prevention":"Good air circulation. Avoid overhead irrigation. Remove debris.","emoji":"🍄"},
    ],
}

def detect_disease(crop_type, symptoms_text, additional_info=""):
    text = (symptoms_text + " " + additional_info).lower()
    crop = crop_type.lower()
    candidates = DISEASE_DB.get(crop, []) + DISEASE_DB["general"]
    matches = []
    for disease in candidates:
        score = 0
        matched_symptoms = []
        for symptom in disease["symptoms"]:
            if any(word in text for word in symptom.split()):
                score += 1
                matched_symptoms.append(symptom)
        if score > 0:
            matches.append({**disease, "score": score, "matched": matched_symptoms})
    matches.sort(key=lambda x: x["score"], reverse=True)
    if not matches:
        return {"detected": False, "message": "No specific disease matched. Try describing symptoms in more detail."}
    top = matches[0]
    confidence = min(int((top["score"] / max(len(top["symptoms"]), 1)) * 100), 95)
    return {
        "detected": True,
        "disease": top["name"],
        "severity": top["severity"],
        "confidence": confidence,
        "emoji": top["emoji"],
        "treatment": top["treatment"],
        "prevention": top["prevention"],
        "matched_symptoms": top["matched"],
        "other_possible": [m["name"] for m in matches[1:3]] if len(matches) > 1 else []
    }

@app.route("/disease", methods=["GET"])
@login_required
def disease_page():
    farms = []
    try:
        conn = get_db(); cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(f"SELECT id, farm_name, crop_type FROM farms WHERE user_id={ph} ORDER BY farm_name", (session["user_id"],))
        farms = cur.fetchall(); conn.close()
    except Exception:
        pass
    return render_template("disease.html", farms=farms)

@app.route("/api/disease-detect", methods=["POST"])
@login_required
def api_disease_detect():
    if is_demo():
        return demo_block_json()
    d = request.get_json(force=True) or {}
    crop_type = d.get("crop_type", "general")
    symptoms = d.get("symptoms", "")
    additional = d.get("additional_info", "")
    if not symptoms.strip():
        return jsonify({"error": "Please describe the symptoms"}), 400
    result = detect_disease(crop_type, symptoms, additional)
    return jsonify(result)

# ══════════════════════════════════════════════════════════════════
#  CROP GROWTH TRACKER
# ══════════════════════════════════════════════════════════════════
@app.route("/growth")
@login_required
def growth_page():
    uid = current_user()["id"]
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    farms = conn.execute(
        f"SELECT id, farm_name, crop_type, planting_date FROM farms WHERE user_id={ph} ORDER BY farm_name", (uid,)
    ).fetchall()
    growth_records = conn.execute(
        f"""SELECT g.*, f.farm_name, f.crop_type FROM crop_growth g
            JOIN farms f ON g.farm_id=f.id
            WHERE g.user_id={ph} ORDER BY g.created_at DESC""", (uid,)
    ).fetchall()
    conn.close()
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("growth.html", farms=farms, records=growth_records, today=today)

@app.route("/growth/add", methods=["POST"])
@login_required
def add_growth():
    uid = current_user()["id"]
    planting_date= valid_date(request.form.get("planting_date"))
    expected_days= to_int(request.form.get("expected_days", 90), 1, 1500, 90)
    growth_stage = clip(request.form.get("growth_stage","Seedling"), 40)
    notes        = clip(request.form.get("notes",""), 1000)
    conn = get_db()
    farm_id = owned_farm_id(conn, uid, request.form.get("farm_id"))
    if not farm_id or not planting_date:
        conn.close()
        flash("Choose one of your farms and a valid planting date.", "error")
        return redirect(url_for("growth_page"))
    ph = "%s" if USE_POSTGRES else "?"
    # Calculate harvest date
    from datetime import date, timedelta
    pd = datetime.strptime(planting_date, "%Y-%m-%d")
    harvest_date = (pd + timedelta(days=expected_days)).strftime("%Y-%m-%d")
    conn.execute(
        f"INSERT INTO crop_growth (farm_id,user_id,planting_date,expected_days,harvest_date,growth_stage,notes) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
        (farm_id, uid, planting_date, expected_days, harvest_date, growth_stage, notes)
    )
    conn.commit()
    conn.close()
    flash("✅ Growth record added.", "success")
    return redirect(url_for("growth_page"))

@app.route("/growth/update/<int:gid>", methods=["POST"])
@login_required
def update_growth(gid):
    uid = current_user()["id"]
    growth_stage = request.form.get("growth_stage","")
    notes        = request.form.get("notes","")
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    conn.execute(
        f"UPDATE crop_growth SET growth_stage={ph}, notes={ph} WHERE id={ph} AND user_id={ph}",
        (growth_stage, notes, gid, uid)
    )
    conn.commit()
    conn.close()
    flash("✅ Growth stage updated.", "success")
    return redirect(url_for("growth_page"))

@app.route("/growth/delete/<int:gid>", methods=["POST"])
@login_required
def delete_growth(gid):
    uid = current_user()["id"]
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    conn.execute(f"DELETE FROM crop_growth WHERE id={ph} AND user_id={ph}", (gid, uid))
    conn.commit()
    conn.close()
    flash("Growth record deleted.", "success")
    return redirect(url_for("growth_page"))


# ══════════════════════════════════════════════════════════════════
#  IRRIGATION LOG
# ══════════════════════════════════════════════════════════════════
@app.route("/irrigation")
@login_required
def irrigation_page():
    uid = current_user()["id"]
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    farms = conn.execute(
        f"SELECT id, farm_name, crop_type FROM farms WHERE user_id={ph} ORDER BY farm_name", (uid,)
    ).fetchall()
    logs = conn.execute(
        f"""SELECT i.*, f.farm_name FROM irrigation_log i
            JOIN farms f ON i.farm_id=f.id
            WHERE i.user_id={ph} ORDER BY i.date DESC LIMIT 50""", (uid,)
    ).fetchall()
    # Weather suggestion
    weather_tip = ""
    try:
        loc = "Chittagong"
        resp = __import__("requests").get(
            f"https://api.openweathermap.org/data/2.5/forecast?q={loc}&appid={OPENWEATHER_KEY}&units=metric&cnt=8",
            timeout=5
        ).json()
        rain_soon = any(
            "rain" in item.get("weather",[{}])[0].get("main","").lower()
            for item in resp.get("list",[])[:4]
        )
        weather_tip = "🌧️ Rain expected in the next 24 hours — irrigation may not be needed." if rain_soon else "☀️ No rain expected — consider irrigating your crops."
    except Exception:
        pass
    conn.close()
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("irrigation.html", farms=farms, logs=logs, weather_tip=weather_tip, today=today)

@app.route("/irrigation/add", methods=["POST"])
@login_required
def add_irrigation():
    uid = current_user()["id"]
    conn = get_db()
    ok, msg = save_irrigation_entry(conn, uid, request.form)
    conn.close()
    if request.headers.get("X-GF-Fetch"):
        return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("irrigation_page"))

@app.route("/irrigation/delete/<int:iid>", methods=["POST"])
@login_required
def delete_irrigation(iid):
    uid = current_user()["id"]
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    conn.execute(f"DELETE FROM irrigation_log WHERE id={ph} AND user_id={ph}", (iid, uid))
    conn.commit()
    conn.close()
    flash("Log deleted.", "success")
    return redirect(url_for("irrigation_page"))


# ══════════════════════════════════════════════════════════════════
#  FARM EXPENSE TRACKER
# ══════════════════════════════════════════════════════════════════
def finance_summary(uid):
    """Profit & loss per farm, expense by category and the last 6 months (all from the user's own entries)."""
    conn = get_db()
    farms = conn.execute("SELECT id, farm_name, crop_type, area FROM farms WHERE user_id=? ORDER BY farm_name", (uid,)).fetchall()
    rows = conn.execute("SELECT farm_id, type, category, amount, date FROM expense_log WHERE user_id=?", (uid,)).fetchall()
    conn.close()
    per = {f["id"]: {"farm": f["farm_name"], "crop": f["crop_type"], "area": f["area"] or 0, "income": 0.0, "expense": 0.0} for f in farms}
    cats, months = {}, {}
    for r in rows:
        amt = float(r["amount"] or 0)
        p = per.get(r["farm_id"])
        if p is not None:
            p["income" if r["type"] == "income" else "expense"] += amt
        if r["type"] != "income":
            cats[r["category"] or "Other"] = cats.get(r["category"] or "Other", 0) + amt
        m = (r["date"] or "")[:7]
        if m:
            b = months.setdefault(m, {"income": 0.0, "expense": 0.0})
            b["income" if r["type"] == "income" else "expense"] += amt
    farm_rows = []
    for p in per.values():
        if p["income"] or p["expense"]:
            p["profit"] = p["income"] - p["expense"]
            p["per_acre"] = round(p["profit"] / p["area"]) if p["area"] else None
            farm_rows.append(p)
    farm_rows.sort(key=lambda x: x["profit"], reverse=True)
    keys = sorted(months)[-6:]
    monthly = [{"m": k, "label": datetime.strptime(k, "%Y-%m").strftime("%b %y"),
                "income": months[k]["income"], "expense": months[k]["expense"],
                "profit": months[k]["income"] - months[k]["expense"]} for k in keys]
    tot_exp = sum(cats.values())
    cat_rows = [{"cat": c, "amount": a, "pct": round(a / tot_exp * 100) if tot_exp else 0}
                for c, a in sorted(cats.items(), key=lambda x: -x[1])]
    return {"farms": farm_rows, "cats": cat_rows, "monthly": monthly,
            "max_month": max([max(m["income"], m["expense"]) for m in monthly] or [1]) or 1}

@app.route("/expenses")
@login_required
def expenses_page():
    uid = current_user()["id"]
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    farms = conn.execute(
        f"SELECT id, farm_name, crop_type FROM farms WHERE user_id={ph} ORDER BY farm_name", (uid,)
    ).fetchall()
    farm_id_filter = request.args.get("farm_id", "")
    if farm_id_filter:
        logs = conn.execute(
            f"""SELECT e.*, f.farm_name FROM expense_log e JOIN farms f ON e.farm_id=f.id
                WHERE e.user_id={ph} AND e.farm_id={ph} ORDER BY e.date DESC""", (uid, farm_id_filter)
        ).fetchall()
    else:
        logs = conn.execute(
            f"""SELECT e.*, f.farm_name FROM expense_log e JOIN farms f ON e.farm_id=f.id
                WHERE e.user_id={ph} ORDER BY e.date DESC LIMIT 100""", (uid,)
        ).fetchall()
    # Summary
    total_income  = sum(r["amount"] for r in logs if r["type"] == "income")
    total_expense = sum(r["amount"] for r in logs if r["type"] == "expense")
    profit = total_income - total_expense
    conn.close()
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("expenses.html", farms=farms, logs=logs,
                           total_income=total_income, total_expense=total_expense,
                           profit=profit, today=today, farm_id_filter=farm_id_filter,
                           fin=finance_summary(uid))

# ── entries that may also arrive later from the offline queue ───────
import re as _re
def _claim_cid(conn, uid, cid):
    """Each offline entry has a random id so a retry can never be saved twice.
    True = new, False = already saved earlier (not an error), None = malformed id."""
    if not cid:
        return True
    if not _re.fullmatch(r"[A-Za-z0-9_-]{8,64}", str(cid)):
        return None
    ph = "%s" if USE_POSTGRES else "?"
    if conn.execute(f"SELECT 1 FROM offline_sync WHERE user_id={ph} AND cid={ph}", (uid, cid)).fetchone():
        return False
    try:
        conn.execute(f"INSERT INTO offline_sync (user_id,cid) VALUES ({ph},{ph})", (uid, cid))
    except Exception:                                   # two requests raced: the other one won
        try: conn.rollback()
        except Exception: pass
        return False
    return True

def save_expense_entry(conn, uid, f):
    etype    = "income" if f.get("type") == "income" else "expense"
    category = clip(f.get("category", "Other"), 40)
    amount   = to_float(f.get("amount", 0) or 0, 0.0001, 1e10, None)
    desc     = clip(f.get("description", ""), 300)
    date     = valid_date(f.get("date"))
    farm_id  = owned_farm_id(conn, uid, f.get("farm_id"))
    if not farm_id or not date or amount is None:
        return False, "Choose one of your farms, a valid date and a positive amount."
    claim = _claim_cid(conn, uid, f.get("cid"))
    if claim is None:
        return False, "Invalid entry id."
    if claim is False:
        return True, "✅ Entry already saved."
    ph = "%s" if USE_POSTGRES else "?"
    conn.execute(
        f"INSERT INTO expense_log (farm_id,user_id,type,category,amount,description,date) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
        (farm_id, uid, etype, category, amount, desc, date))
    conn.commit()
    return True, "✅ Entry saved."

def save_irrigation_entry(conn, uid, f):
    date         = valid_date(f.get("date"))
    water_liters = to_float(f.get("water_liters", 0) or 0, 0, 1e9, None)
    method       = clip(f.get("method", "Manual"), 40)
    duration_min = to_int(f.get("duration_min", 0) or 0, 0, 100000, None)
    notes        = clip(f.get("notes", ""), 1000)
    farm_id      = owned_farm_id(conn, uid, f.get("farm_id"))
    if not farm_id or not date or water_liters is None or duration_min is None:
        return False, "Choose one of your farms, a valid date and valid numbers."
    claim = _claim_cid(conn, uid, f.get("cid"))
    if claim is None:
        return False, "Invalid entry id."
    if claim is False:
        return True, "✅ Irrigation already logged."
    ph = "%s" if USE_POSTGRES else "?"
    conn.execute(
        f"INSERT INTO irrigation_log (farm_id,user_id,date,water_liters,method,duration_min,notes) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
        (farm_id, uid, date, water_liters, method, duration_min, notes))
    conn.commit()
    return True, "✅ Irrigation logged."

@app.route("/api/offline/sync", methods=["POST"])
@login_required
def api_offline_sync():
    """Receives entries that were written while the phone had no network."""
    uid = session["user_id"]
    k = "sync:%s" % uid
    if throttle_blocked(k, 40, 600):
        return jsonify({"error": "Too many sync requests."}), 429
    throttle_hit(k)
    body = request.get_json(silent=True) or {}
    entries = body.get("entries")
    if not isinstance(entries, list) or len(entries) > 50:
        return jsonify({"error": "Send between 1 and 50 entries."}), 400
    done, rejected = [], []
    conn = get_db()
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("f"), dict):
            continue
        cid = str(e.get("cid") or "")
        f = {kk: (vv if isinstance(vv, (str, int, float)) else "") for kk, vv in e["f"].items()}
        f["cid"] = cid
        if not cid:
            rejected.append({"cid": cid, "reason": "missing id"}); continue
        try:
            fn = save_expense_entry if e.get("kind") == "expense" else save_irrigation_entry if e.get("kind") == "irrigation" else None
            if fn is None:
                rejected.append({"cid": cid, "reason": "unknown kind"}); continue
            ok, msg = fn(conn, uid, f)
        except Exception as ex:
            print("[offline-sync]", type(ex).__name__)
            try: conn.rollback()
            except Exception: pass
            ok, msg = False, "could not save"
        (done if ok else rejected).append(cid if ok else {"cid": cid, "reason": msg})
    conn.close()
    return jsonify({"done": done, "rejected": rejected})

@app.route("/expenses/add", methods=["POST"])
@login_required
def add_expense():
    uid = current_user()["id"]
    conn = get_db()
    ok, msg = save_expense_entry(conn, uid, request.form)
    conn.close()
    if request.headers.get("X-GF-Fetch"):
        return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("expenses_page"))

@app.route("/expenses/delete/<int:eid>", methods=["POST"])
@login_required
def delete_expense(eid):
    uid = current_user()["id"]
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    conn.execute(f"DELETE FROM expense_log WHERE id={ph} AND user_id={ph}", (eid, uid))
    conn.commit()
    conn.close()
    flash("Entry deleted.", "success")
    return redirect(url_for("expenses_page"))


# ══════════════════════════════════════════════════════════════════
#  MARKET PRICE TRACKER  (real scrape → cache → fallback)
# ══════════════════════════════════════════════════════════════════

# Fallback / baseline prices (DAM-verified as of Nov 2026, Dhaka wholesale)
_MARKET_FALLBACK = {
    "Rice (Boro)":    {"price": 32,  "unit": "kg", "trend": "up",    "tip": "Good time to sell — Boro prices rising after harvest season."},
    "Rice (Aman)":    {"price": 28,  "unit": "kg", "trend": "stable","tip": "Prices stable. Store 2–3 weeks for better return."},
    "Wheat":          {"price": 38,  "unit": "kg", "trend": "up",    "tip": "Wheat prices rising due to import costs. Sell now."},
    "Potato":         {"price": 22,  "unit": "kg", "trend": "down",  "tip": "Prices dropping. Consider cold storage if possible."},
    "Tomato":         {"price": 45,  "unit": "kg", "trend": "up",    "tip": "High demand in Dhaka markets. Good time to sell."},
    "Brinjal":        {"price": 30,  "unit": "kg", "trend": "stable","tip": "Stable demand. Local market preferred."},
    "Onion":          {"price": 55,  "unit": "kg", "trend": "up",    "tip": "Onion prices surging. Excellent selling opportunity."},
    "Garlic":         {"price": 120, "unit": "kg", "trend": "up",    "tip": "High value crop. Dhaka wholesale recommended."},
    "Mustard":        {"price": 65,  "unit": "kg", "trend": "stable","tip": "Steady demand from oil mills."},
    "Jute":           {"price": 42,  "unit": "kg", "trend": "up",    "tip": "Export demand increasing. Consider bulk selling."},
    "Maize":          {"price": 25,  "unit": "kg", "trend": "stable","tip": "Poultry feed demand is consistent. Fair price now."},
    "Lentil (Masur)": {"price": 95,  "unit": "kg", "trend": "up",    "tip": "High price due to low local production. Good return."},
    "Chilli (dry)":   {"price": 180, "unit": "kg", "trend": "up",    "tip": "Best selling crop this season. Act fast."},
    "Ginger":         {"price": 90,  "unit": "kg", "trend": "stable","tip": "Consistent spice market demand."},
    "Turmeric":       {"price": 75,  "unit": "kg", "trend": "stable","tip": "Pharma and food industry demand is steady."},
}

# In-memory cache: {"prices": {...}, "fetched_at": datetime, "source": "live"/"fallback"}
_price_cache = {"prices": None, "fetched_at": None, "source": "fallback"}
_CACHE_TTL_HOURS = 6  # re-fetch every 6 hours

def _fetch_dam_prices():
    """Live prices are intentionally NOT fetched.

    Checked 2026-11-15: dam.gov.bd publishes its daily retail prices only as per-division downloadable files
    (a table of dates with 'Download' links), not as an HTML table or a public JSON feed, so there is nothing
    reliable to scrape. The market page therefore shows labelled reference values plus the user's own recorded
    prices. (An earlier version retried the site without certificate verification; that was removed.)"""
    return None


def get_market_prices():
    """Return prices from cache or re-fetch, falling back to hardcoded values."""
    global _price_cache
    now = datetime.now()
    cache_valid = (
        _price_cache["prices"] is not None and
        _price_cache["fetched_at"] is not None and
        (now - _price_cache["fetched_at"]) < timedelta(hours=_CACHE_TTL_HOURS)
    )
    if cache_valid:
        return _price_cache["prices"], _price_cache["source"], _price_cache["fetched_at"]

    # Try live scrape
    live = _fetch_dam_prices()
    if live:
        # Merge: live prices override fallback; fallback fills missing crops
        merged = dict(_MARKET_FALLBACK)
        merged.update(live)
        _price_cache = {"prices": merged, "fetched_at": now, "source": "live"}
        return merged, "live", now
    else:
        # Use fallback
        _price_cache = {"prices": _MARKET_FALLBACK, "fetched_at": now, "source": "fallback"}
        return _MARKET_FALLBACK, "fallback", now


def _record_prices(prices, source):
    """Keep a daily price history - only REAL (live) quotes are stored, never the sample values."""
    if source != "live":
        return
    day = datetime.now().strftime("%Y-%m-%d")
    try:
        conn = get_db()
        for crop, d in prices.items():
            if conn.execute("SELECT id FROM price_history WHERE crop=? AND day=? AND source='live'", (crop, day)).fetchone():
                conn.execute("UPDATE price_history SET price=? WHERE crop=? AND day=? AND source='live'", (float(d["price"]), crop, day))
            else:
                conn.execute("INSERT INTO price_history (crop,price,unit,day,source) VALUES (?,?,?,?,'live')",
                             (crop, float(d["price"]), d.get("unit", "kg"), day))
        conn.commit(); conn.close()
    except Exception as e:
        print("[market] could not record prices:", repr(e))

def _calendar_for(crop):
    n = crop.lower()
    for k, v in CROP_CALENDAR.items():
        base = k.lower().split(" (")[0]
        if base in n or n.split(" (")[0] in k.lower():
            return v
    return None

_MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

def market_view(prices, source, lang="en", uid=None):
    """Trend/advice from REAL data only: stored live quotes + the prices this user recorded themselves."""
    bn = lang == "bn"
    live, mine = {}, {}
    try:
        conn = get_db()
        since = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        for r in conn.execute("SELECT crop, price, day, source, user_id FROM price_history WHERE day>=? ORDER BY day", (since,)).fetchall():
            if (r["source"] or "live") == "manual":
                if uid is not None and r["user_id"] == uid:
                    mine.setdefault(r["crop"], []).append((r["day"], float(r["price"])))
            else:
                live.setdefault(r["crop"], []).append((r["day"], float(r["price"])))
        conn.close()
    except Exception:
        pass
    mon = datetime.now().strftime("%b")
    out = []
    for crop, d in prices.items():
        pts = sorted(live.get(crop, []) + mine.get(crop, []))
        trend, tip, kind = "unknown", "", "seasonal"
        if len(pts) >= 3:
            vals = [v for _, v in pts]
            cur, prev = vals[-1], vals[:-1]
            avg = sum(prev) / len(prev)
            chg = (cur - avg) / avg * 100 if avg else 0
            trend = "up" if chg >= 3 else "down" if chg <= -3 else "stable"
            hi, lo = max(vals), min(vals)
            n = len(pts)
            if hi > lo and cur >= lo + 0.75 * (hi - lo):
                tip = (f"দাম রেকর্ড করা {n}টির মধ্যে সর্বোচ্চের কাছাকাছি — বিক্রির ভালো সময়।" if bn else
                       f"Price is near the top of your {n} recorded prices — a good moment to sell if your crop is ready.")
            elif hi > lo and cur <= lo + 0.25 * (hi - lo):
                tip = (f"দাম রেকর্ড করা {n}টির মধ্যে সর্বনিম্নের কাছাকাছি — সম্ভব হলে সংরক্ষণ করে অপেক্ষা করুন।" if bn else
                       f"Price is near the bottom of your {n} recorded prices — hold and store if you can.")
            else:
                tip = (f"দাম রেকর্ড করা {n}টির মাঝামাঝি।" if bn else f"Price is mid-range across {n} recorded prices.")
            kind = "history"
        else:
            cal = _calendar_for(crop)
            if cal and mon in cal["harvest"]:
                tip = ("এখন ফসল তোলার মৌসুম — সরবরাহ বেশি থাকায় দাম সাধারণত কম থাকে। পারলে সংরক্ষণ করুন।" if bn else
                       "Harvest season now — supply is high, so prices are usually lowest. Store if you can.")
            elif cal:
                i = _MON.index(mon)
                after = any(_MON[(i - k) % 12] in cal["harvest"] for k in (1, 2, 3))
                tip = ("ফসল তোলার কয়েক মাস পর — দাম সাধারণত বাড়তে থাকে।" if bn and after else
                       "বিক্রির জন্য নির্দিষ্ট মৌসুমি পরামর্শ নেই।" if bn else
                       "A few months after harvest — prices usually recover." if after else
                       "No seasonal pattern to flag right now.")
            else:
                tip = "এই ফসলের জন্য মৌসুমি তথ্য নেই।" if bn else "No seasonal data for this crop."
        last_mine = mine[crop][-1] if mine.get(crop) else None
        out.append({"crop": crop, "price": d["price"], "unit": d["unit"], "trend": trend, "tip": tip,
                    "kind": kind, "spark": [v for _, v in pts][-30:], "samples": len(pts),
                    "mine": {"price": last_mine[1], "day": last_mine[0]} if last_mine else None})
    return out

@app.route("/market/record", methods=["POST"])
@login_required
def market_record():
    """The user records a price they actually saw at their local market (BDT per unit)."""
    crop = (request.form.get("crop") or "").strip()
    prices, _, _ = get_market_prices()
    if crop not in prices:
        flash("Unknown crop.", "error"); return redirect(url_for("market_page"))
    try:
        price = float(request.form.get("price", ""))
    except ValueError:
        price = -1
    if not (0 < price < 100000):
        flash("Enter a valid price in ৳.", "error"); return redirect(url_for("market_page"))
    day = datetime.now().strftime("%Y-%m-%d")
    uid = session["user_id"]
    conn = get_db()
    row = conn.execute("SELECT id FROM price_history WHERE crop=? AND day=? AND source='manual' AND user_id=?", (crop, day, uid)).fetchone()
    if row:
        conn.execute("UPDATE price_history SET price=? WHERE id=?", (price, row["id"]))
    else:
        conn.execute("INSERT INTO price_history (crop,price,unit,day,source,user_id) VALUES (?,?,?,?,'manual',?)",
                     (crop, price, prices[crop].get("unit", "kg"), day, uid))
    conn.commit(); conn.close()
    flash(f"Saved: {crop} ৳{price:g} today.", "success")
    return redirect(url_for("market_page"))

@app.route("/market")
@login_required
def market_page():
    prices, source, fetched_at = get_market_prices()
    _record_prices(prices, source)
    updated_str = fetched_at.strftime("%d %b %Y, %I:%M %p") if fetched_at else datetime.now().strftime("%d %b %Y")
    return render_template("market.html", prices=prices,
                           view=market_view(prices, source, session.get("lang", "en"), session["user_id"]),
                           updated=updated_str,
                           price_source=source)


# ══════════════════════════════════════════════════════════════════
#  CROP CALENDAR
# ══════════════════════════════════════════════════════════════════
CROP_CALENDAR = {
    "Rice (Boro)":    {"sow":["Nov","Dec","Jan"],  "harvest":["Apr","May"],      "region":"All Bangladesh", "days":130, "emoji":"🌾"},
    "Rice (Aman)":    {"sow":["Jun","Jul","Aug"],  "harvest":["Nov","Dec"],      "region":"All Bangladesh", "days":140, "emoji":"🌾"},
    "Rice (Aus)":     {"sow":["Mar","Apr"],         "harvest":["Jul","Aug"],      "region":"All Bangladesh", "days":110, "emoji":"🌾"},
    "Wheat":          {"sow":["Nov","Dec"],          "harvest":["Mar","Apr"],      "region":"North Bangladesh","days":110, "emoji":"🌿"},
    "Potato":         {"sow":["Oct","Nov"],          "harvest":["Jan","Feb"],      "region":"North & Central", "days":90,  "emoji":"🥔"},
    "Tomato":         {"sow":["Sep","Oct"],          "harvest":["Dec","Jan","Feb"],"region":"All Bangladesh", "days":90,  "emoji":"🍅"},
    "Onion":          {"sow":["Oct","Nov"],          "harvest":["Feb","Mar"],      "region":"South Bangladesh","days":100, "emoji":"🧅"},
    "Mustard":        {"sow":["Oct","Nov"],          "harvest":["Feb","Mar"],      "region":"North Bangladesh","days":100, "emoji":"🌼"},
    "Jute":           {"sow":["Mar","Apr","May"],    "harvest":["Jul","Aug"],      "region":"All Bangladesh", "days":120, "emoji":"🌿"},
    "Maize":          {"sow":["Oct","Nov"],          "harvest":["Feb","Mar"],      "region":"North Bangladesh","days":120, "emoji":"🌽"},
    "Brinjal":        {"sow":["Aug","Sep"],          "harvest":["Nov","Dec","Jan"],"region":"All Bangladesh", "days":80,  "emoji":"🍆"},
    "Chilli":         {"sow":["Sep","Oct"],          "harvest":["Jan","Feb","Mar"],"region":"South Bangladesh","days":120, "emoji":"🌶️"},
    "Garlic":         {"sow":["Oct","Nov"],          "harvest":["Feb","Mar"],      "region":"North Bangladesh","days":100, "emoji":"🧄"},
    "Ginger":         {"sow":["Mar","Apr"],          "harvest":["Nov","Dec"],      "region":"Hilly regions",   "days":240, "emoji":"🫚"},
    "Lentil":         {"sow":["Oct","Nov"],          "harvest":["Feb","Mar"],      "region":"North Bangladesh","days":100, "emoji":"🫘"},
}

@app.route("/calendar")
@login_required
def calendar_page():
    current_month = datetime.now().strftime("%b")
    # Mark which crops can be sown or harvested this month
    for crop, data in CROP_CALENDAR.items():
        data["sow_now"]     = current_month in data["sow"]
        data["harvest_now"] = current_month in data["harvest"]
    return render_template("calendar.html", crops=CROP_CALENDAR,
                           current_month=current_month, months=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])


# ══════════════════════════════════════════════════════════════════
#  LANGUAGE TOGGLE
# ══════════════════════════════════════════════════════════════════
@app.route("/set-language/<lang>")
def set_language(lang):
    if lang in ("en", "bn"):
        session["lang"] = lang
    ref = request.referrer or ""
    if ref.startswith(request.host_url):
        return redirect(ref)
    return redirect(url_for("dashboard") if "user_id" in session else url_for("index"))


# ══════════════════════════════════════════════════════════════════
#  PDF FARM REPORT
# ══════════════════════════════════════════════════════════════════
def _report_tasks(uid):
    try:
        return tasks_for_user(uid, session.get("lang", "en"))[0][:8]
    except Exception as e:
        print("[report] tasks failed:", repr(e)); return []

def _report_weather(farms):
    try:
        city = next((f["location"] for f in farms if f["location"]), "Chittagong")
        w = get_weather(city)
        return w if w.get("source") == "live" else None      # never print mock weather in a report
    except Exception:
        return None

@app.route("/report")
@login_required
def report_page():
    uid = current_user()["id"]
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    farms = conn.execute(
        f"SELECT * FROM farms WHERE user_id={ph} ORDER BY farm_name", (uid,)
    ).fetchall()
    growth = conn.execute(
        f"""SELECT g.*, f.farm_name, f.crop_type FROM crop_growth g JOIN farms f ON g.farm_id=f.id
            WHERE g.user_id={ph} ORDER BY g.created_at DESC LIMIT 20""", (uid,)
    ).fetchall()
    irrigations = conn.execute(
        f"""SELECT i.*, f.farm_name FROM irrigation_log i JOIN farms f ON i.farm_id=f.id
            WHERE i.user_id={ph} ORDER BY i.date DESC LIMIT 20""", (uid,)
    ).fetchall()
    expenses = conn.execute(
        f"""SELECT e.*, f.farm_name FROM expense_log e JOIN farms f ON e.farm_id=f.id
            WHERE e.user_id={ph} ORDER BY e.date DESC LIMIT 50""", (uid,)
    ).fetchall()
    # Totals must cover ALL entries - the list above is only the latest 50 rows.
    tot = {r["type"]: float(r["s"] or 0) for r in conn.execute(
        f"SELECT type, SUM(amount) AS s FROM expense_log WHERE user_id={ph} GROUP BY type", (uid,)).fetchall()}
    total_income, total_expense = tot.get("income", 0.0), tot.get("expense", 0.0)
    profit = total_income - total_expense

    user = current_user()
    conn.close()
    today = datetime.now().strftime("%d %B %Y")
    return render_template("report.html",
        user=user, farms=farms, growth=growth,
        irrigations=irrigations, expenses=expenses,
        total_income=total_income, total_expense=total_expense,
        profit=profit, today=today, fin=finance_summary(uid),
        tasks=_report_tasks(uid), wx=_report_weather(farms))


# ══════════════════════════════════════════════════════════════════
#  ADMIN PANEL  (numbers only - never other people's records)
# ══════════════════════════════════════════════════════════════════
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}

def is_admin(user):
    """Set ADMIN_EMAILS (comma separated) in the environment to enable the panel."""
    try:
        return bool(user and ADMIN_EMAILS and (user["email"] or "").lower() in ADMIN_EMAILS)
    except Exception:
        return False

@app.route("/admin")
@login_required
def admin_panel():
    if not is_admin(current_user()):
        abort(404)                                    # do not even reveal that the page exists
    conn = get_db()
    def one(q, a=()):
        r = conn.execute(q, a).fetchone()
        return int(list(dict(r).values())[0] or 0)
    now = datetime.now()
    d7  = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    users = {
        "total": one("SELECT COUNT(*) FROM users WHERE role<>'demo'"),
        "new7": one("SELECT COUNT(*) FROM users WHERE role<>'demo' AND substr(created_at,1,10)>=?", (d7,)),
        "new30": one("SELECT COUNT(*) FROM users WHERE role<>'demo' AND substr(created_at,1,10)>=?", (d30,)),
        "google": one("SELECT COUNT(*) FROM users WHERE role<>'demo' AND google_id IS NOT NULL AND google_id<>''"),
        "with_farm": one("SELECT COUNT(DISTINCT user_id) FROM farms WHERE user_id IN (SELECT id FROM users WHERE role<>'demo')"),
        "push": one("SELECT COUNT(DISTINCT user_id) FROM push_subs"),
    }
    users["password"] = users["total"] - users["google"]
    feats = []
    for label, table, datecol in (("Farms", "farms", "created_at"), ("Income & expenses", "expense_log", "date"),
                                  ("Irrigation logs", "irrigation_log", "date"), ("Growth tracking", "crop_growth", "created_at"),
                                  ("Farm notes", "crop_notes", "created_at"), ("Fertilizer saved", "fertilizer_history", "created_at"),
                                  ("Disease photo scans", "disease_scans", "created_at"), ("Offline-synced entries", "offline_sync", None)):
        feats.append({"label": label,
                      "rows": one(f"SELECT COUNT(*) FROM {table}"),
                      "users": one(f"SELECT COUNT(DISTINCT user_id) FROM {table}"),
                      "last30": one(f"SELECT COUNT(*) FROM {table} WHERE substr({datecol},1,10)>=?", (d30,)) if datecol else None})
    signups = [dict(r) for r in conn.execute(
        "SELECT substr(created_at,1,10) AS day, COUNT(*) AS n FROM users WHERE role<>'demo' AND substr(created_at,1,10)>=? GROUP BY day ORDER BY day",
        ((now - timedelta(days=13)).strftime("%Y-%m-%d"),)).fetchall()]
    crops = [dict(r) for r in conn.execute(
        "SELECT LOWER(crop_type) AS crop, COUNT(*) AS n FROM farms GROUP BY LOWER(crop_type) ORDER BY n DESC LIMIT 8").fetchall()]
    area = one("SELECT COALESCE(CAST(SUM(area) AS INTEGER),0) FROM farms")
    conn.close()
    mx = max([s["n"] for s in signups] or [1])
    return render_template("admin.html", users=users, feats=feats, signups=signups, crops=crops, mx=mx, area=area,
                           push_on=PUSH_ENABLED, mail_on=MAIL_ENABLED,
                           mail_how=("Brevo API (HTTPS)" if (BREVO_API_KEY and MAIL_FROM) else
                                     "SMTP - blocked on Render's free plan, use BREVO_API_KEY + MAIL_FROM" if MAIL_ENABLED else ""),
                           brevo_half=bool(BREVO_API_KEY) != bool(MAIL_FROM) and not (BREVO_API_KEY and MAIL_FROM), gem=bool(os.environ.get("GEMINI_API_KEY")),
                           wx=bool(OPENWEATHER_KEY), when=now.strftime("%d %b %Y %H:%M"))


# ══════════════════════════════════════════════════════════════════
#  DOWNLOADS  (CSV for Excel / PDF report - own data only)
# ══════════════════════════════════════════════════════════════════
import exports

def _export_rows(uid, year=None):
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    yr = f" AND substr({{c}}.date,1,4)={ph}" if year else ""
    args = (uid, year) if year else (uid,)
    farms = [dict(r) for r in conn.execute(f"SELECT * FROM farms WHERE user_id={ph} ORDER BY farm_name", (uid,)).fetchall()]
    exp = [dict(r) for r in conn.execute(
        f"SELECT e.*, f.farm_name FROM expense_log e JOIN farms f ON e.farm_id=f.id WHERE e.user_id={ph}{yr.format(c='e')} ORDER BY e.date DESC LIMIT 5000", args).fetchall()]
    irr = [dict(r) for r in conn.execute(
        f"SELECT i.*, f.farm_name FROM irrigation_log i JOIN farms f ON i.farm_id=f.id WHERE i.user_id={ph}{yr.format(c='i')} ORDER BY i.date DESC LIMIT 5000", args).fetchall()]
    tot = {r["type"]: float(r["s"] or 0) for r in conn.execute(
        f"SELECT type, SUM(amount) AS s FROM expense_log WHERE user_id={ph} GROUP BY type", (uid,)).fetchall()}
    conn.close()
    return farms, exp, irr, (tot.get("income", 0.0), tot.get("expense", 0.0))

@app.route("/export/<kind>.<fmt>")
@login_required
def export_download(kind, fmt):
    uid = session["user_id"]
    if kind not in ("farms", "expenses", "irrigation", "report") or fmt not in ("csv", "pdf") or (kind == "report") != (fmt == "pdf"):
        abort(404)
    if throttle_blocked("dl:%s" % uid, 20, 600):
        return Response("Too many downloads, please wait a few minutes.", 429)
    throttle_hit("dl:%s" % uid)
    year = request.args.get("year", "")
    year = year if year.isdigit() and len(year) == 4 else None
    farms, exp, irr, totals = _export_rows(uid, year)
    stamp = datetime.now().strftime("%Y-%m-%d")
    if kind == "farms":
        body = exports.make_csv(["Farm", "Crop", "Location", "Area (acre)", "Planting date", "Status"],
                                [[f["farm_name"], f["crop_type"], f["location"], f["area"], f["planting_date"], f["status"]] for f in farms])
    elif kind == "expenses":
        body = exports.make_csv(["Date", "Farm", "Type", "Category", "Amount", "Description"],
                                [[e["date"], e["farm_name"], e["type"], e["category"], e["amount"], e["description"]] for e in exp])
    elif kind == "irrigation":
        body = exports.make_csv(["Date", "Farm", "Method", "Water (litres)", "Duration (min)", "Notes"],
                                [[i["date"], i["farm_name"], i["method"], i["water_liters"], i["duration_min"], i["notes"]] for i in irr])
    else:
        body = exports.make_pdf(current_user()["name"], stamp, farms, exp[:200], irr[:200], totals)
    mime = "application/pdf" if fmt == "pdf" else "text/csv; charset=utf-8"
    resp = Response(body, mimetype=mime)
    resp.headers["Content-Disposition"] = f'attachment; filename="greenfield-{kind}-{year or stamp}.{fmt}"'
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ══════════════════════════════════════════════════════════════════
#  PWA / uptime helpers
# ══════════════════════════════════════════════════════════════════
@app.route("/healthz")
def healthz():
    """Tiny, DB-free endpoint for uptime monitors (keeps the free instance awake)."""
    r = Response("ok", mimetype="text/plain")
    r.headers["Cache-Control"] = "no-store"
    return r

@app.route("/sw.js")
def service_worker():
    """Served from the site root so the worker controls every page (scope '/')."""
    path = os.path.join(app.static_folder, "sw.js")
    with open(path, encoding="utf-8") as fh:
        r = Response(fh.read(), mimetype="application/javascript")
    r.headers["Cache-Control"] = "no-cache"
    r.headers["Service-Worker-Allowed"] = "/"
    return r

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "The photo is too large. Please choose a smaller one."}), 413

@app.errorhandler(Exception)
def api_errors_as_json(e):
    """Make /api/* failures come back as JSON (never an HTML error page)."""
    from werkzeug.exceptions import HTTPException
    if request.path.startswith("/api/"):
        code = e.code if isinstance(e, HTTPException) else 500
        if not isinstance(e, HTTPException):
            print("[api error]", repr(e))
        return jsonify({"error": f"Server error ({code}). Please try again."}), code
    if isinstance(e, HTTPException):
        return e
    raise e

@app.route("/offline")
def offline_page():
    return render_template("offline.html")


# ══════════════════════════════════════════════════════════════════
#  PHOTO-BASED DISEASE ANALYSIS (vision AI)
# ══════════════════════════════════════════════════════════════════
_vision_hits = {}          # user_id -> [timestamps]; simple per-user rate limit
VISION_LIMIT, VISION_WINDOW = 12, 3600

@app.route("/api/disease-image", methods=["POST"])
@login_required
def api_disease_image():
    if is_demo():
        return demo_block_json()
    uid = session["user_id"]
    now = time.time()
    hits = [t for t in _vision_hits.get(uid, []) if now - t < VISION_WINDOW]
    if len(hits) >= VISION_LIMIT:
        return jsonify({"error": "You have reached the hourly photo-analysis limit. Please try again later."}), 429
    files = [f for f in request.files.getlist("image") if f][:3]
    if not files:
        return jsonify({"error": "Please choose or take a photo first."}), 400
    data = [f.read(vision.MAX_BYTES + 1) for f in files]
    photo_key = hashlib.sha256("".join(sorted(hashlib.sha256(d).hexdigest() for d in data)).encode()).hexdigest()
    crop = (request.form.get("crop_type") or "")[:40]
    notes = (request.form.get("notes") or "")[:600]
    lang = "bn" if session.get("lang") == "bn" else "en"
    if not vision.provider():
        return jsonify({"error": "Photo analysis is not enabled on this server yet (AI key missing).",
                        "not_configured": True}), 503
    try:
        hits.append(now); _vision_hits[uid] = hits
        result = vision.analyze(data, crop, notes, lang)
    except vision.VisionError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        print("[vision]", repr(e))
        return jsonify({"error": "Something went wrong while analysing the photo."}), 500
    result["scan_id"] = _save_scan(uid, result, crop, request.form.get("farm_id"),
                                   request.form.get("thumb", ""), lang, photo_key)
    return jsonify(result)


def _save_scan(uid, result, crop, farm_id, thumb, lang, photo_key=""):
    """Keep every successful analysis (small thumbnail only, never the full photo). Never fails the request."""
    try:
        conn = get_db()
        fid = 0
        try:
            fid = int(farm_id or 0)
        except ValueError:
            fid = 0
        if fid and not conn.execute("SELECT id FROM farms WHERE id=? AND user_id=?", (fid, uid)).fetchone():
            fid = 0
        if not (isinstance(thumb, str) and thumb.startswith("data:image/jpeg;base64,") and len(thumb) < 90000):
            thumb = ""
        # Same photo analysed again -> the newest result replaces the older one (keeps its farm link).
        old = conn.execute(
            "SELECT id, farm_id FROM disease_scans WHERE user_id=? AND ((?<>'' AND photo_key=?) OR (photo_key='' AND ?<>'' AND thumb=?))",
            (uid, photo_key, photo_key, thumb, thumb)).fetchall()
        if old:
            if not fid:
                fid = next((o["farm_id"] for o in old if o["farm_id"]), 0)
            for o in old:
                conn.execute("DELETE FROM disease_scans WHERE id=? AND user_id=?", (o["id"], uid))
        row = conn.execute(
            """INSERT INTO disease_scans (user_id,farm_id,crop,diagnosis,health_status,confidence,severity,result_json,thumb,lang,photo_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
            (uid, fid, crop, result.get("primary_diagnosis", ""), result.get("health_status", ""),
             int(result.get("confidence", 0)), result.get("severity", ""), json.dumps(result, ensure_ascii=False),
             thumb, lang, photo_key)).fetchone()
        conn.commit()
        sid = row[0] if row else None
        conn.close()
        return sid
    except Exception as e:
        print("[save_scan]", repr(e))
        return None


@app.route("/api/disease-history")
@login_required
def api_disease_history():
    conn = get_db()
    # one-time tidy of older duplicates (same photo scanned several times): keep only the newest
    seen = {}
    for r in conn.execute("SELECT id, thumb, photo_key FROM disease_scans WHERE user_id=? ORDER BY id DESC",
                          (session["user_id"],)).fetchall():
        key = (r["photo_key"] or r["thumb"] or "")
        if not key:
            continue
        if key in seen:
            conn.execute("DELETE FROM disease_scans WHERE id=? AND user_id=?", (r["id"], session["user_id"]))
        else:
            seen[key] = r["id"]
    conn.commit()
    rows = conn.execute(
        """SELECT d.id, d.crop, d.diagnosis, d.health_status, d.confidence, d.severity, d.thumb, d.created_at,
                  d.farm_id, f.farm_name
           FROM disease_scans d LEFT JOIN farms f ON f.id=d.farm_id
           WHERE d.user_id=? ORDER BY d.id DESC LIMIT 30""", (session["user_id"],)).fetchall()
    conn.close()
    return jsonify([{k: r[k] for k in ("id", "crop", "diagnosis", "health_status", "confidence", "severity",
                                       "thumb", "created_at", "farm_id", "farm_name")} for r in rows])


def _own_scan(conn, sid):
    return conn.execute("SELECT * FROM disease_scans WHERE id=? AND user_id=?", (sid, session["user_id"])).fetchone()


@app.route("/api/disease-history/<int:sid>")
@login_required
def api_disease_scan(sid):
    conn = get_db(); r = _own_scan(conn, sid); conn.close()
    if not r:
        return jsonify({"error": "Not found"}), 404
    data = json.loads(r["result_json"])
    data.update({"scan_id": r["id"], "farm_id": r["farm_id"], "created_at": r["created_at"], "crop": r["crop"]})
    return jsonify(data)


@app.route("/api/disease-history/<int:sid>/delete", methods=["POST"])
@login_required
def api_disease_scan_delete(sid):
    conn = get_db()
    conn.execute("DELETE FROM disease_scans WHERE id=? AND user_id=?", (sid, session["user_id"]))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


def _scan_text(r, data):
    """Plain-text summary of a scan, in the language it was analysed in."""
    bn = r["lang"] == "bn"
    L = (lambda en, bn_: bn_ if bn else en)
    t = data.get("treatment", {})
    lines = []
    if data.get("summary"):
        lines.append(data["summary"])
    lines.append(L("AI confidence: ", "AI-এর নিশ্চয়তা: ") + f"{data.get('confidence', 0)}%"
                 + (L(" · Severity: ", " · তীব্রতা: ") + data["severity"] if data.get("severity") not in (None, "", "None") else ""))
    for label, key in ((L("Do first", "প্রথমে করণীয়"), "immediate_steps"),
                       (L("Organic options", "জৈব উপায়"), "organic_options"),
                       (L("Chemical options", "রাসায়নিক উপায়"), "chemical_options")):
        items = t.get(key) or []
        if items:
            lines.append(label + ": " + "; ".join(items))
    if data.get("prevention"):
        lines.append(L("Prevention", "প্রতিরোধ") + ": " + "; ".join(data["prevention"]))
    lines.append(L("(From AI photo diagnosis, ", "(AI ছবি-নির্ণয় থেকে, ") + (r["created_at"] or "")[:10] + ")")
    return "\n".join(lines)


def _scan_title(r):
    bn = r["lang"] == "bn"
    name = r["diagnosis"] or ("সুস্থ গাছ" if bn else "Healthy plant" if r["health_status"] == "healthy" else "Plant check")
    if r["health_status"] == "healthy" and not r["diagnosis"]:
        name = "সুস্থ গাছ" if bn else "Healthy plant"
    return (("রোগ নির্ণয়: " if bn else "Diagnosis: ") + name)[:120]


@app.route("/api/disease-history/<int:sid>/to-note", methods=["POST"])
@login_required
def api_scan_to_note(sid):
    uid = session["user_id"]
    body = request.get_json(silent=True) or {}
    conn = get_db(); r = _own_scan(conn, sid)
    if not r:
        conn.close(); return jsonify({"error": "Not found"}), 404
    try:
        fid = int(body.get("farm_id") or r["farm_id"] or 0)
    except ValueError:
        fid = 0
    if not fid or not conn.execute("SELECT id FROM farms WHERE id=? AND user_id=?", (fid, uid)).fetchone():
        conn.close(); return jsonify({"error": "Please choose a farm first.", "need_farm": True}), 400
    data = json.loads(r["result_json"])
    cat = "Nutrition" if r["health_status"] == "nutrient_deficiency" else "Pest Control"
    conn.execute("INSERT INTO crop_notes (farm_id,user_id,title,note,category) VALUES (?,?,?,?,?)",
                 (fid, uid, _scan_title(r), _scan_text(r, data), cat))
    conn.execute("UPDATE disease_scans SET farm_id=? WHERE id=? AND user_id=?", (fid, sid, uid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/disease-history/<int:sid>/to-growth", methods=["POST"])
@login_required
def api_scan_to_growth(sid):
    uid = session["user_id"]
    body = request.get_json(silent=True) or {}
    conn = get_db(); r = _own_scan(conn, sid)
    if not r:
        conn.close(); return jsonify({"error": "Not found"}), 404
    try:
        fid = int(body.get("farm_id") or r["farm_id"] or 0)
    except ValueError:
        fid = 0
    if not fid or not conn.execute("SELECT id FROM farms WHERE id=? AND user_id=?", (fid, uid)).fetchone():
        conn.close(); return jsonify({"error": "Please choose a farm first.", "need_farm": True}), 400
    g = conn.execute("SELECT id, notes FROM crop_growth WHERE farm_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
                     (fid, uid)).fetchone()
    if not g:
        conn.close()
        return jsonify({"error": "This farm has no growth record yet. Add one in Growth Tracker first, or use Farm Notes.",
                        "no_growth": True}), 400
    line = f"[{(r['created_at'] or '')[:10]}] {_scan_title(r)} ({r['confidence']}%)"
    new_notes = ((g["notes"] or "").rstrip() + "\n" + line).strip()[:2000]
    conn.execute("UPDATE crop_growth SET notes=? WHERE id=? AND user_id=?", (new_notes, g["id"], uid))
    conn.execute("UPDATE disease_scans SET farm_id=? WHERE id=? AND user_id=?", (fid, sid, uid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})



# ══════════════════════════════════════════════════════════════════
#  TODAY'S TASKS  (rule-based: crop age + last irrigation + 24 h forecast)
# ══════════════════════════════════════════════════════════════════
def tasks_for_user(uid, lang="en"):
    from concurrent.futures import ThreadPoolExecutor
    import requests as _rq
    conn = get_db()
    farms = [dict(r) for r in conn.execute(
        "SELECT id, farm_name, crop_type, location, planting_date, status FROM farms WHERE user_id=? ORDER BY farm_name LIMIT 12",
        (uid,)).fetchall()]
    info, soil = {}, {}
    for f in farms:
        g = conn.execute("SELECT expected_days, growth_stage FROM crop_growth WHERE farm_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
                         (f["id"], uid)).fetchone()
        i = conn.execute("SELECT date FROM irrigation_log WHERE farm_id=? AND user_id=? ORDER BY date DESC LIMIT 1",
                         (f["id"], uid)).fetchone()
        sc = conn.execute("""SELECT diagnosis, health_status, severity, created_at FROM disease_scans
                             WHERE farm_id=? AND user_id=? ORDER BY id DESC LIMIT 1""", (f["id"], uid)).fetchone()
        sr = conn.execute("SELECT moisture, created_at FROM sensor_readings WHERE farm_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
                          (f["id"], uid)).fetchone()
        soil[f["id"]] = {"moisture": float(sr["moisture"]), "age_hours": _age_hours(sr["created_at"])} if sr else None
        info[f["id"]] = (dict(g) if g else None, i["date"] if i else None, dict(sc) if sc else None)
    conn.close()
    active = [f for f in farms if (f.get("status") or "").lower() not in ("harvested", "inactive", "closed")]
    cities = sorted({(f["location"] or "").strip() for f in active if f.get("location")})
    wx = {}
    if OPENWEATHER_KEY and cities:
        with ThreadPoolExecutor(max_workers=4) as ex:
            res = list(ex.map(lambda c: farm_tasks.fetch_forecast(c, OPENWEATHER_KEY, _rq), cities[:6]))
        wx = dict(zip(cities[:6], res))
    tasks = []
    for f in active:
        g, li, sc = info[f["id"]]
        tasks += farm_tasks.build_tasks(f, g, li, sc, wx.get((f["location"] or "").strip()), lang=lang, soil=soil.get(f["id"]))
    return farm_tasks.sort_tasks(tasks), bool(wx and any(wx.values())), len(active)

@app.route("/api/today-tasks")
@login_required
def api_today_tasks():
    tasks, has_weather, n_farms = tasks_for_user(session["user_id"], session.get("lang", "en"))
    return jsonify({"tasks": tasks, "weather": has_weather, "farms": n_farms,
                    "date": datetime.now().strftime("%Y-%m-%d")})


# ══════════════════════════════════════════════════════════════════
#  DOWNLOAD MY DATA  (own data only, JSON)
# ══════════════════════════════════════════════════════════════════
@app.route("/account/export")
@login_required
def export_my_data():
    uid = session["user_id"]
    conn = get_db()
    def rows(sql):
        return [dict(r) for r in conn.execute(sql, (uid,)).fetchall()]
    data = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "profile": rows("SELECT id, name, email, account_id, created_at FROM users WHERE id=?"),
        "farms": rows("SELECT * FROM farms WHERE user_id=?"),
        "farm_notes": rows("SELECT * FROM crop_notes WHERE user_id=?"),
        "growth": rows("SELECT * FROM crop_growth WHERE user_id=?"),
        "irrigation": rows("SELECT * FROM irrigation_log WHERE user_id=?"),
        "expenses": rows("SELECT * FROM expense_log WHERE user_id=?"),
        "fertilizer_history": rows("SELECT * FROM fertilizer_history WHERE user_id=?"),
        "disease_scans": rows("SELECT id, farm_id, crop, diagnosis, health_status, confidence, severity, created_at FROM disease_scans WHERE user_id=?"),
        "sensor_devices": rows("SELECT id, farm_id, name, created_at, last_seen FROM sensor_devices WHERE user_id=?"),   # never the token
        "sensor_readings": rows("SELECT id, device_id, farm_id, moisture, temp, source, created_at FROM sensor_readings WHERE user_id=? ORDER BY id DESC LIMIT 5000"),
        "forecast_inputs": rows("SELECT farm_id, yield_per_acre, price_per_kg, remaining_cost FROM forecast_inputs WHERE user_id=?"),
    }
    conn.close()
    r = Response(json.dumps(data, ensure_ascii=False, indent=2, default=str), mimetype="application/json")
    r.headers["Content-Disposition"] = f'attachment; filename="greenfield-my-data-{datetime.now():%Y%m%d}.json"'
    r.headers["Cache-Control"] = "no-store"
    return r


# ══════════════════════════════════════════════════════════════════
#  PUSH ALERTS  (Web Push - needs VAPID keys in the environment; otherwise the feature stays hidden)
# ══════════════════════════════════════════════════════════════════
VAPID_PUBLIC_KEY  = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT     = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")
CRON_TOKEN        = os.environ.get("CRON_TOKEN", "")
PUSH_ENABLED      = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)
PUSH_KINDS        = {"rain_alert", "heat_alert", "fungal", "harvest_now", "harvest_soon", "irrigate", "skip_irrigation", "soil_dry"}
# Alerts that would repeat every day are sent once per this many days (default: once a day).
PUSH_REPEAT_DAYS  = {"harvest_soon": 3, "harvest_now": 2, "irrigate": 2, "skip_irrigation": 1, "soil_dry": 1}

@app.route("/api/push/key")
@login_required
def api_push_key():
    if not PUSH_ENABLED:
        return jsonify({"enabled": False}), 200
    return jsonify({"enabled": True, "key": VAPID_PUBLIC_KEY})

_PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "push.services.mozilla.com",
               "notify.windows.com", "push.apple.com", "web.push.apple.com")
def push_endpoint_ok(ep):
    """Only the real browser push services may be called by the server (blocks SSRF / internal hosts)."""
    try:
        u = urlparse(ep)
        host = (u.hostname or "").lower()
        if u.scheme != "https" or u.username or u.password or u.port not in (None, 443) or len(ep) > 1000:
            return False
        return any(host == h or host.endswith("." + h) for h in _PUSH_HOSTS)
    except Exception:
        return False

@app.route("/api/push/subscribe", methods=["POST"])
@login_required
def api_push_subscribe():
    if is_demo():
        return demo_block_json()
    if not PUSH_ENABLED:
        return jsonify({"error": "Alerts are not configured on this server."}), 503
    b = request.get_json(silent=True) or {}
    ep, keys = (b.get("endpoint") or ""), (b.get("keys") or {})
    if (not isinstance(ep, str) or not isinstance(keys, dict) or not push_endpoint_ok(ep)
            or not isinstance(keys.get("p256dh"), str) or not isinstance(keys.get("auth"), str)
            or not keys.get("p256dh") or not keys.get("auth")):
        return jsonify({"error": "Invalid subscription."}), 400
    uid = session["user_id"]
    conn = get_db()
    conn.execute("DELETE FROM push_subs WHERE endpoint=?", (ep,))
    # at most 5 devices per user: forget the oldest ones
    old = conn.execute("SELECT id FROM push_subs WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    for r in old[4:]:
        conn.execute("DELETE FROM push_subs WHERE id=?", (r["id"],))
    conn.execute("INSERT INTO push_subs (user_id,endpoint,p256dh,auth,lang) VALUES (?,?,?,?,?)",
                 (uid, ep, keys["p256dh"][:200], keys["auth"][:100], session.get("lang", "en")))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/push/unsubscribe", methods=["POST"])
@login_required
def api_push_unsubscribe():
    ep = (request.get_json(silent=True) or {}).get("endpoint", "")
    conn = get_db()
    conn.execute("DELETE FROM push_subs WHERE endpoint=? AND user_id=?", (ep, session["user_id"]))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

_last_test_push = {}

@app.route("/api/push/test", methods=["POST"])
@login_required
def api_push_test():
    if is_demo():
        return demo_block_json()
    """Send a test notification to the signed-in user's own devices (once per 20 s)."""
    if not PUSH_ENABLED:
        return jsonify({"error": "Alerts are not configured on this server."}), 503
    uid = session["user_id"]
    now = time.time()
    if now - _last_test_push.get(uid, 0) < 20:
        return jsonify({"error": "Please wait a few seconds."}), 429
    _last_test_push[uid] = now
    conn = get_db()
    subs = [dict(r) for r in conn.execute("SELECT * FROM push_subs WHERE user_id=?", (uid,)).fetchall()]
    sent = gone = failed = 0
    bn = session.get("lang") == "bn"
    payload = {"title": "🌱 GreenField", "tag": "gf-test", "url": "/dashboard",
               "body": "অ্যালার্ট ঠিকমতো কাজ করছে ✓" if bn else "Test alert — your alerts are working ✓"}
    for sub in subs:
        r = send_push(sub, payload)
        if r == "ok": sent += 1
        elif r == "gone":
            gone += 1
            conn.execute("DELETE FROM push_subs WHERE id=?", (sub["id"],)); conn.commit()
        else: failed += 1
    conn.close()
    return jsonify({"sent": sent, "expired": gone, "failed": failed, "devices": len(subs)})

def send_push(sub, payload):
    """Send one notification. Returns 'ok', 'gone' (subscription expired) or 'error'."""
    try:
        from pywebpush import webpush, WebPushException
    except Exception:
        return "error"
    if not push_endpoint_ok(sub["endpoint"]):
        return "gone"                              # not a real browser push service: drop it
    try:
        webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                data=json.dumps(payload, ensure_ascii=False), vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT}, ttl=6 * 3600, timeout=10)
        return "ok"
    except WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        return "gone" if code in (404, 410) else "error"
    except Exception:
        return "error"

@app.route("/api/cron/alerts", methods=["POST"])
def api_cron_alerts():
    """Called every few hours by the GitHub Actions 'alerts' workflow. Protected by CRON_TOKEN."""
    tok = request.headers.get("X-Cron-Token", "")
    if not CRON_TOKEN or not PUSH_ENABLED or not hmac.compare_digest(tok.encode("utf-8"), CRON_TOKEN.encode("utf-8")):
        return jsonify({"error": "forbidden"}), 403
    day = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    subs = [dict(r) for r in conn.execute("SELECT * FROM push_subs").fetchall()]
    conn.close()
    sent = gone = 0
    by_user = {}
    for s in subs:
        by_user.setdefault(s["user_id"], []).append(s)
    for uid, usubs in by_user.items():
        lang = usubs[0].get("lang") or "en"
        try:
            tasks, _, _ = tasks_for_user(uid, lang)
        except Exception as e:
            print("[alerts] tasks failed", uid, repr(e)); continue
        conn = get_db()
        for t in tasks:
            if t["kind"] not in PUSH_KINDS:
                continue
            since = (datetime.now() - timedelta(days=PUSH_REPEAT_DAYS.get(t["kind"], 1) - 1)).strftime("%Y-%m-%d")
            if conn.execute("SELECT id FROM push_log WHERE user_id=? AND task_id=? AND day>=?", (uid, t["id"], since)).fetchone():
                continue
            conn.execute("INSERT INTO push_log (user_id,task_id,day) VALUES (?,?,?)", (uid, t["id"], day))
            conn.commit()
            payload = {"title": f'{t["icon"]} {t["title"]} — {t["farm"]}', "body": t["detail"][:180],
                       "url": t["link"] or "/dashboard", "tag": t["id"]}
            for s in usubs:
                r = send_push(s, payload)
                if r == "ok": sent += 1
                elif r == "gone":
                    gone += 1
                    conn.execute("DELETE FROM push_subs WHERE id=?", (s["id"],)); conn.commit()
        conn.execute("DELETE FROM push_log WHERE day<?", ((datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),))
        conn.commit(); conn.close()
    return jsonify({"users": len(by_user), "sent": sent, "expired": gone})


# ══════════════════════════════════════════════════════════════════
#  SOIL SENSORS  (a device sends readings with its own secret token; the owner sees them here)
#  No hardware is required: readings can also be typed in by hand or sent by tools/sensor_simulator.py
# ══════════════════════════════════════════════════════════════════
import forecast as fc

@app.template_global()
def tr(en, bn):
    """Pick the English or Bangla text for the current language (used by the newer pages)."""
    return bn if session.get("lang") == "bn" else en

@app.template_filter("money")
def money_filter(v):
    try:
        return "৳{:,.0f}".format(float(v))
    except (TypeError, ValueError):
        return "—"

def _utcnow_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def _age_hours(created_at):
    """Hours since a reading (stored as naive UTC text); a huge number if it cannot be read."""
    try:
        t = datetime.strptime(str(created_at)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return 9999.0
    return max(0.0, (datetime.now(timezone.utc) - t).total_seconds() / 3600)

def _bd_label(created_at):
    """UTC text -> 'MM-DD HH:MM' in Bangladesh time (UTC+6, no daylight saving)."""
    try:
        t = datetime.strptime(str(created_at)[:19], "%Y-%m-%d %H:%M:%S") + timedelta(hours=6)
        return t.strftime("%m-%d %H:%M")
    except ValueError:
        return ""

MAX_DEVICES_PER_USER = 5
SENSOR_KEEP_DAYS = 30

def _sensor_base_url():
    return (APP_BASE_URL or request.host_url).rstrip("/")

def _sensors_context(conn, uid, new_token=None, new_device=None):
    farms = [dict(r) for r in conn.execute("SELECT id, farm_name, crop_type FROM farms WHERE user_id=? ORDER BY farm_name", (uid,)).fetchall()]
    since = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    devices = []
    for d in conn.execute("""SELECT d.*, f.farm_name FROM sensor_devices d JOIN farms f ON f.id=d.farm_id
                             WHERE d.user_id=? ORDER BY d.id""", (uid,)).fetchall():
        d = dict(d)
        pts = [dict(r) for r in conn.execute(
            "SELECT moisture, temp, created_at FROM sensor_readings WHERE device_id=? AND user_id=? AND created_at>=? ORDER BY id DESC LIMIT 200",
            (d["id"], uid, since)).fetchall()][::-1]
        last = conn.execute("SELECT moisture, temp, source, created_at FROM sensor_readings WHERE device_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
                            (d["id"], uid)).fetchone()
        d["last"] = dict(last) if last else None
        if d["last"]:
            d["last"]["age_h"] = _age_hours(d["last"]["created_at"])
            d["last"]["when"] = _bd_label(d["last"]["created_at"])
        d["chart"] = {"labels": [_bd_label(p["created_at"]) for p in pts],
                      "moisture": [p["moisture"] for p in pts],
                      "temp": [p["temp"] for p in pts]}
        d["token_hint"] = d.get("token_hint") or ""
        devices.append(d)
    return {"farms": farms, "devices": devices, "new_token": new_token, "new_device": new_device,
            "base_url": _sensor_base_url(), "dry": farm_tasks.SOIL_DRY_BELOW, "wet": farm_tasks.SOIL_WET_ABOVE,
            "fresh_h": farm_tasks.SOIL_FRESH_HOURS, "max_devices": MAX_DEVICES_PER_USER}

@app.route("/sensors")
@login_required
def sensors_page():
    conn = get_db()
    ctx = _sensors_context(conn, session["user_id"])
    conn.close()
    return render_template("sensors.html", **ctx)

@app.route("/sensors/add", methods=["POST"])
@login_required
def sensors_add():
    uid = session["user_id"]
    conn = get_db()
    fid = owned_farm_id(conn, uid, request.form.get("farm_id"))
    name = clip(request.form.get("name"), 40) or "Soil sensor"
    n = conn.execute("SELECT COUNT(*) AS c FROM sensor_devices WHERE user_id=?", (uid,)).fetchone()["c"]
    if fid is None:
        conn.close(); flash("Choose one of your farms.", "error"); return redirect(url_for("sensors_page"))
    if n >= MAX_DEVICES_PER_USER:
        conn.close(); flash(f"You can add up to {MAX_DEVICES_PER_USER} sensors.", "error"); return redirect(url_for("sensors_page"))
    token = "gfs_" + secrets.token_urlsafe(24)
    conn.execute("INSERT INTO sensor_devices (user_id, farm_id, name, token_hash, token_hint, created_at) VALUES (?,?,?,?,?,?)",
                 (uid, fid, name, hash_token(token), token[-4:], _utcnow_str()))
    conn.commit()
    ctx = _sensors_context(conn, uid, new_token=token, new_device=name)
    conn.close()
    resp = make_response(render_template("sensors.html", **ctx))   # the token is shown ONCE, here, and never stored in clear text
    resp.headers["Cache-Control"] = "no-store"
    return resp

def _own_device(conn, uid, did):
    return conn.execute("SELECT * FROM sensor_devices WHERE id=? AND user_id=?", (to_int(did, 1, 2**31 - 1, 0), uid)).fetchone()

@app.route("/sensors/<int:did>/delete", methods=["POST"])
@login_required
def sensors_delete(did):
    uid = session["user_id"]
    conn = get_db()
    if _own_device(conn, uid, did):
        conn.execute("DELETE FROM sensor_readings WHERE device_id=? AND user_id=?", (did, uid))
        conn.execute("DELETE FROM sensor_devices WHERE id=? AND user_id=?", (did, uid))
        conn.commit()
        flash("Sensor removed. Its token no longer works.", "success")
    conn.close()
    return redirect(url_for("sensors_page"))

@app.route("/sensors/<int:did>/reading", methods=["POST"])
@login_required
def sensors_manual_reading(did):
    """The farmer types in a reading (e.g. from a cheap hand-held probe, or to try the feature without hardware)."""
    uid = session["user_id"]
    conn = get_db()
    d = _own_device(conn, uid, did)
    moist = to_float(request.form.get("moisture"), 0, 100)
    temp_raw = (request.form.get("temp") or "").strip()
    temp = to_float(temp_raw, -20, 70) if temp_raw else None
    if not d or moist is None or (temp_raw and temp is None):
        conn.close(); flash("Enter moisture between 0 and 100 (temperature between -20 and 70, optional).", "error")
        return redirect(url_for("sensors_page"))
    conn.execute("INSERT INTO sensor_readings (device_id, farm_id, user_id, moisture, temp, source, created_at) VALUES (?,?,?,?,?,?,?)",
                 (did, d["farm_id"], uid, moist, temp, "manual", _utcnow_str()))
    conn.execute("UPDATE sensor_devices SET last_seen=? WHERE id=?", (_utcnow_str(), did))
    conn.commit(); conn.close()
    flash("Reading saved.", "success")
    return redirect(url_for("sensors_page"))

@app.route("/api/sensor/ingest", methods=["POST"])
def api_sensor_ingest():
    """For the sensor itself:  POST  {"moisture": 41.5, "temp": 28.2}  with  Authorization: Bearer gfs_...
    Token-authenticated, so it needs no login or cookie; wrong tokens are throttled per IP, readings per device."""
    ip = client_ip()
    if throttle_blocked("sensfail:" + ip, 30, 600):
        return jsonify({"error": "too many failed attempts"}), 429
    if (request.content_length or 0) > 2048:
        return jsonify({"error": "payload too large"}), 413
    auth = request.headers.get("Authorization", "")
    tok = auth[7:].strip() if auth[:7].lower() == "bearer " else request.headers.get("X-Device-Token", "").strip()
    conn = get_db()
    dev = None
    if tok.startswith("gfs_") and len(tok) <= 100:
        dev = conn.execute("SELECT id, user_id, farm_id FROM sensor_devices WHERE token_hash=?", (hash_token(tok),)).fetchone()
    if not dev:
        conn.close(); throttle_hit("sensfail:" + ip)
        return jsonify({"error": "invalid token"}), 401
    key = f"sens:{dev['id']}"
    if throttle_blocked(key, 120, 3600):
        conn.close(); return jsonify({"error": "too many readings (limit 120 per hour)"}), 429
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    moist = to_float(data.get("moisture"), 0, 100)
    temp = to_float(data.get("temp"), -20, 70) if data.get("temp") is not None else None
    if moist is None or (data.get("temp") is not None and temp is None):
        conn.close(); return jsonify({"error": "moisture must be 0-100 (and temp -20..70 if sent)"}), 400
    throttle_hit(key)
    now = _utcnow_str()
    conn.execute("INSERT INTO sensor_readings (device_id, farm_id, user_id, moisture, temp, source, created_at) VALUES (?,?,?,?,?,?,?)",
                 (dev["id"], dev["farm_id"], dev["user_id"], moist, temp, "device", now))
    conn.execute("UPDATE sensor_devices SET last_seen=? WHERE id=?", (now, dev["id"]))
    conn.execute("DELETE FROM sensor_readings WHERE device_id=? AND created_at<?",
                 (dev["id"], (datetime.now(timezone.utc) - timedelta(days=SENSOR_KEEP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()
    return jsonify({"ok": True}), 201


# ══════════════════════════════════════════════════════════════════
#  YIELD + PROFIT/LOSS FORECAST  (transparent arithmetic - see forecast.py)
# ══════════════════════════════════════════════════════════════════
def _price_for(conn, uid, ck, override):
    """(price per kg, source tag, note) - the farmer's own number first, then their last recorded price, then a haircut reference."""
    if override and override > 0:
        return override, "yours", ""
    word = fc.PRICE_MATCH.get(ck)
    if word:
        rows = conn.execute("SELECT crop, price, day FROM price_history WHERE user_id=? AND source='manual' ORDER BY day DESC, id DESC",
                            (uid,)).fetchall()
        for r in rows:
            if word in (r["crop"] or "").lower():
                return float(r["price"]), "recorded", r["day"]
    ref = fc.reference_price(ck, _MARKET_FALLBACK)
    if ref:
        return round(ref * fc.FARMGATE_FACTOR, 1), "reference", f"{int(fc.FARMGATE_FACTOR * 100)}% of ৳{ref:g}"
    return None, "", ""

def forecast_rows(uid):
    conn = get_db()
    farms = [dict(r) for r in conn.execute("SELECT id, farm_name, crop_type, area, planting_date, status FROM farms WHERE user_id=? ORDER BY farm_name", (uid,)).fetchall()]
    inputs = {r["farm_id"]: dict(r) for r in conn.execute("SELECT * FROM forecast_inputs WHERE user_id=?", (uid,)).fetchall()}
    rows = []
    for f in farms:
        ck = farm_tasks.crop_key(f["crop_type"])
        t = {r["type"]: float(r["s"] or 0) for r in conn.execute(
            "SELECT type, SUM(amount) AS s FROM expense_log WHERE farm_id=? AND user_id=? GROUP BY type", (f["id"], uid)).fetchall()}
        inp = inputs.get(f["id"], {})
        price, psrc, pnote = _price_for(conn, uid, ck, inp.get("price_per_kg"))
        try:
            area = float(f["area"] or 0)
        except (TypeError, ValueError):
            area = 0.0
        res = fc.forecast_farm(ck, area, price, t.get("expense", 0.0), t.get("income", 0.0),
                               inp.get("yield_per_acre"), inp.get("remaining_cost"))
        g = conn.execute("SELECT harvest_date FROM crop_growth WHERE farm_id=? AND user_id=? ORDER BY id DESC LIMIT 1", (f["id"], uid)).fetchone()
        harvest = (g["harvest_date"] if g and g["harvest_date"] else "")
        if not harvest and f.get("planting_date") and ck in farm_tasks.EXPECTED_DAYS:
            pd_ = farm_tasks._d(f["planting_date"])
            if pd_:
                harvest = (pd_ + timedelta(days=farm_tasks.EXPECTED_DAYS[ck])).isoformat()
        rows.append({"farm": f, "ck": ck, "fc": res, "price_src": psrc, "price_note": pnote, "inp": inp,
                     "income_so_far": t.get("income", 0.0), "harvest": harvest})
    conn.close()
    return rows

@app.route("/forecast")
@login_required
def forecast_page():
    rows = forecast_rows(session["user_id"])
    ok = [r["fc"] for r in rows if r["fc"]["ok"]]
    tot = None
    if ok:
        tot = {"partial": any(not x["costs_known"] for x in ok),
               "profit": [sum(x["profit"][i] for x in ok) for i in range(3)],
               "income": [sum(x["income_total"][i] for x in ok) for i in range(3)],
               "cost": sum(x["cost"] for x in ok), "n": len(ok)}
    return render_template("forecast.html", rows=rows, tot=tot, factor=int(fc.FARMGATE_FACTOR * 100),
                           spread=int(fc.SPREAD * 100), maund=int(fc.MAUND_KG))

@app.route("/forecast/save", methods=["POST"])
@login_required
def forecast_save():
    uid = session["user_id"]
    conn = get_db()
    fid = owned_farm_id(conn, uid, request.form.get("farm_id"))
    if fid is None:
        conn.close(); flash("Farm not found.", "error"); return redirect(url_for("forecast_page"))
    def num(name, hi):
        raw = (request.form.get(name) or "").strip()
        return (to_float(raw, 0, hi), bool(raw))
    y, y_given = num("yield_per_acre", 100000)
    p, p_given = num("price_per_kg", 100000)
    c, c_given = num("remaining_cost", 1e9)
    if (y_given and y is None) or (p_given and p is None) or (c_given and c is None):
        conn.close(); flash("Please enter valid positive numbers.", "error"); return redirect(url_for("forecast_page"))
    # empty field = "use the default"; store NULL
    conn.execute("DELETE FROM forecast_inputs WHERE user_id=? AND farm_id=?", (uid, fid))
    if y or p or c_given:          # "0" is a real answer for costs still to come ("nothing left to spend")
        conn.execute("INSERT INTO forecast_inputs (user_id, farm_id, yield_per_acre, price_per_kg, remaining_cost, updated_at) VALUES (?,?,?,?,?,?)",
                     (uid, fid, y or None, p or None, c if c_given else None, _utcnow_str()))
    conn.commit(); conn.close()
    flash("Forecast inputs saved.", "success")
    return redirect(url_for("forecast_page") + f"#farm{fid}")


# ── Entry ─────────────────────────────────────────────────────────
# Always init DB (works for both gunicorn and dev server)
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") != "production"
    print(f"🌱  GreenField → http://127.0.0.1:{port}")
    app.run(debug=debug, host="0.0.0.0", port=port)
