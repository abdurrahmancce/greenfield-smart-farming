import re
from conftest import A, H
import farm_tasks as ft


def _user(email="s@x.co", crop="Tomato"):
    c = A.app.test_client()
    c.post("/register", data={"name": "S", "email": email, "password": "password1", "confirm": "password1"}, headers=H)
    c.post("/farms/add", data={"farm_name": "F", "crop_type": crop, "location": "L", "planting_date": "2026-01-01", "area": "2"}, headers=H)
    cn = A.get_db(); fid = cn.execute("SELECT id FROM farms WHERE user_id=(SELECT id FROM users WHERE email=?)", (email,)).fetchone()["id"]; cn.close()
    return c, fid


def _add_sensor(c, fid, name="Probe"):
    r = c.post("/sensors/add", data={"farm_id": str(fid), "name": name}, headers=H)
    html = r.get_data(as_text=True)
    return r, re.search(r"gfs_[A-Za-z0-9_-]{20,}", html).group(0)


def _post(c, token, body, **kw):
    return c.post("/api/sensor/ingest", json=body, headers={"Authorization": f"Bearer {token}"}, **kw)


def _count(t):
    cn = A.get_db(); n = cn.execute(f"SELECT count(*) n FROM {t}").fetchone()["n"]; cn.close(); return n


def test_token_is_shown_once_and_only_its_hash_is_stored(client):
    c, fid = _user()
    r, tok = _add_sensor(c, fid)
    assert r.headers["Cache-Control"] == "no-store"
    cn = A.get_db(); row = cn.execute("SELECT token_hash, token_hint FROM sensor_devices").fetchone(); cn.close()
    assert tok not in row["token_hash"] and row["token_hash"] == A.hash_token(tok) and row["token_hint"] == tok[-4:]
    assert tok not in c.get("/sensors").get_data(as_text=True)          # never shown again


def test_ingest_saves_reading_and_validates(client):
    c, fid = _user()
    _, tok = _add_sensor(c, fid)
    anon = A.app.test_client()                                          # a device has no cookie and no login
    assert _post(anon, tok, {"moisture": 41.5, "temp": 28}).status_code == 201
    assert _count("sensor_readings") == 1
    for bad in ({"moisture": 101}, {"moisture": -1}, {"moisture": "wet"}, {"moisture": "nan"}, {"moisture": 5, "temp": 999}, {}, []):
        assert _post(anon, tok, bad).status_code == 400, bad
    assert _count("sensor_readings") == 1


def test_ingest_rejects_missing_wrong_and_revoked_tokens(client):
    c, fid = _user()
    _, tok = _add_sensor(c, fid)
    anon = A.app.test_client()
    assert anon.post("/api/sensor/ingest", json={"moisture": 5}).status_code == 401
    assert _post(anon, "gfs_" + "x" * 30, {"moisture": 5}).status_code == 401
    assert _post(anon, tok[:-1], {"moisture": 5}).status_code == 401
    assert anon.post("/api/sensor/ingest", json={"moisture": 5}, headers={"X-Device-Token": tok}).status_code == 201
    did = A.get_db().execute("SELECT id FROM sensor_devices").fetchone()["id"]
    c.post(f"/sensors/{did}/delete", headers=H)                         # revoke
    assert _post(anon, tok, {"moisture": 5}).status_code == 401 and _count("sensor_readings") == 0


def test_failed_token_guessing_is_throttled(client):
    anon = A.app.test_client()
    codes = [_post(anon, "gfs_" + "y" * 30, {"moisture": 5}).status_code for _ in range(35)]
    assert codes[0] == 401 and codes[-1] == 429


def test_reading_rate_limit_per_device(client):
    c, fid = _user()
    _, tok = _add_sensor(c, fid)
    anon = A.app.test_client()
    codes = [_post(anon, tok, {"moisture": 50}).status_code for _ in range(125)]
    assert codes.count(201) == 120 and codes[-1] == 429


def test_oversized_payload_refused(client):
    c, fid = _user()
    _, tok = _add_sensor(c, fid)
    assert _post(A.app.test_client(), tok, {"moisture": 5, "pad": "x" * 5000}).status_code == 413


