"""Regression tests for the security post-mortem (v25). Each test = one attack that used to work."""
import io
import pytest
from conftest import A, H


def _mk(client_factory, email, name="U"):
    c = A.app.test_client()
    c.post("/register", data={"name": name, "email": email, "password": "Gf-test-pw-91", "confirm": "Gf-test-pw-91"}, headers=H)
    return c


def _farm(c, name="FARM-A"):
    c.post("/farms/add", data={"farm_name": name, "crop_type": "Rice", "location": "L", "planting_date": "2026-01-01", "area": "2"}, headers=H)
    cn = A.get_db(); fid = cn.execute("SELECT id FROM farms WHERE farm_name=?", (name,)).fetchone()["id"]; cn.close()
    return fid


def test_cannot_log_into_another_users_farm(client):
    a = _mk(client, "a@x.co"); b = _mk(client, "b@x.co")
    fid = _farm(a, "SECRET-NAME")
    b.post("/expenses/add", data={"farm_id": fid, "amount": "5", "date": "2026-02-01"}, headers=H)
    b.post("/growth/add", data={"farm_id": fid, "planting_date": "2026-02-01"}, headers=H)
    b.post("/irrigation/add", data={"farm_id": fid, "date": "2026-02-01", "water_liters": "3"}, headers=H)
    cn = A.get_db()
    for t in ("expense_log", "crop_growth", "irrigation_log"):
        assert cn.execute(f"SELECT count(*) n FROM {t}").fetchone()["n"] == 0, t
    cn.close()
    assert b"SECRET-NAME" not in b.get("/expenses").data


@pytest.mark.parametrize("path,data", [
    ("/farms/add", {"farm_name": "n", "crop_type": "c", "location": "l", "planting_date": "2026-01-01", "area": "nan"}),
    ("/farms/add", {"farm_name": "n", "crop_type": "c", "location": "l", "planting_date": "2026-01-01", "area": "inf"}),
    ("/growth/add", {"farm_id": "1", "planting_date": "xx"}),
    ("/growth/add", {"farm_id": "1", "planting_date": "2026-01-01", "expected_days": "abc"}),
    ("/expenses/add", {"farm_id": "1", "date": "2026-01-01", "amount": "1e999"}),
    ("/expenses/add", {"farm_id": "abc", "date": "2026-01-01", "amount": "5"}),
    ("/irrigation/add", {"farm_id": "1", "date": "2026-01-01", "water_liters": "abc"}),
])
def test_bad_numbers_never_crash(client, path, data):
    c = _mk(client, "n@x.co"); _farm(c)
    assert c.post(path, data=data, headers=H).status_code in (302, 303)


def test_text_is_length_limited(client):
    c = _mk(client, "l@x.co"); fid = _farm(c)
    c.post("/expenses/add", data={"farm_id": fid, "amount": "5", "date": "2026-01-01", "description": "A" * 100000}, headers=H)
    cn = A.get_db(); n = cn.execute("SELECT max(length(description)) m FROM expense_log").fetchone()["m"]; cn.close()
    assert n <= 300


def test_push_endpoint_allowlist(client, monkeypatch):
    monkeypatch.setattr(A, "PUSH_ENABLED", True)
    c = _mk(client, "p@x.co")
    keys = {"p256dh": "a", "auth": "b"}
    for bad in ("https://169.254.169.254/x", "https://evil.test/x", "http://fcm.googleapis.com/x",
                "https://fcm.googleapis.com.evil.test/x", "https://user@fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x"):
        assert c.post("/api/push/subscribe", json={"endpoint": bad, "keys": keys}, headers=H).status_code == 400, bad
    for ok in ("https://fcm.googleapis.com/fcm/send/abc", "https://updates.push.services.mozilla.com/wpush/v2/abc",
               "https://web.push.apple.com/abc", "https://wns2-par02p.notify.windows.com/w/?token=abc"):
        assert c.post("/api/push/subscribe", json={"endpoint": ok, "keys": keys}, headers=H).status_code == 200, ok
    for i in range(10):
        c.post("/api/push/subscribe", json={"endpoint": f"https://fcm.googleapis.com/fcm/send/{i}", "keys": keys}, headers=H)
    cn = A.get_db(); n = cn.execute("SELECT count(*) n FROM push_subs").fetchone()["n"]; cn.close()
    assert n <= 5


def test_weather_and_fertilizer_need_login(client):
    anon = A.app.test_client()
    assert anon.get("/api/weather").status_code in (302, 401)
    assert anon.post("/api/fertilizer", json={"area": 1}, headers=H).status_code in (302, 401)


def test_google_login_rules(client, monkeypatch):
    victim_pre = _mk(client, "v@gmail.com")                      # attacker pre-registers the victim's address
    A.GOOGLE_OAUTH_ENABLED = True

    def with_info(info):
        class G:
            def authorize_access_token(self): return {"userinfo": info}
        monkeypatch.setattr(A, "google", G(), raising=False)
        c = A.app.test_client(); c.get("/login/google/callback"); return c
    # unverified email -> refused
    assert with_info({"sub": "s1", "email": "v@gmail.com", "email_verified": False}).get("/dashboard").status_code == 302
    # verified -> ok, and the attacker's password stops working
    assert with_info({"sub": "s1", "email": "v@gmail.com", "email_verified": True}).get("/dashboard").status_code == 200
    r = A.app.test_client().post("/login", data={"email": "v@gmail.com", "password": "Gf-test-pw-91"}, headers=H)
    assert r.status_code == 200                                  # login page again, not a redirect
    assert victim_pre.get("/dashboard").status_code == 302       # old session was signed out
    # a different Google account with the same e-mail cannot take it over
    assert with_info({"sub": "OTHER", "email": "v@gmail.com", "email_verified": True}).get("/dashboard").status_code == 302
    A.GOOGLE_OAUTH_ENABLED = False


