"""Forecast routes (blueprint). Shared helpers are imported from app.py, which registers this blueprint after defining them."""
from flask import Blueprint

bp = Blueprint("forecast", __name__)

from app import (
    _MARKET_FALLBACK,
    _utcnow_str,
    datetime,
    farm_tasks,
    fc,
    flash,
    get_db,
    login_required,
    owned_farm_id,
    redirect,
    render_template,
    request,
    session,
    timedelta,
    timezone,
    to_float,
    url_for,
)

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
        today_bd = (datetime.now(timezone.utc) + timedelta(hours=6)).date().isoformat()
        rows.append({"farm": f, "ck": ck, "fc": res, "price_src": psrc, "price_note": pnote, "inp": inp,
                     "income_so_far": t.get("income", 0.0), "harvest": harvest,
                     "season": fc.season_of(ck, f.get("planting_date")),
                     "check": fc.actual_check(t.get("income", 0.0), (res.get("revenue") or [0, 0])[1] if res.get("ok") else 0, harvest, today_bd)})
    conn.close()
    return rows

@bp.route("/forecast")
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
    return render_template("forecast.html", rows=rows, tot=tot, seasons=fc.season_summary(rows), factor=int(fc.FARMGATE_FACTOR * 100),
                           spread=int(fc.SPREAD * 100), maund=int(fc.MAUND_KG))

@bp.route("/forecast/save", methods=["POST"])
@login_required
def forecast_save():
    uid = session["user_id"]
    conn = get_db()
    fid = owned_farm_id(conn, uid, request.form.get("farm_id"))
    if fid is None:
        conn.close(); flash("Farm not found.", "error"); return redirect(url_for("forecast.forecast_page"))
    def num(name, hi):
        raw = (request.form.get(name) or "").strip()
        return (to_float(raw, 0, hi), bool(raw))
    y, y_given = num("yield_per_acre", 100000)
    p, p_given = num("price_per_kg", 100000)
    c, c_given = num("remaining_cost", 1e9)
    if (y_given and y is None) or (p_given and p is None) or (c_given and c is None):
        conn.close(); flash("Please enter valid positive numbers.", "error"); return redirect(url_for("forecast.forecast_page"))
    # empty field = "use the default"; store NULL
    conn.execute("DELETE FROM forecast_inputs WHERE user_id=? AND farm_id=?", (uid, fid))
    if y or p or c_given:          # "0" is a real answer for costs still to come ("nothing left to spend")
        conn.execute("INSERT INTO forecast_inputs (user_id, farm_id, yield_per_acre, price_per_kg, remaining_cost, updated_at) VALUES (?,?,?,?,?,?)",
                     (uid, fid, y or None, p or None, c if c_given else None, _utcnow_str()))
    conn.commit(); conn.close()
    flash("Forecast inputs saved.", "success")
    return redirect(url_for("forecast.forecast_page") + f"#farm{fid}")
