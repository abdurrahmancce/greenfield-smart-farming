import os, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DATABASE_URL", None)
import app as A

H = {"Origin": "http://localhost"}

@pytest.fixture()
def client(tmp_path):
    A.DB_PATH = str(tmp_path / "t.db")
    A.init_db()
    A.app.config["TESTING"] = True
    A._throttle_hits.clear()
    return A.app.test_client()


@pytest.fixture(autouse=True)
def _fast_password_hashing(monkeypatch):
    """Tests create many users; the real scrypt hash is deliberately slow (good for security, bad for test time).
    Use a very cheap hash here only. check_password_hash still verifies it, and production code is untouched."""
    real = A.generate_password_hash
    monkeypatch.setattr(A, "generate_password_hash", lambda pw, *a, **k: real(pw, method="pbkdf2:sha256:1"))
