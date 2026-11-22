"""Seasons, forecast-vs-recorded check, 7-day sensor summary and the sensor CSV download."""
import os, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import app as appmod
import forecast as fc


# ---- pure functions -------------------------------------------------------------------------
@pytest.mark.parametrize("crop,date,key", [
    ("rice", "2026-04-10", "aus"), ("rice", "2026-07-20", "aman"), ("rice", "2026-12-15", "boro"),
    ("rice", "2026-02-01", "boro"), ("rice", "2026-10-31", "aman"), ("rice", "2026-11-01", "boro"),
    ("tomato", "2026-12-01", "rabi"), ("wheat", "2026-01-15", "rabi"),
    ("tomato", "2026-04-01", "kharif1"), ("tomato", "2026-08-01", "kharif2")])
def test_season_of(crop, date, key):
    assert fc.season_of(crop, date)["key"] == key


@pytest.mark.parametrize("bad", [None, "", "garbage", "2026-13-01", "2026/05/01", "2026-00-10"])
def test_season_of_bad_dates_are_none(bad):
    assert fc.season_of("rice", bad) is None


def test_actual_check_only_judges_after_harvest_date():
    assert fc.actual_check(0, 100000, "2026-01-01", "2026-06-01") is None
    assert fc.actual_check(50000, 0, "2026-01-01", "2026-06-01") is None
    assert fc.actual_check(50000, 100000, "2027-01-01", "2026-06-01")["verdict"] == "early"
    assert fc.actual_check(50000, 100000, "2026-01-01", "2026-06-01")["verdict"] == "below"
    assert fc.actual_check(95000, 100000, "2026-01-01", "2026-06-01")["verdict"] == "close"
    assert fc.actual_check(150000, 100000, "2026-01-01", "2026-06-01")["verdict"] == "above"
    assert fc.actual_check(95000, 100000, "", "2026-06-01")["verdict"] == "early"      # no harvest date -> never judged


def test_season_summary_groups_and_skips_unusable_farms():
    ok = lambda inc, cost, prof, area, known=True: {"ok": True, "area": area, "income_total": [0, inc, 0], "cost": cost,
                                                    "profit": [0, prof, 0], "costs_known": known}
    rows = [{"fc": ok(100, 40, 60, 2), "season": {"key": "aman", "en": "Aman", "bn": "আমন"}},
            {"fc": ok(50, 10, 40, 3, known=False), "season": {"key": "aman", "en": "Aman", "bn": "আমন"}},
            {"fc": ok(80, 20, 60, 1), "season": {"key": "boro", "en": "Boro", "bn": "বোরো"}},
            {"fc": {"ok": False}, "season": {"key": "boro", "en": "Boro", "bn": "বোরো"}},
            {"fc": ok(10, 1, 9, 1), "season": None}]
    s = fc.season_summary(rows)
    assert [x["en"] for x in s] == ["Aman", "Boro"]
    aman = s[0]
    assert (aman["n"], aman["acres"], aman["income"], aman["profit"], aman["partial"]) == (2, 5.0, 150, 100, True)
    assert aman["profit_per_acre"] == 20 and s[1]["n"] == 1 and s[1]["partial"] is False


# ---- pages / downloads ----------------------------------------------------------------------
@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DB_PATH", str(tmp_path / "t.db"))
    appmod._throttle_hits.clear()
    appmod.init_db()
    appmod.app.config["TESTING"] = True
    return appmod


def _stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def test_forecast_page_shows_seasons_and_recorded_check(env):
    c = env.app.test_client(); c.post("/demo")
    html = c.get("/forecast").get_data(as_text=True)
    assert "By season" in html and "Aman" in html                  # demo rice farm was planted in September
    conn = env.get_db()
    conn.execute("UPDATE crop_growth SET harvest_date='2000-01-01'"); conn.commit(); conn.close()
    assert "Forecast vs. recorded" in c.get("/forecast").get_data(as_text=True)   # wheat farm has recorded income
    with c.session_transaction() as sess:                           # the Bangla version renders too
        sess["lang"] = "bn"
    page = c.get("/forecast").get_data(as_text=True)
    assert "মৌসুম অনুযায়ী" in page and "আমন" in page
    assert "গত ৭ দিন" in c.get("/sensors").get_data(as_text=True)


def test_week_summary_and_csv_are_private_and_safe(env):
    a = env.app.test_client(); a.post("/demo")
    b = env.app.test_client(); b.post("/demo")
    conn = env.get_db()
    uid = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()["id"]
    dev = conn.execute("SELECT id FROM sensor_devices WHERE user_id=?", (uid,)).fetchone()["id"]
    conn.execute("UPDATE sensor_devices SET name=? WHERE id=?", ("=HYPERLINK(\"http://x\")", dev))
    conn.execute("DELETE FROM sensor_readings WHERE device_id=?", (dev,))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    farm = conn.execute("SELECT farm_id FROM sensor_devices WHERE id=?", (dev,)).fetchone()["farm_id"]
    for hrs, m in [(1, 20.0), (2, 40.0), (30, 60.0), (200, 10.0)]:           # the 200 h one is older than 7 days
        conn.execute("INSERT INTO sensor_readings (device_id,farm_id,user_id,moisture,temp,source,created_at) VALUES (?,?,?,?,?,?,?)",
                     (dev, farm, uid, m, 25.0, "device", _stamp(now - timedelta(hours=hrs))))
    conn.commit()
    w = env._week_stats(conn, dev, uid); conn.close()
    assert w["n"] == 3 and w["min"] == 20.0 and w["max"] == 60.0 and abs(w["avg"] - 40.0) < 1e-9
    assert len(w["days"]) == 7 and sum(1 for d in w["days"] if d["avg"] is not None) >= 1
    # page renders the summary
    assert "Last 7 days" in a.get("/sensors").get_data(as_text=True)
    # CSV: own data only (all 4 stored readings incl. the older one), formula text neutralised
    r = a.get("/sensors/export.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv" and "attachment" in r.headers["Content-Disposition"]
    text = r.get_data(as_text=True)
    assert "'=HYPERLINK" in text and "\n=HYPERLINK" not in text and ",=HYPERLINK" not in text
    assert len(text.strip().splitlines()) == 1 + 4                   # header + 4 readings
    other = b.get("/sensors/export.csv").get_data(as_text=True)
    assert "HYPERLINK" not in other
    # anonymous visitors are sent to the login page
    anon = env.app.test_client().get("/sensors/export.csv")
    assert anon.status_code in (301, 302, 303) and "login" in anon.headers["Location"]