def test_account_delete_removes_everything(client):
    c = _mk(client, "d@x.co"); fid = _farm(c)
    c.post("/expenses/add", data={"farm_id": fid, "amount": "5", "date": "2026-01-01"}, headers=H)
    c.post("/growth/add", data={"farm_id": fid, "planting_date": "2026-01-01"}, headers=H)
    c.post("/irrigation/add", data={"farm_id": fid, "date": "2026-01-01", "water_liters": "3"}, headers=H)
    c.post("/profile", data={"action": "delete_account", "delete_password": "Gf-test-pw-91", "delete_confirm": "DELETE"}, headers=H)
    cn = A.get_db()
    for t in ("users", "farms", "expense_log", "crop_growth", "irrigation_log", "push_subs"):
        assert cn.execute(f"SELECT count(*) n FROM {t}").fetchone()["n"] == 0, t
    cn.close()


def test_deleting_a_farm_removes_its_records(client):
    c = _mk(client, "f@x.co"); fid = _farm(c)
    c.post("/expenses/add", data={"farm_id": fid, "amount": "5", "date": "2026-01-01"}, headers=H)
    c.post(f"/farms/delete/{fid}", headers=H)
    cn = A.get_db(); assert cn.execute("SELECT count(*) n FROM expense_log").fetchone()["n"] == 0; cn.close()


def test_photo_must_be_a_real_image(client):
    c = _mk(client, "ph@x.co")
    c.post("/profile", data={"action": "upload_photo", "profile_photo": (io.BytesIO(b"<script>alert(1)</script>"), "x.png", "image/png")},
           headers=H, content_type="multipart/form-data")
    cn = A.get_db(); assert (cn.execute("SELECT avatar_photo FROM users").fetchone()["avatar_photo"] or "") == ""; cn.close()
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 50
    c.post("/profile", data={"action": "upload_photo", "profile_photo": (io.BytesIO(png), "x.png", "image/png")},
           headers=H, content_type="multipart/form-data")
    cn = A.get_db(); assert cn.execute("SELECT avatar_photo FROM users").fetchone()["avatar_photo"].startswith("data:image/png"); cn.close()


def test_security_headers_and_cron_token_edge(client):
    h = client.get("/login").headers
    assert "frame-ancestors 'self'" in h["Content-Security-Policy"]
    A.CRON_TOKEN = "x" * 40; A.PUSH_ENABLED = True
    assert client.post("/api/cron/alerts", headers={"X-Cron-Token": "é" * 5}).status_code == 403   # non-ASCII must not 500
    A.CRON_TOKEN = ""; A.PUSH_ENABLED = False


def test_reset_link_not_logged_in_production(client, capsys, monkeypatch):
    monkeypatch.setattr(A, "_IS_PROD", True)
    A.send_reset_email("a@x.co", "A", "https://x/reset-password/SECRETTOKEN")
    assert "SECRETTOKEN" not in capsys.readouterr().out


def test_connections_are_closed_after_a_crash(client):
    c = _mk(client, "c@x.co")
    for _ in range(30):
        c.post("/farms/add", data={"farm_name": "x", "crop_type": "c", "location": "l", "planting_date": "bad", "area": "1"}, headers=H)
    assert c.post("/farms/add", data={"farm_name": "ok", "crop_type": "c", "location": "l", "planting_date": "2026-01-01", "area": "1"}, headers=H).status_code == 302


def test_reset_mail_goes_out_over_https_api(client, monkeypatch):
    """Render's free plan blocks SMTP, so mail is sent through an HTTPS API; the name is HTML-escaped."""
    sent = {}
    class R: status_code = 201
    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers, body=json); return R()
    monkeypatch.setattr(A, "BREVO_API_KEY", "k"); monkeypatch.setattr(A, "MAIL_FROM", "me@x.co")
    monkeypatch.setattr(A, "MAIL_ENABLED", True); monkeypatch.setattr(A.requests, "post", fake_post)
    assert A.send_reset_email("a@x.co", "<b>Eve</b>", "https://x/reset-password/T") is True
    assert sent["url"].startswith("https://api.brevo.com/") and sent["body"]["to"] == [{"email": "a@x.co"}]
    assert "<b>Eve</b>" not in sent["body"]["htmlContent"] and "&lt;b&gt;" in sent["body"]["htmlContent"]


def test_reset_mail_api_failure_returns_false_without_leaking(client, monkeypatch, capsys):
    class R: status_code = 401
    monkeypatch.setattr(A, "BREVO_API_KEY", "secretkey"); monkeypatch.setattr(A, "MAIL_FROM", "me@x.co")
    monkeypatch.setattr(A, "MAIL_ENABLED", True); monkeypatch.setattr(A.requests, "post", lambda *a, **k: R())
    assert A.send_reset_email("a@x.co", "A", "https://x/reset-password/SECRETTOKEN") is False
    out = capsys.readouterr().out
    assert "SECRETTOKEN" not in out and "secretkey" not in out
    assert "HTTP 401" in out
