import forecast as fc
from conftest import A, H
from test_sensors import _user, _count


def test_arithmetic_and_break_even():
    r = fc.forecast_farm("rice", 2, 30.0, expenses=10000, income=0, remaining_cost=5000)
    assert r["costs_known"]
    assert r["ok"] and r["yield_per_acre"] == [1000, 1350, 1900]
    assert r["kg"] == [2000, 2700, 3800] and r["revenue"] == [60000, 81000, 114000]
    assert r["cost"] == 15000 and r["profit"] == [45000, 66000, 99000]
    assert r["break_even_price"] == 5.6 and r["break_even_yield"] == 250
    assert r["verdict"] == "profit"


def test_loss_and_uncertain_verdicts():
    assert fc.forecast_farm("rice", 1, 10.0, 50000, 0, remaining_cost=0)["verdict"] == "loss"
    assert fc.forecast_farm("rice", 1, 30.0, 40000, 0, remaining_cost=0)["verdict"] == "uncertain"


def test_without_remaining_costs_the_verdict_is_only_an_upper_bound():
    r = fc.forecast_farm("rice", 1, 30.0, 100, 0)                 # costs still to come never entered
    assert r["verdict"] == "partial" and not r["costs_known"]
    assert fc.forecast_farm("rice", 1, 30.0, 100, 0, remaining_cost=0)["verdict"] == "profit"   # an explicit 0 is an answer


def test_recorded_income_is_not_counted_twice():
    r = fc.forecast_farm("rice", 1, 30.0, 0, income=30000)       # forecast mid = 40500, already sold 30000
    assert r["income_total"][1] == 40500 and r["income_total"][0] == 30000
    r = fc.forecast_farm("rice", 1, 1.0, 0, income=30000)         # already earned more than the forecast
    assert r["income_total"] == [30000, 30000, 30000]


def test_users_own_yield_replaces_reference_with_a_spread():
    r = fc.forecast_farm("rice", 2, 30.0, 0, 0, yield_override=2000)
    assert r["yield_source"] == "yours" and r["yield_per_acre"] == [1600, 2000, 2400]


def test_missing_inputs_give_a_reason_not_an_error():
    assert fc.forecast_farm("rice", 0, 30, 0, 0)["reason"] == "no_area"
    assert fc.forecast_farm("quinoa", 2, 30, 0, 0)["reason"] == "no_reference"
    assert fc.forecast_farm("rice", 2, None, 0, 0)["reason"] == "no_price"
    assert fc.forecast_farm("quinoa", 2, 30, 0, 0, yield_override=500)["ok"]


def test_reference_price_is_the_cheapest_match():
    assert fc.reference_price("rice", A._MARKET_FALLBACK) == min(v["price"] for k, v in A._MARKET_FALLBACK.items() if "rice" in k.lower())
    assert fc.reference_price("quinoa", A._MARKET_FALLBACK) is None


def test_page_renders_and_saves_inputs(client):
    c, fid = _user("f@x.co", "Wheat")
    c.post("/expenses/add", data={"farm_id": str(fid), "amount": "1000", "date": "2026-02-01", "type": "expense", "category": "Seeds"}, headers=H)
    html = c.get("/forecast").get_data(as_text=True)
    assert "Break-even" in html and "not a promise" in html and "will be LOWER than shown" in html   # no remaining costs yet
    assert "reference" in html or "sample wholesale" in html           # says where the price came from
    c.post("/forecast/save", data={"farm_id": str(fid), "yield_per_acre": "1500", "price_per_kg": "40", "remaining_cost": "2000"}, headers=H)
    html = c.get("/forecast").get_data(as_text=True)
    assert "your number" in html and _count("forecast_inputs") == 1 and "Even the low case" in html   # costs entered => a real verdict
    c.post("/forecast/save", data={"farm_id": str(fid), "remaining_cost": "0"}, headers=H)
    assert _count("forecast_inputs") == 1 and "Even the low case" in c.get("/forecast").get_data(as_text=True)
    c.post("/forecast/save", data={"farm_id": str(fid), "yield_per_acre": "", "price_per_kg": "", "remaining_cost": ""}, headers=H)
    assert _count("forecast_inputs") == 0                                # empty boxes = back to defaults


def test_forecast_validation_and_isolation(client):
    a, fid = _user("a@x.co")
    b, _ = _user("b@x.co")
    for bad in ("-5", "abc", "nan", "1e99"):
        a.post("/forecast/save", data={"farm_id": str(fid), "yield_per_acre": bad}, headers=H)
    assert _count("forecast_inputs") == 0
    b.post("/forecast/save", data={"farm_id": str(fid), "yield_per_acre": "100"}, headers=H)   # Alice's farm
    assert _count("forecast_inputs") == 0
    assert A.app.test_client().get("/forecast").status_code in (302, 401)


def test_recorded_market_price_beats_reference(client):
    c, fid = _user("m@x.co", "Wheat")
    uid = A.get_db().execute("SELECT id FROM users").fetchone()["id"]
    cn = A.get_db()
    cn.execute("INSERT INTO price_history (crop, price, day, source, user_id) VALUES ('Wheat', 55, '2026-11-10', 'manual', ?)", (uid,)); cn.commit()
    price, src, note = A._price_for(cn, uid, "wheat", None); cn.close()
    assert (price, src, note) == (55.0, "recorded", "2026-11-10")
    cn = A.get_db(); p2, s2, _ = A._price_for(cn, uid, "wheat", 70.0); cn.close()
    assert (p2, s2) == (70.0, "yours")


def test_irrigate_task_does_not_claim_no_rain_without_weather_data():
    import datetime as dt, farm_tasks as ft
    farm = {"id": 1, "farm_name": "A", "crop_type": "Rice", "planting_date": "2026-09-01"}
    today = dt.date(2026, 11, 22)
    no_wx = [t for t in ft.build_tasks(farm, last_irrigation="2026-11-01", wx=None, today=today) if t["kind"] == "irrigate"]
    assert no_wx and "no rain is expected" not in no_wx[0]["detail"] and "no weather data" in no_wx[0]["detail"]
    wx = {"rain_mm": 0, "pop": 0, "temp_max": 30, "temp_min": 24, "wind_kmh": 10, "humidity": 60}
    with_wx = [t for t in ft.build_tasks(farm, last_irrigation="2026-11-01", wx=wx, today=today) if t["kind"] == "irrigate"]
    assert with_wx and "no rain is expected" in with_wx[0]["detail"]