def test_users_cannot_touch_each_others_sensors(client):
    a, fid = _user("a@x.co")
    b, bfid = _user("b@x.co")
    _, tok = _add_sensor(a, fid)
    did = A.get_db().execute("SELECT id FROM sensor_devices").fetchone()["id"]
    assert b.post(f"/sensors/{did}/delete", headers=H).status_code in (302, 303)
    assert _count("sensor_devices") == 1                                # still there
    b.post(f"/sensors/{did}/reading", data={"moisture": "10"}, headers=H)
    assert _count("sensor_readings") == 0
    b.post("/sensors/add", data={"farm_id": str(fid), "name": "steal"}, headers=H)   # Alice's farm
    assert _count("sensor_devices") == 1
    assert "…" + tok[-4:] not in b.get("/sensors").get_data(as_text=True)


def test_device_limit_and_login_required(client):
    c, fid = _user()
    for i in range(7):
        c.post("/sensors/add", data={"farm_id": str(fid), "name": f"s{i}"}, headers=H)
    assert _count("sensor_devices") == A.MAX_DEVICES_PER_USER
    anon = A.app.test_client()
    assert anon.get("/sensors").status_code in (302, 401)


def test_manual_reading_validates(client):
    c, fid = _user()
    _add_sensor(c, fid)
    did = A.get_db().execute("SELECT id FROM sensor_devices").fetchone()["id"]
    c.post(f"/sensors/{did}/reading", data={"moisture": "55", "temp": "27"}, headers=H)
    c.post(f"/sensors/{did}/reading", data={"moisture": "500"}, headers=H)
    c.post(f"/sensors/{did}/reading", data={"moisture": "40", "temp": "abc"}, headers=H)
    assert _count("sensor_readings") == 1


def test_dry_soil_becomes_a_push_worthy_task_and_wet_soil_hides_the_schedule_nudge():
    f = {"id": 1, "farm_name": "X", "crop_type": "Tomato", "planting_date": "2026-10-01"}
    def kinds(m, age=2, wx=None):
        return [t["kind"] for t in ft.build_tasks(f, None, "2026-11-01", None, wx, soil={"moisture": m, "age_hours": age})]
    assert kinds(20) == ["soil_dry"] and "soil_dry" in A.PUSH_KINDS
    assert "irrigate" in kinds(50) and kinds(70) == []
    assert kinds(90) == ["soil_wet"]
    assert "soil_dry" not in kinds(20, age=30)                          # stale reading is ignored
    rain = {"rain_mm": 9, "pop": .9, "wind_kmh": 5, "temp_max": 28, "humidity": 70}
    assert "soil_dry" not in kinds(20, wx=rain)                         # rain coming: normal hold-off advice wins


def test_sensor_data_is_deleted_with_the_account_and_farm(client):
    c, fid = _user()
    _, tok = _add_sensor(c, fid)
    _post(A.app.test_client(), tok, {"moisture": 30})
    c.post(f"/farms/delete/{fid}", headers=H)
    assert _count("sensor_readings") == 0 and _count("sensor_devices") == 0


def test_account_deletion_removes_sensor_and_forecast_data(client):
    c, fid = _user("d@x.co")
    _, tok = _add_sensor(c, fid)
    _post(A.app.test_client(), tok, {"moisture": 30})
    c.post("/forecast/save", data={"farm_id": str(fid), "price_per_kg": "40"}, headers=H)
    cn = A.get_db(); uid = cn.execute("SELECT id FROM users").fetchone()["id"]
    A.delete_user_data(cn, uid); cn.commit(); cn.close()
    assert _count("sensor_readings") == 0 and _count("sensor_devices") == 0 and _count("forecast_inputs") == 0


def test_export_has_sensor_data_but_never_the_token(client):
    c, fid = _user("e@x.co")
    _, tok = _add_sensor(c, fid)
    _post(A.app.test_client(), tok, {"moisture": 30})
    body = c.get("/account/export").get_data(as_text=True)
    assert '"sensor_readings"' in body and tok not in body and A.hash_token(tok) not in body
