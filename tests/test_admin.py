from conftest import A, H


def _u(email):
    c = A.app.test_client()
    c.post("/register", data={"name": "N", "email": email, "password": "Gf-test-pw-91", "confirm": "Gf-test-pw-91"}, headers=H)
    return c


def test_admin_only_for_listed_email(client, monkeypatch):
    monkeypatch.setattr(A, "ADMIN_EMAILS", {"boss@x.co"})
    boss, other = _u("boss@x.co"), _u("other@x.co")
    other.post("/farms/add", data={"farm_name": "PRIVATE-FARM", "crop_type": "Rice", "location": "L", "planting_date": "2026-01-01", "area": "3"}, headers=H)
    assert other.get("/admin").status_code == 404
    assert A.app.test_client().get("/admin").status_code in (302, 401)
    r = boss.get("/admin")
    assert r.status_code == 200 and b"Users" in r.data
    assert b"PRIVATE-FARM" not in r.data and b"other@x.co" not in r.data       # aggregates only
    assert b"/admin" in boss.get("/dashboard").data and b'href="/admin"' not in other.get("/dashboard").data


def test_admin_disabled_by_default(client, monkeypatch):
    monkeypatch.setattr(A, "ADMIN_EMAILS", set())
    assert _u("anyone@x.co").get("/admin").status_code == 404
