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
