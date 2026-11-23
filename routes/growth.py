"""Growth routes (blueprint). Shared helpers are imported from app.py, which registers this blueprint after defining them."""
from flask import Blueprint

bp = Blueprint("growth", __name__)

from app import (
    USE_POSTGRES,
    clip,
    current_user,
    datetime,
    flash,
    get_db,
    login_required,
    notes,
    owned_farm_id,
    redirect,
    render_template,
    request,
    timedelta,
    to_int,
    url_for,
    valid_date,
)

# ══════════════════════════════════════════════════════════════════
#  CROP GROWTH TRACKER
# ══════════════════════════════════════════════════════════════════
@bp.route("/growth")
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

@bp.route("/growth/add", methods=["POST"])
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
        return redirect(url_for("growth.growth_page"))
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
    return redirect(url_for("growth.growth_page"))

@bp.route("/growth/update/<int:gid>", methods=["POST"])
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
    return redirect(url_for("growth.growth_page"))

@bp.route("/growth/delete/<int:gid>", methods=["POST"])
@login_required
def delete_growth(gid):
    uid = current_user()["id"]
    conn = get_db()
    ph = "%s" if USE_POSTGRES else "?"
    conn.execute(f"DELETE FROM crop_growth WHERE id={ph} AND user_id={ph}", (gid, uid))
    conn.commit()
    conn.close()
    flash("Growth record deleted.", "success")
    return redirect(url_for("growth.growth_page"))
