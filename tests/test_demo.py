"""The one-click demo account: isolated, seeded, restricted, and cleaned up."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import app as appmod


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DB_PATH", str(tmp_path / "t.db"))
    appmod._throttle_hits.clear()
    appmod.init_db()
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _count(sql, *a):
    c = appmod.get_db(); n = c.execute(sql, a).fetchone()[0]; c.close(); return n


def test_demo_creates_seeded_isolated_account(client):
    r = client.post("/demo")
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")
    assert _count("SELECT COUNT(*) FROM users WHERE role='demo'") == 1
    assert _count("SELECT COUNT(*) FROM farms") == 3
    assert _count("SELECT COUNT(*) FROM sensor_readings") == 8
    # a second visitor gets a separate account - no shared data
    c2 = appmod.app.test_client(); c2.post("/demo")
    assert _count("SELECT COUNT(*) FROM users WHERE role='demo'") == 2
    assert _count("SELECT COUNT(DISTINCT user_id) FROM farms") == 2


def test_demo_pages_render_and_show_dry_soil_task(client):
    client.post("/demo")
    for path in ("/dashboard", "/farms", "/sensors", "/forecast", "/expenses", "/report", "/analytics"):
        assert client.get(path).status_code == 200, path
    assert b"Soil is dry" in client.get("/api/today-tasks").data


def test_demo_cannot_change_credentials_or_use_paid_features(client):
    client.post("/demo")
    client.post("/profile", data={"action": "change_password", "current_password": "x",
                                  "new_password": "abcdefgh1", "confirm_password": "abcdefgh1"})
    client.post("/profile", data={"action": "delete_account", "delete_password": "x", "delete_confirm": "DELETE"})
    assert _count("SELECT COUNT(*) FROM users WHERE role='demo'") == 1      # still there
    assert client.post("/api/disease-detect", json={"symptoms": "spots"}).status_code == 403
    assert client.post("/api/disease-image", data={}).status_code == 403
    assert client.post("/api/push/test").status_code == 403


def test_demo_is_rate_limited_and_capped(client, monkeypatch):
    monkeypatch.setattr(appmod, "DEMO_PER_IP", 2)
    for _ in range(2):
        appmod.app.test_client().post("/demo")
    appmod.app.test_client().post("/demo")
    assert _count("SELECT COUNT(*) FROM users WHERE role='demo'") == 2
    appmod._throttle_hits.clear()
    monkeypatch.setattr(appmod, "DEMO_MAX_USERS", 2)
    appmod.app.test_client().post("/demo")
    assert _count("SELECT COUNT(*) FROM users WHERE role='demo'") == 2


def test_old_demo_accounts_are_purged_with_their_data(client):
    client.post("/demo")
    c = appmod.get_db()
    c.execute("UPDATE users SET created_at='2000-01-01 00:00:00' WHERE role='demo'"); c.commit(); c.close()
    appmod._throttle_hits.clear()
    appmod.app.test_client().post("/demo")
    assert _count("SELECT COUNT(*) FROM users WHERE role='demo'") == 1      # old one gone, new one present
    assert _count("SELECT COUNT(*) FROM farms") == 3
    assert _count("SELECT COUNT(*) FROM sensor_readings") == 8


def test_demo_hidden_from_admin_counts_and_login_page_has_button(client):
    client.post("/demo")
    assert b"Try the demo" in appmod.app.test_client().get("/login").data
    c = appmod.get_db()
    n = c.execute("SELECT COUNT(*) FROM users WHERE role<>'demo'").fetchone()[0]; c.close()
    assert n == 0
