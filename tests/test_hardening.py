import app as A
from conftest import H


def test_isolation_headers_and_security_txt(client):
    r = client.get("/login")
    assert r.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert r.headers["Cross-Origin-Resource-Policy"] == "same-site"
    t = client.get("/.well-known/security.txt")
    assert t.status_code == 200 and t.mimetype == "text/plain"
    body = t.get_data(as_text=True)
    assert "Contact: https://github.com/" in body and "Expires: " in body


def test_weak_passwords_are_refused():
    assert A.weak_password_reason("password123")
    assert A.weak_password_reason("Password123")          # case-insensitive
    assert A.weak_password_reason("aaaaaaaaaa")           # one repeated character
    assert A.weak_password_reason("abdurrahman", "abdurrahman@x.com")   # same as e-mail name
    assert A.weak_password_reason("Tr0ub4dor&3x", "a@b.com", "Abdur") is None


def test_register_rejects_a_common_password(client):
    r = client.post("/register", data={"name": "Rahim Uddin", "email": "r@example.com",
                                      "password": "password123", "confirm": "password123"}, headers=H)
    assert b"too common" in r.data
    conn = A.get_db()
    assert conn.execute("SELECT COUNT(*) AS n FROM users WHERE email='r@example.com'").fetchone()["n"] == 0
    conn.close()


def test_google_redirect_ignores_forged_host(client, monkeypatch):
    monkeypatch.setattr(A, "APP_BASE_URL", "https://greenfield.example")
    monkeypatch.setattr(A, "GOOGLE_CLIENT_ID", "x", raising=False)
    r = client.get("/login/google", headers={"Host": "evil.example"})
    loc = r.headers.get("Location", "")
    assert "evil.example" not in loc


def test_set_language_only_redirects_to_a_path_on_this_site(client):
    r = client.get("/set-language/bn", headers={"Referer": "http://localhost/farms?x=1", "Host": "localhost"})
    assert r.headers["Location"] == "/farms?x=1"
    for evil in ("http://localhost.evil.example/", "https://evil.example/x", "http://localhost@evil.example/"):
        r = client.get("/set-language/en", headers={"Referer": evil, "Host": "localhost"})
        assert "evil" not in r.headers["Location"]
