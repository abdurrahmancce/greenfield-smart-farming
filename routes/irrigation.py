"""Irrigation routes (blueprint). Shared helpers are imported from app.py, which registers this blueprint after defining them."""
from flask import Blueprint

bp = Blueprint("irrigation", __name__)

from app import (
    OPENWEATHER_KEY,
    USE_POSTGRES,
    current_user,
    datetime,
    flash,
    get_db,
    jsonify,
    login_required,
    redirect,
    render_template,
    request,
    save_irrigation_entry,
    url_for,
)

# ══════════════════════════════════════════════════════════════════
#  IRRIGATION LOG
# ══════════════════════════════════════════════════════════════════
@bp.route("/irrigation")
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

@bp.route("/irrigation/add", methods=["POST"])
@login_required
def add_irrigation():
    uid = current_user()["id"]
    conn = get_db()
    ok, msg = save_irrigation_entry(conn, uid, request.form)
    conn.close()
    if request.headers.get("X-GF-Fetch"):
        return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("irrigation.irrigation_page"))

@bp.route("/irrigation/delete/<int:iid>", methods=["POST"])
@login_required
def delete_irrigation(iid):
    uid = current_user()["id"]
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    conn.execute(f"DELETE FROM irrigation_log WHERE id={ph} AND user_id={ph}", (iid, uid))
    conn.commit()
    conn.close()
    flash("Log deleted.", "success")
    return redirect(url_for("irrigation.irrigation_page"))
