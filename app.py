"""
GreenField Smart Farming App — app.py v7
Flask 3 | SQLite (local) / PostgreSQL (production) | Auth | Google OAuth | Profile Photo | Full CRUD
"""
import os, sqlite3, json, hashlib, secrets, base64, string
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (Flask, render_template, request, redirect,
                   url_for, jsonify, flash, session, Response, abort)
import i18n
import vision
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
MAIL_ENABLED  = bool(MAIL_SERVER and MAIL_USERNAME and MAIL_PASSWORD)
APP_BASE_URL  = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000")

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024   # photo uploads (profile photo / disease photo)
app.secret_key = os.environ.get("SECRET_KEY", "gf_smartfarm_dev_secret_2024")

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
    interface regardless of which database backend is active."""
    if USE_POSTGRES:
        raw = psycopg2.connect(DATABASE_URL)
        return PGConnWrapper(raw)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn


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
        print("=" * 60)
        print(f"[PASSWORD RESET] Email not configured — link for {to_email}:")
        print(reset_link)
        print("=" * 60)
        return True

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Reset your GreenField password"
        msg["From"] = MAIL_USERNAME
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
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT, timeout=10) as server:
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_USERNAME, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[PASSWORD RESET] Email send failed: {e}")
        print(f"[PASSWORD RESET] Fallback link for {to_email}: {reset_link}")
        return False

# ══════════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ══════════════════════════════════════════════════════════════════
def login_required(f):
    """Decorator — redirects to /login if not logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
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
@app.context_processor
def inject_user():
    lang = session.get("lang", "en")
    user = current_user()
    avatar_url = ""
    if user and user["avatar_photo"]:
        photo = user["avatar_photo"]
        ver = hashlib.md5((str(len(photo)) + photo[-200:]).encode()).hexdigest()[:8]
        avatar_url = url_for("avatar", uid=user["id"], v=ver)
    return {
        "current_user": user,
        "lang": lang,
        "is_bn": lang == "bn",
        "avatar_url": avatar_url,
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

def get_weather(city="Chittagong"):
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
                f"?q={q}&appid={OPENWEATHER_KEY}&units=metric&cnt=7", timeout=5) as r:
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

            forecast, seen = [], set()
            for item in fr.get("list",[]):
                day = item["dt_txt"][:10]
                if day not in seen:
                    seen.add(day)
                    forecast.append({"day":datetime.strptime(day,"%Y-%m-%d").strftime("%a"),
                                     "temp":round(item["main"]["temp"]),
                                     "icon":_owm_icon(item["weather"][0]["icon"]),
                                     "desc":item["weather"][0]["main"]})
                if len(forecast)==7: break
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
            m = _mock_weather(city); m["api_error"] = str(e); return m
    return _mock_weather(city)

