"""
GreenField Smart Farming App — app.py v6
Flask 3 | SQLite (local) / PostgreSQL (production) | Auth | Full CRUD | Weather API
"""
import os, sqlite3, json, hashlib, secrets
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (Flask, render_template, request, redirect,
                   url_for, jsonify, flash, session)

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
app.secret_key = os.environ.get("SECRET_KEY", "gf_smartfarm_dev_secret_2024")

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
    """)
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
        "SELECT id, name, email, role, created_at FROM users WHERE id=?",
        (session["user_id"],)
    ).fetchone()
    conn.close()
    return user

# Inject user into every template automatically
@app.context_processor
def inject_user():
    return {"current_user": current_user()}

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
            session.clear()
            session["user_id"]   = user["id"]
            session["user_name"] = user["name"]
            flash(f"👋 Welcome back, <strong>{user['name']}</strong>!", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid email or password. Please try again.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
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
    farms_data =conn.execute("SELECT farm_name,crop_type,area FROM farms WHERE user_id=?",(uid,)).fetchall()
    status_data=conn.execute("SELECT status,COUNT(*) as cnt FROM farms WHERE user_id=? GROUP BY status",(uid,)).fetchall()
    conn.close()
    labels=[f["farm_name"] for f in farms_data]
    areas =[f["area"]      for f in farms_data]
    crops =[f["crop_type"] for f in farms_data]
    return render_template("analytics.html",
        labels=labels,areas=areas,crops=crops,
        months=["Jan","Feb","Mar","Apr","May","Jun","Jul"],
        water=[280,320,410,390,480,520,460],
        harvest=[15,18,22,19,28,31,25],
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

# ── Entry ─────────────────────────────────────────────────────────
# Always init DB (works for both gunicorn and dev server)
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") != "production"
    print(f"🌱  GreenField → http://127.0.0.1:{port}")
    app.run(debug=debug, host="0.0.0.0", port=port)
