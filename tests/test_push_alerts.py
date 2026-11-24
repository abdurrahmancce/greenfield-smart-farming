from datetime import date, timedelta
from conftest import A, H
import farm_tasks


def test_harvest_soon_and_irrigate_tasks_exist():
    farm = {"id": 1, "farm_name": "F", "crop_type": "Rice", "planting_date": (date.today() - timedelta(days=110)).isoformat()}
    kinds = {t["kind"] for t in farm_tasks.build_tasks(farm, {"expected_days": 118, "growth_stage": "x"}, (date.today() - timedelta(days=20)).isoformat(), None, None)}
    assert "harvest_soon" in kinds and "irrigate" in kinds
    assert {"harvest_soon", "irrigate", "skip_irrigation", "harvest_now"} <= A.PUSH_KINDS


def test_cron_sends_harvest_alert_once_per_window(client, monkeypatch):
    c = A.app.test_client()
    c.post("/register", data={"name": "H", "email": "h@x.co", "password": "Gf-test-pw-91", "confirm": "Gf-test-pw-91"}, headers=H)
    planted = (date.today() - timedelta(days=110)).isoformat()
    c.post("/farms/add", data={"farm_name": "F", "crop_type": "Rice", "location": "L", "planting_date": planted, "area": "1"}, headers=H)
    cn = A.get_db()
    uid = cn.execute("SELECT id FROM users").fetchone()["id"]; fid = cn.execute("SELECT id FROM farms").fetchone()["id"]
    cn.execute("INSERT INTO crop_growth (farm_id,user_id,planting_date,expected_days,growth_stage,harvest_date) VALUES (?,?,?,?,?,?)",
               (fid, uid, planted, 118, "Flowering", (date.today() + timedelta(days=8)).isoformat()))
    cn.execute("INSERT INTO push_subs (user_id,endpoint,p256dh,auth,lang) VALUES (?,?,?,?,?)", (uid, "https://fcm.googleapis.com/fcm/send/x", "a", "b", "en"))
    cn.commit(); cn.close()
    sent = []
    monkeypatch.setattr(A, "send_push", lambda s, p: sent.append(p["tag"]) or "ok")
    monkeypatch.setattr(A, "PUSH_ENABLED", True); monkeypatch.setattr(A, "CRON_TOKEN", "t" * 40)
    h = {"X-Cron-Token": "t" * 40}
    A.app.test_client().post("/api/cron/alerts", headers=h)
    assert any(t.endswith(":harvest_soon") for t in sent)
    n = len(sent)
    A.app.test_client().post("/api/cron/alerts", headers=h)           # same day / window: nothing new
    assert len(sent) == n