def _mock_weather(city="Chittagong"):
    seed = int(hashlib.md5(city.lower().encode()).hexdigest()[:4],16) % 20
    cond = ["Partly Cloudy","Sunny","Overcast","Light Rain"][seed%4]
    imap = {"Partly Cloudy":"cloud-sun","Sunny":"sun","Overcast":"cloud","Light Rain":"cloud-rain"}
    t    = 27+seed%8
    days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    ic   = ["cloud-sun","sun","cloud","cloud-rain","sun","sun","cloud-sun"]
    forecast = [{"day":days[i],"temp":t+(i%3)-1,"icon":ic[i],"desc":cond} for i in range(7)]
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
        if len(password) < 6:    errors.append("Password must be at least 6 characters.")
        if password != confirm:   errors.append("Passwords do not match.")
        if not errors:
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
                conn.close()
                flash(f"🌱 Welcome to GreenField, <strong>{name}</strong>! Your account is ready.", "success")
                return redirect(url_for("dashboard"))
            conn.close()
        for e in errors: flash(e, "error")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email    = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        conn     = get_db()
        user     = conn.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            _lang = session.get("lang")
            session.clear()
            if _lang: session["lang"] = _lang
            session["user_id"]   = user["id"]
            session["user_name"] = user["name"]
            flash(f"👋 Welcome back, <strong>{user['name']}</strong>!", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid email or password. Please try again.", "error")
    return render_template("login.html", google_enabled=GOOGLE_OAUTH_ENABLED)

@app.route("/logout")
def logout():
    _lang = session.get("lang")
    session.clear()
    if _lang: session["lang"] = _lang
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


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
        name      = user_info.get("name", "Google User")
        picture   = user_info.get("picture", "")

        conn = get_db()
        # Check if user exists by google_id or email
        existing = conn.execute(
            "SELECT * FROM users WHERE google_id=? OR email=?", (google_id, email)
        ).fetchone()

        if existing:
            # Update google_id if logging in with Google for the first time on existing account
            if not existing["google_id"]:
                conn.execute("UPDATE users SET google_id=? WHERE id=?", (google_id, existing["id"]))
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

        conn.close()
        session["user_id"]   = uid
        session["user_name"] = uname
        session["user_email"]= email
        flash(f"✅ Logged in with Google as {uname}.", "success")
        return redirect(url_for("dashboard"))
    except Exception as e:
        flash(f"Google login failed: {str(e)}", "error")
        return redirect(url_for("login"))


# ── Forgot / Reset Password ─────────────────────────────────────────
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        conn  = get_db()
        user  = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        # Always show the same message whether or not the email exists —
        # this prevents attackers from discovering which emails are registered.
        if user:
            token      = secrets.token_urlsafe(32)
            expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
            conn.execute(
                "INSERT INTO password_resets (user_id, token, expires_at, used) VALUES (?,?,?,0)",
                (user["id"], token, expires_at)
            )
            conn.commit()
            reset_link = f"{APP_BASE_URL}/reset-password/{token}"
            send_reset_email(user["email"], user["name"], reset_link)
            log_activity("requested", "password_reset", f"For {email}")

        conn.close()
        flash("If that email is registered, a reset link has been sent. "
              "Check your inbox (and the server log if email isn't configured).", "success")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    conn = get_db()
    reset_row = conn.execute(
        "SELECT * FROM password_resets WHERE token=?", (token,)
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

        if len(new_pw) < 6:
            flash("Password must be at least 6 characters.", "error")
        elif new_pw != confirm:
            flash("Passwords do not match.", "error")
        else:
            conn.execute(
                "UPDATE users SET password=? WHERE id=?",
                (generate_password_hash(new_pw), reset_row["user_id"])
            )
            conn.execute(
                "UPDATE password_resets SET used=1 WHERE token=?", (token,)
            )
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
            elif len(new_pw) < 6:
                flash("New password must be at least 6 characters.", "error")
            elif new_pw != confirm_pw:
                flash("Passwords do not match.", "error")
            else:
                conn.execute("UPDATE users SET password=? WHERE id=?",
                             (generate_password_hash(new_pw), uid))
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
                    photo_bytes = photo.read(5 * 1024 * 1024)  # max 5MB
                    if len(photo_bytes) >= 5 * 1024 * 1024:
                        flash("Image too large. Maximum size is 5 MB.", "error")
                    else:
                        b64 = base64.b64encode(photo_bytes).decode("utf-8")
                        data_url = f"data:{photo.content_type};base64,{b64}"
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
                conn.execute("DELETE FROM disease_scans WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM crop_notes WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM farms WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM fertilizer_history WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM users WHERE id=?", (uid,))
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
        crop_dist=crop_dist,     weather=get_weather())

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
    name=d.get("farm_name","").strip(); crop=d.get("crop_type","").strip()
    loc=d.get("location","").strip();   pdate=d.get("planting_date","").strip()
    status=d.get("status","Active").strip()
    errors=[]
    if not name:  errors.append("Farm name is required.")
    if not crop:  errors.append("Crop type is required.")
    if not loc:   errors.append("Location is required.")
    if not pdate: errors.append("Planting date is required.")
    try:
        area_f=float(d.get("area","0"))
        if area_f<=0: raise ValueError
    except (ValueError,TypeError):
        errors.append("Area must be a positive number.")
    if errors:
        for e in errors: flash(e,"error")
        return redirect(url_for("farms"))
    conn=get_db()
    conn.execute(
        "INSERT INTO farms (user_id,farm_name,crop_type,location,area,planting_date,status) VALUES (?,?,?,?,?,?,?)",
        (uid,name,crop,loc,area_f,pdate,status))
    conn.commit(); conn.close()
    flash(f"🌱 Farm <strong>{name}</strong> added!", "success")
    return redirect(url_for("farms"))

@app.route("/farms/edit/<int:fid>", methods=["POST"])
@login_required
def edit_farm(fid):
    uid=session["user_id"]; conn=get_db()
    if not conn.execute("SELECT id FROM farms WHERE id=? AND user_id=?",(fid,uid)).fetchone():
        conn.close(); flash("Farm not found or access denied.","error")
        return redirect(url_for("farms"))
    d=request.form
    name=d.get("farm_name","").strip(); crop=d.get("crop_type","").strip()
    loc=d.get("location","").strip();   pdate=d.get("planting_date","").strip()
    status=d.get("status","Active").strip()
    try:    area_f=float(d.get("area","1"))
    except: area_f=1.0
    conn.execute(
        "UPDATE farms SET farm_name=?,crop_type=?,location=?,area=?,planting_date=?,status=? WHERE id=? AND user_id=?",
        (name,crop,loc,area_f,pdate,status,fid,uid))
    conn.commit(); conn.close()
    flash(f"✅ Farm <strong>{name}</strong> updated.", "success")
    return redirect(url_for("farms"))

@app.route("/farms/delete/<int:fid>", methods=["POST"])
@login_required
def delete_farm(fid):
    uid=session["user_id"]; conn=get_db()
    row=conn.execute("SELECT farm_name FROM farms WHERE id=? AND user_id=?",(fid,uid)).fetchone()
    if not row:
        conn.close(); flash("Farm not found or access denied.","error")
        return redirect(url_for("farms"))
    # Manually cascade — remove this farm's notes first, then the farm itself
    conn.execute("DELETE FROM crop_notes WHERE farm_id=? AND user_id=?",(fid,uid))
    conn.execute("DELETE FROM farms WHERE id=? AND user_id=?",(fid,uid))
    conn.commit(); conn.close()
    flash(f"🗑️ Farm <strong>{row['farm_name']}</strong> deleted.", "success")
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
    d    = request.get_json(force=True) or {}
    crop = d.get("crop_type","").strip()
    area = float(d.get("area", 1))
    label= d.get("label","").strip()
    if not crop or area <= 0:
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
def api_weather():
    return jsonify(get_weather(request.args.get("city","Chittagong")))

@app.route("/api/fertilizer", methods=["POST"])
def api_fertilizer():
    d=request.get_json(force=True) or {}
    return jsonify(calc_fertilizer(d.get("crop_type","rice"),float(d.get("area",1))))

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
    farm_id      = request.form.get("farm_id")
    planting_date= request.form.get("planting_date","")
    expected_days= int(request.form.get("expected_days", 90))
    growth_stage = request.form.get("growth_stage","Seedling")
    notes        = request.form.get("notes","")
    if not farm_id or not planting_date:
        flash("Farm and planting date are required.", "error")
        return redirect(url_for("growth_page"))
    conn = get_db()
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
    farm_id      = request.form.get("farm_id")
    date         = request.form.get("date","")
    water_liters = float(request.form.get("water_liters", 0) or 0)
    method       = request.form.get("method","Manual")
    duration_min = int(request.form.get("duration_min", 0) or 0)
    notes        = request.form.get("notes","")
    if not farm_id or not date:
        flash("Farm and date are required.", "error")
        return redirect(url_for("irrigation_page"))
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    conn.execute(
        f"INSERT INTO irrigation_log (farm_id,user_id,date,water_liters,method,duration_min,notes) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
        (farm_id, uid, date, water_liters, method, duration_min, notes)
    )
    conn.commit()
    conn.close()
    flash("✅ Irrigation logged.", "success")
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
                           profit=profit, today=today, farm_id_filter=farm_id_filter)

