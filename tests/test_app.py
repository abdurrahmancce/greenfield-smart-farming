import os, sys, tempfile
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

def register(c, email="a@b.co", pw="password1"):
    return c.post("/register", data={"name": "T", "email": email, "password": pw, "confirm": pw}, headers=H, follow_redirects=False)

def test_healthz(client):
    assert client.get("/healthz").status_code == 200

def test_short_password_rejected(client):
    r = register(client, pw="short")
    assert r.status_code == 200 and b"8" in r.data

def test_register_login_flow(client):
    register(client)
    r = client.post("/login", data={"email": "a@b.co", "password": "password1"}, headers=H)
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
    client.post("/login", data={"email": "a@b.co", "password": "password1"}, headers=H)
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
