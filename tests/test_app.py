import os, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DATABASE_URL", None)
import app as A
import farm_tasks

@pytest.fixture()
def client(tmp_path):
    A.DB_PATH = str(tmp_path / "t.db")
    A.init_db()
    A.app.config["TESTING"] = True
    A._throttle.clear() if hasattr(A, "_throttle") else None
    return A.app.test_client()

H = {"Origin": "http://localhost"}

def register(c, email="a@b.co", pw="Gf-test-pw-91"):
    return c.post("/register", data={"name": "T", "email": email, "password": pw, "confirm": pw}, headers=H, follow_redirects=False)

def test_healthz(client):
    assert client.get("/healthz").status_code == 200

def test_short_password_rejected(client):
    r = register(client, pw="short")
    assert r.status_code == 200 and b"8" in r.data

def test_register_login_flow(client):
    register(client)
    r = client.post("/login", data={"email": "a@b.co", "password": "Gf-test-pw-91"}, headers=H)
    assert r.status_code in (302, 303)
    assert client.get("/dashboard").status_code == 200

def test_login_lockout(client):
    register(client)
    client = A.app.test_client()          # fresh, logged-out browser
    codes = [client.post("/login", data={"email": "a@b.co", "password": "wrong"}, headers=H).status_code for _ in range(12)]
    assert 429 in codes

def test_cross_site_post_blocked(client):
    r = client.post("/login", data={"email": "a@b.co", "password": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403

def test_protected_pages_redirect(client):
    for u in ("/dashboard", "/market", "/expenses", "/api/today-tasks", "/account/export"):
        assert client.get(u).status_code in (302, 401), u

def test_cron_requires_token(client):
    assert client.post("/api/cron/alerts").status_code == 403

def test_security_headers(client):
    r = client.get("/healthz")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"

def test_tasks_and_export_when_logged_in(client):
    register(client)
    client.post("/login", data={"email": "a@b.co", "password": "Gf-test-pw-91"}, headers=H)
    r = client.get("/api/today-tasks")
    assert r.status_code == 200 and r.get_json()["tasks"] == []
    assert client.get("/account/export").get_json()["farms"] == []
    assert client.get("/market").status_code == 200
    assert client.get("/expenses").status_code == 200

def test_safe_next():
    assert A.safe_next("https://evil.com") != "https://evil.com"
    assert A.safe_next("//evil.com") != "//evil.com"

def test_irrigate_rule():
    f = {"id": 1, "farm_name": "F", "crop_type": "Tomato", "planting_date": "2026-10-01"}
    t = farm_tasks.build_tasks(f, None, "2026-10-01", None, None, today=__import__("datetime").date(2026, 11, 14))
    assert any(x["kind"] == "irrigate" for x in t)

def _login(c, email="s@b.co"):
    register(c, email=email)
    c2 = A.app.test_client()
    c2.post("/login", data={"email": email, "password": "Gf-test-pw-91"}, headers=H)
    return c2

def test_password_change_signs_out_other_devices(client):
    a = _login(client)
    b = A.app.test_client()
    b.post("/login", data={"email": "s@b.co", "password": "Gf-test-pw-91"}, headers=H)
    assert a.get("/dashboard").status_code == 200 and b.get("/dashboard").status_code == 200
    a.post("/profile", data={"action": "change_password", "current_password": "Gf-test-pw-91",
                             "new_password": "newpassword2", "confirm_password": "newpassword2"}, headers=H)
    assert a.get("/dashboard").status_code == 200           # the device that changed it stays in
    assert b.get("/dashboard").status_code == 302           # the other one is signed out

def test_record_market_price_and_trend(client):
    c = _login(client, "m@b.co")
    crop = list(A.get_market_prices()[0].keys())[0]
    for _ in range(1):
        r = c.post("/market/record", data={"crop": crop, "price": "50"}, headers=H)
        assert r.status_code == 302
    assert c.post("/market/record", data={"crop": crop, "price": "-5"}, headers=H).status_code == 302
    conn = A.get_db()
    rows = conn.execute("SELECT price, source FROM price_history WHERE crop=?", (crop,)).fetchall()
    assert len(rows) == 1 and rows[0]["source"] == "manual" and rows[0]["price"] == 50
    assert b"Your last price" in c.get("/market").data

def test_market_trend_needs_three_points():
    prices = {"Tomato": {"price": 40, "unit": "kg"}}
    v = A.market_view(prices, "sample", "en", None)
    assert v[0]["trend"] == "unknown" and v[0]["kind"] == "seasonal"

def test_report_renders(client):
    c = _login(client, "r@b.co")
    r = c.get("/report")
    assert r.status_code == 200 and b"Financial Summary" in r.data


def test_push_test_requires_login_and_config(client):
    assert client.post("/api/push/test", headers=H).status_code in (302, 401, 403)
    register(client)
    client.post("/login", data={"email": "a@b.co", "password": "Gf-test-pw-91"}, headers=H)
    A.PUSH_ENABLED = False
    assert client.post("/api/push/test", headers=H).status_code == 503


def test_crop_mismatch_warning():
    import datetime
    d = datetime.date(2026, 11, 14)
    # farm name says tea, crop says Rice -> a low-priority warning
    f = {"id": 1, "farm_name": "Tea Garden", "crop_type": "Rice", "planting_date": "2026-11-01"}
    kinds = [t["kind"] for t in farm_tasks.build_tasks(f, None, None, None, None, today=d)]
    assert "crop_mismatch" in kinds
    # matching name and crop -> no warning
    f2 = {"id": 2, "farm_name": "Rice Field North", "crop_type": "Rice", "planting_date": "2026-11-01"}
    assert "crop_mismatch" not in [t["kind"] for t in farm_tasks.build_tasks(f2, None, None, None, None, today=d)]
    # names with no crop word never warn
    f3 = {"id": 3, "farm_name": "Hurricane", "crop_type": "Wheat", "planting_date": "2026-11-01"}
    assert "crop_mismatch" not in [t["kind"] for t in farm_tasks.build_tasks(f3, None, None, None, None, today=d)]
    # alias: 'Corn Plot' with crop Maize is fine
    f4 = {"id": 4, "farm_name": "Corn Plot", "crop_type": "Maize", "planting_date": "2026-11-01"}
    assert "crop_mismatch" not in [t["kind"] for t in farm_tasks.build_tasks(f4, None, None, None, None, today=d)]


def test_market_placeholder_is_bangla(client):
    c = _login(client, "bn@b.co")
    c.get("/set-language/bn")
    html = c.get("/market").data.decode("utf-8")
    assert "আপনার দেখা দাম" in html and "Price you saw" not in html
    c.get("/set-language/en")
    assert "Price you saw" in c.get("/market").data.decode("utf-8")