@app.route("/expenses/add", methods=["POST"])
@login_required
def add_expense():
    uid      = current_user()["id"]
    farm_id  = request.form.get("farm_id")
    etype    = request.form.get("type","expense")
    category = request.form.get("category","Other")
    amount   = float(request.form.get("amount", 0) or 0)
    desc     = request.form.get("description","")
    date     = request.form.get("date","")
    if not farm_id or not date or amount <= 0:
        flash("Farm, date and amount are required.", "error")
        return redirect(url_for("expenses_page"))
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    conn.execute(
        f"INSERT INTO expense_log (farm_id,user_id,type,category,amount,description,date) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
        (farm_id, uid, etype, category, amount, desc, date)
    )
    conn.commit()
    conn.close()
    flash("✅ Entry saved.", "success")
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
    """
    Scrape DAM (Department of Agricultural Marketing) daily price page.
    URL: https://www.dam.gov.bd/price-of-agricultural-commodity/daily-commodity-price
    Returns dict of crop→price, or None on failure.
    """
    try:
        import urllib.request, re
        url = "https://www.dam.gov.bd/price-of-agricultural-commodity/daily-commodity-price"
        req = urllib.request.Request(url, headers={"User-Agent": "GreenField-FarmApp/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # DAM page has a table: commodity | unit | price
        # Parse <tr> rows with Bengali/English crop names
        scraped = {}
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL|re.IGNORECASE)
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL|re.IGNORECASE)
            if len(cells) >= 3:
                name_raw = re.sub(r'<[^>]+>', '', cells[0]).strip()
                price_raw = re.sub(r'[^\d.]', '', re.sub(r'<[^>]+>', '', cells[-1]).strip())
                if price_raw and name_raw:
                    try:
                        scraped[name_raw] = float(price_raw)
                    except ValueError:
                        pass

        # Map DAM names → our crop keys
        name_map = {
            "চাল (ব্রি ধান)": "Rice (Boro)", "আউশ চাল": "Rice (Aman)",
            "গম": "Wheat", "আলু": "Potato", "টমেটো": "Tomato",
            "বেগুন": "Brinjal", "পেঁয়াজ": "Onion", "রসুন": "Garlic",
            "সরিষা": "Mustard", "পাট": "Jute", "ভুট্টা": "Maize",
            "মসুর ডাল": "Lentil (Masur)", "শুকনো মরিচ": "Chilli (dry)",
            "আদা": "Ginger", "হলুদ": "Turmeric",
            # English names on DAM
            "Rice": "Rice (Boro)", "Wheat": "Wheat", "Potato": "Potato",
            "Tomato": "Tomato", "Onion": "Onion", "Garlic": "Garlic",
            "Mustard": "Mustard", "Jute": "Jute", "Maize": "Maize",
            "Masur Dal": "Lentil (Masur)", "Dry Chilli": "Chilli (dry)",
            "Ginger": "Ginger", "Turmeric": "Turmeric",
        }

        result = {}
        for dam_name, our_key in name_map.items():
            if dam_name in scraped and our_key in _MARKET_FALLBACK:
                fb = _MARKET_FALLBACK[our_key]
                new_price = int(scraped[dam_name])
                old_price = fb["price"]
                if new_price > old_price * 1.03:   trend = "up"
                elif new_price < old_price * 0.97: trend = "down"
                else:                               trend = "stable"
                result[our_key] = {
                    "price": new_price,
                    "unit": fb["unit"],
                    "trend": trend,
                    "tip": fb["tip"],
                }

        return result if len(result) >= 5 else None   # Need at least 5 crops
    except Exception:
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


@app.route("/market")
@login_required
def market_page():
    prices, source, fetched_at = get_market_prices()
    updated_str = fetched_at.strftime("%d %b %Y, %I:%M %p") if fetched_at else datetime.now().strftime("%d %b %Y")
    return render_template("market.html", prices=prices,
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
        f"""SELECT g.*, f.farm_name FROM crop_growth g JOIN farms f ON g.farm_id=f.id
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
    total_income  = sum(r["amount"] for r in expenses if r["type"] == "income")
    total_expense = sum(r["amount"] for r in expenses if r["type"] == "expense")
    profit = total_income - total_expense

    user = current_user()
    conn.close()
    today = datetime.now().strftime("%d %B %Y")
    return render_template("report.html",
        user=user, farms=farms, growth=growth,
        irrigations=irrigations, expenses=expenses,
        total_income=total_income, total_expense=total_expense,
        profit=profit, today=today)


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


# ── Entry ─────────────────────────────────────────────────────────
# Always init DB (works for both gunicorn and dev server)
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") != "production"
    print(f"🌱  GreenField → http://127.0.0.1:{port}")
    app.run(debug=debug, host="0.0.0.0", port=port)
