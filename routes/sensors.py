"""Sensors routes (blueprint). Shared helpers are imported from app.py, which registers this blueprint after defining them."""
from flask import Blueprint

bp = Blueprint("sensors", __name__)

from app import (
    APP_BASE_URL,
    Response,
    _age_hours,
    _bd_label,
    _utcnow_str,
    client_ip,
    clip,
    datetime,
    exports,
    farm_tasks,
    flash,
    get_db,
    hash_token,
    jsonify,
    login_required,
    make_response,
    owned_farm_id,
    redirect,
    render_template,
    request,
    secrets,
    session,
    throttle_blocked,
    throttle_hit,
    timedelta,
    timezone,
    to_float,
    to_int,
    url_for,
)

MAX_DEVICES_PER_USER = 5
SENSOR_KEEP_DAYS = 30

def _sensor_base_url():
    return (APP_BASE_URL or request.host_url).rstrip("/")

def _week_stats(conn, device_id, uid):
    """Average / lowest / highest soil moisture over the last 7 Bangladesh days, plus one average per day.
    One query per sensor (no per-day loop over rows). Returns None when there are no readings in that window."""
    bd_today = (datetime.now(timezone.utc) + timedelta(hours=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    days = []                                   # oldest -> newest; each is [start_utc, end_utc, label]
    for i in range(6, -1, -1):
        st = bd_today - timedelta(days=i)
        days.append([(st - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
                     (st - timedelta(hours=6) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"), st.strftime("%m-%d")])
    cols, args = [], []
    for k, (a_, b_, _l) in enumerate(days):
        cols.append(f"SUM(CASE WHEN created_at>=? AND created_at<? THEN moisture END) AS s{k}, "
                    f"SUM(CASE WHEN created_at>=? AND created_at<? THEN 1 ELSE 0 END) AS c{k}")
        args += [a_, b_, a_, b_]
    row = conn.execute("SELECT AVG(moisture) AS av, MIN(moisture) AS lo, MAX(moisture) AS hi, COUNT(*) AS n, " + ", ".join(cols) +
                       " FROM sensor_readings WHERE device_id=? AND user_id=? AND created_at>=?",
                       tuple(args) + (device_id, uid, days[0][0])).fetchone()
    if not row or not row["n"]:
        return None
    per_day = []
    for k, (_a, _b, label) in enumerate(days):
        c = row[f"c{k}"] or 0
        per_day.append({"label": label, "avg": (float(row[f"s{k}"]) / c) if c else None})
    return {"avg": float(row["av"]), "min": float(row["lo"]), "max": float(row["hi"]), "n": int(row["n"]), "days": per_day}

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
        d["week"] = _week_stats(conn, d["id"], uid)
        d["token_hint"] = d.get("token_hint") or ""
        devices.append(d)
    return {"farms": farms, "devices": devices, "new_token": new_token, "new_device": new_device,
            "base_url": _sensor_base_url(), "dry": farm_tasks.SOIL_DRY_BELOW, "wet": farm_tasks.SOIL_WET_ABOVE,
            "fresh_h": farm_tasks.SOIL_FRESH_HOURS, "max_devices": MAX_DEVICES_PER_USER}

@bp.route("/sensors")
@login_required
def sensors_page():
    conn = get_db()
    ctx = _sensors_context(conn, session["user_id"])
    conn.close()
    return render_template("sensors.html", **ctx)

@bp.route("/sensors/export.csv")
@login_required
def sensors_export():
    """The user's own soil readings (newest 20,000, i.e. at most the 30 days we keep) as a spreadsheet-safe CSV."""
    uid = session["user_id"]
    if throttle_blocked("dl:%s" % uid, 20, 600):
        return Response("Too many downloads, please wait a few minutes.", 429)
    throttle_hit("dl:%s" % uid)
    conn = get_db()
    rows = conn.execute("""SELECT r.created_at, r.moisture, r.temp, r.source, d.name AS dev, f.farm_name
                           FROM sensor_readings r JOIN sensor_devices d ON d.id=r.device_id JOIN farms f ON f.id=r.farm_id
                           WHERE r.user_id=? ORDER BY r.id DESC LIMIT 20000""", (uid,)).fetchall()
    conn.close()
    def bd(ts):
        try:
            return (datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S") + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return ""
    body = exports.make_csv(["Time (Bangladesh, UTC+6)", "Time (UTC)", "Sensor", "Farm", "Moisture (%)", "Temperature (C)", "Source"],
                            [[bd(r["created_at"]), str(r["created_at"])[:16], r["dev"], r["farm_name"], r["moisture"], r["temp"], r["source"]]
                             for r in reversed(rows)])
    resp = Response(body, mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="greenfield-soil-readings-{datetime.now(timezone.utc).strftime("%Y-%m-%d")}.csv"'
    resp.headers["Cache-Control"] = "no-store"
    return resp

@bp.route("/sensors/add", methods=["POST"])
@login_required
def sensors_add():
    uid = session["user_id"]
    conn = get_db()
    fid = owned_farm_id(conn, uid, request.form.get("farm_id"))
    name = clip(request.form.get("name"), 40) or "Soil sensor"
    n = conn.execute("SELECT COUNT(*) AS c FROM sensor_devices WHERE user_id=?", (uid,)).fetchone()["c"]
    if fid is None:
        conn.close(); flash("Choose one of your farms.", "error"); return redirect(url_for("sensors.sensors_page"))
    if n >= MAX_DEVICES_PER_USER:
        conn.close(); flash(f"You can add up to {MAX_DEVICES_PER_USER} sensors.", "error"); return redirect(url_for("sensors.sensors_page"))
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

@bp.route("/sensors/<int:did>/delete", methods=["POST"])
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
    return redirect(url_for("sensors.sensors_page"))

@bp.route("/sensors/<int:did>/reading", methods=["POST"])
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
        return redirect(url_for("sensors.sensors_page"))
    conn.execute("INSERT INTO sensor_readings (device_id, farm_id, user_id, moisture, temp, source, created_at) VALUES (?,?,?,?,?,?,?)",
                 (did, d["farm_id"], uid, moist, temp, "manual", _utcnow_str()))
    conn.execute("UPDATE sensor_devices SET last_seen=? WHERE id=?", (_utcnow_str(), did))
    conn.commit(); conn.close()
    flash("Reading saved.", "success")
    return redirect(url_for("sensors.sensors_page"))

@bp.route("/api/sensor/ingest", methods=["POST"])
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
