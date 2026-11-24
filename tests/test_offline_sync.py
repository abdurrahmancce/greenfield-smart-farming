from conftest import A, H


def _user(email="o@x.co"):
    c = A.app.test_client()
    c.post("/register", data={"name": "O", "email": email, "password": "Gf-test-pw-91", "confirm": "Gf-test-pw-91"}, headers=H)
    c.post("/farms/add", data={"farm_name": "F", "crop_type": "Rice", "location": "L", "planting_date": "2026-01-01", "area": "2"}, headers=H)
    cn = A.get_db(); fid = cn.execute("SELECT id FROM farms WHERE user_id=(SELECT id FROM users WHERE email=?)", (email,)).fetchone()["id"]; cn.close()
    return c, fid


def _count(t):
    cn = A.get_db(); n = cn.execute(f"SELECT count(*) n FROM {t}").fetchone()["n"]; cn.close(); return n


def test_sync_saves_and_is_idempotent(client):
    c, fid = _user()
    e = [{"cid": "abc12345-1", "kind": "expense", "f": {"farm_id": str(fid), "amount": "50", "date": "2026-02-01", "type": "expense", "category": "Seeds"}},
         {"cid": "abc12345-2", "kind": "irrigation", "f": {"farm_id": str(fid), "date": "2026-02-01", "water_liters": "100"}}]
    r = c.post("/api/offline/sync", json={"entries": e}, headers=H).get_json()
    assert sorted(r["done"]) == ["abc12345-1", "abc12345-2"] and not r["rejected"]
    r = c.post("/api/offline/sync", json={"entries": e}, headers=H).get_json()      # phone retries: no duplicates
    assert len(r["done"]) == 2
    assert _count("expense_log") == 1 and _count("irrigation_log") == 1


def test_sync_rejects_foreign_farm_bad_data_and_bad_ids(client):
    a, fid = _user("a@x.co")
    b, _ = _user("b@x.co")
    r = b.post("/api/offline/sync", json={"entries": [
        {"cid": "bbbbbbbb-1", "kind": "expense", "f": {"farm_id": str(fid), "amount": "5", "date": "2026-02-01"}},       # Alice's farm
        {"cid": "bbbbbbbb-2", "kind": "expense", "f": {"farm_id": "1", "amount": "nan", "date": "2026-02-01"}},
        {"cid": "x", "kind": "expense", "f": {"farm_id": "1", "amount": "5", "date": "2026-02-01"}},                       # id too short
        {"cid": "bbbbbbbb-4", "kind": "evil", "f": {}},
        "garbage", {"cid": "bbbbbbbb-5", "kind": "expense", "f": "notadict"}]}, headers=H).get_json()
    assert r["done"] == [] and len(r["rejected"]) >= 4
    assert _count("expense_log") == 0


def test_sync_needs_login_limits_and_shape(client):
    anon = A.app.test_client()
    assert anon.post("/api/offline/sync", json={"entries": []}, headers={**H, "X-GF-Fetch": "1"}).status_code == 401
    assert anon.post("/api/offline/sync", json={"entries": []}, headers=H).status_code in (302, 401)
    c, _ = _user()
    assert c.post("/api/offline/sync", json={"entries": [{}] * 51}, headers=H).status_code == 400
    assert c.post("/api/offline/sync", data="not json", headers=H).status_code == 400


def test_form_post_with_fetch_header_returns_json_and_dedupes(client):
    c, fid = _user()
    d = {"farm_id": str(fid), "amount": "9", "date": "2026-02-01", "cid": "cid-abcdef-1"}
    h = {**H, "X-GF-Fetch": "1"}
    assert c.post("/expenses/add", data=d, headers=h).get_json()["ok"] is True
    assert c.post("/expenses/add", data=d, headers=h).get_json()["ok"] is True      # retry after a timeout
    assert _count("expense_log") == 1
    r = c.post("/expenses/add", data={**d, "amount": "-1", "cid": "cid-abcdef-2"}, headers=h)
    assert r.status_code == 400 and r.get_json()["ok"] is False


def test_account_delete_removes_sync_ids(client):
    c, fid = _user()
    c.post("/api/offline/sync", json={"entries": [{"cid": "zzzzzzzz-1", "kind": "expense", "f": {"farm_id": str(fid), "amount": "5", "date": "2026-02-01"}}]}, headers=H)
    c.post("/profile", data={"action": "delete_account", "delete_password": "Gf-test-pw-91", "delete_confirm": "DELETE"}, headers=H)
    assert _count("offline_sync") == 0
