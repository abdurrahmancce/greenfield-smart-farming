import io
from conftest import A, H
import exports


def _user(email="e@x.co"):
    c = A.app.test_client()
    c.post("/register", data={"name": "Eve", "email": email, "password": "password1", "confirm": "password1"}, headers=H)
    c.post("/farms/add", data={"farm_name": "=HYPERLINK(\"http://evil\")", "crop_type": "Rice", "location": "বাংলা", "planting_date": "2026-01-01", "area": "2"}, headers=H)
    cn = A.get_db(); fid = cn.execute("SELECT id FROM farms WHERE user_id=(SELECT id FROM users WHERE email=?)", (email,)).fetchone()["id"]; cn.close()
    c.post("/expenses/add", data={"farm_id": fid, "amount": "100", "date": "2026-02-01", "description": "+cmd|' /C calc'!A0 <b>x</b>"}, headers=H)
    c.post("/expenses/add", data={"farm_id": fid, "amount": "40", "type": "income", "date": "2025-02-01"}, headers=H)
    c.post("/irrigation/add", data={"farm_id": fid, "date": "2026-02-01", "water_liters": "300"}, headers=H)
    return c, fid


def test_csv_downloads_and_formula_guard(client):
    c, _ = _user()
    r = c.get("/export/expenses.csv")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"] and r.headers["Cache-Control"] == "no-store"
    text = r.data.decode("utf-8-sig")
    assert "'+cmd" in text and "\n+cmd" not in text and ",+cmd" not in text
    farms = c.get("/export/farms.csv").data.decode("utf-8-sig")
    assert "'=HYPERLINK" in farms and "বাংলা" in farms
    assert "300" in c.get("/export/irrigation.csv").data.decode("utf-8-sig")


def test_year_filter(client):
    c, _ = _user()
    only25 = c.get("/export/expenses.csv?year=2025").data.decode("utf-8-sig")
    assert "2025-02-01" in only25 and "2026-02-01" not in only25
    assert "2026-02-01" in c.get("/export/expenses.csv?year=zzzz").data.decode("utf-8-sig")      # bad year ignored


def test_pdf_is_valid_and_survives_markup_and_bangla(client):
    c, _ = _user()
    r = c.get("/export/report.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")


def test_downloads_need_login_and_only_own_data(client):
    assert A.app.test_client().get("/export/expenses.csv").status_code in (302, 401)
    a, _ = _user("a1@x.co")
    b = A.app.test_client()
    b.post("/register", data={"name": "B", "email": "b1@x.co", "password": "password1", "confirm": "password1"}, headers=H)
    body = b.get("/export/expenses.csv").data.decode("utf-8-sig")
    assert body.strip().count("\n") == 0                         # header only
    for bad in ("/export/report.csv", "/export/farms.pdf", "/export/users.csv", "/export/expenses.xlsx"):
        assert b.get(bad).status_code == 404


def test_safe_cell():
    assert exports.safe_cell("=1+1") == "'=1+1" and exports.safe_cell("-5 off") == "'-5 off"
    assert exports.safe_cell(-5) == -5 and exports.safe_cell("normal") == "normal" and exports.safe_cell(None) == ""


def test_report_page_shows_area_and_growth_crop(client):
    c, fid = _user("rp@x.co")
    c.post("/growth/add", data={"farm_id": fid, "planting_date": "2026-01-01", "expected_days": "90"}, headers=H)
    html = c.get("/report").data.decode()
    assert "<strong>Area:</strong> 2.0 acres" in html or "<strong>Area:</strong> 2 acres" in html
    assert "<td>Rice</td>" in html                      # crop column of the growth table is filled
