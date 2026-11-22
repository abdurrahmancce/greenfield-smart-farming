"""Yield and profit/loss forecast for GreenField - simple, transparent arithmetic (no machine learning).

    expected yield  = area (acres) x yield per acre          (a low / typical / high range)
    expected income = expected yield x price per kg
    expected profit = income - (expenses so far + costs still to come)

The "typical" yield per acre of 9 crops is anchored to Bangladesh national averages (BBS Yearbook of Agricultural
Statistics 2022/23 as quoted in the IFPRI 2024 food-security report; BBS FY2023-24 via The Business Standard; DAE via
Daily Sun; BBS via UNB) converted from t/ha with 1 t/ha = 404.7 kg/acre. The low/high ends are a judgement around that
average (for some crops widened using the best district figures); they are not official numbers. Jute, garlic, chilli
and ginger could not be checked and remain rough estimates (see UNVERIFIED). A farmer's own number (entered per farm)
always replaces all of these, and the page says which one was used.
Prices come from, in this order: the farmer's own price for the farm, the price the farmer last recorded on the
Market page, or - as a last resort - 70% of the sample wholesale reference (farm-gate is usually below wholesale).
Weather, disease and market swings are not modelled, so the result is an estimate, never a promise.
"""
MAUND_KG = 40.0                      # 1 maund = 40 kg (Bangladesh)
FARMGATE_FACTOR = 0.70               # market-table prices are Dhaka wholesale samples; farm-gate is usually lower, so use 70%
SPREAD = 0.20                        # a farmer-entered yield is shown as  -20% .. +20%

# crop key (see farm_tasks.crop_key) -> (low, typical, high) kg per acre.  "typical" = national average where sourced.
YIELD_KG_PER_ACRE = {
    "rice":    (1000, 1350, 1900),   # paddy; BBS 2022/23 all-rice 3.3 t/ha (aus/aman 2.7, boro 4.2) -> 1,335
    "wheat":   (1000, 1400, 1700),   # BBS 2022/23 3.4-3.7 t/ha (two figures in source) -> 1,376-1,497
    "potato":  (7000, 9400, 11000),  # BBS FY25 production / area (UNB) = 9.4 t/acre (derived)
    "tomato":  (4000, 6000, 10000),  # BBS 2022/23 15.1 t/ha -> 6,110 (FAO 2024: 15.8); best district 29.2 t/ha
    "maize":   (3000, 4000, 4400),   # BBS winter maize FY24 4,003 kg/acre, FY25 4,356 (TBS)
    "mustard": (350, 520, 1000),     # BBS 2022/23 1.3 t/ha -> 526; best district 2.5 t/ha
    "onion":   (4000, 5800, 7000),   # DAE FY23-24 14.6 t/ha -> 5,920 (Daily Sun); FY23 13.9
    "brinjal": (3500, 5000, 8000),   # BBS 2022/23 12.3 t/ha -> 4,978; best district 20.5 t/ha
    "lentil":  (350, 570, 900),      # BBS 2022/23 1.4 t/ha -> 567; best district 2.2 t/ha
    # --- NOT checked against any official source: rough estimates ---
    "jute":    (700, 900, 1100),     # fibre
    "garlic":  (2000, 2800, 3600),
    "chilli":  (400, 700, 1000),     # dry chilli
    "ginger":  (2500, 3500, 5000),
}
UNVERIFIED = {"jute", "garlic", "chilli", "ginger"}
# crop key -> words that identify its row in the market price table
PRICE_MATCH = {"rice": "rice", "wheat": "wheat", "potato": "potato", "tomato": "tomato", "maize": "maize",
               "mustard": "mustard", "jute": "jute", "onion": "onion", "garlic": "garlic", "brinjal": "brinjal",
               "chilli": "chilli", "lentil": "lentil", "ginger": "ginger"}


def reference_price(crop_key, table):
    """Lowest matching reference price (conservative) from the market table, or None."""
    word = PRICE_MATCH.get(crop_key)
    if not word:
        return None
    vals = [float(v["price"]) for name, v in table.items() if word in name.lower()]
    return min(vals) if vals else None


def _round(x, n=0):
    return round(x, n) if x is not None else None


def forecast_farm(crop_key, area, price, expenses, income, yield_override=None, remaining_cost=None):
    """Return a dict describing the estimate, or one with ok=False and a reason.
    area: acres; price: BDT per kg (or None); expenses/income: totals already recorded; yield_override: kg per acre;
    remaining_cost: costs still to come - None means the farmer has not said, and then the profit is only an upper bound."""
    out = {"ok": False, "reason": "", "yield_source": "", "area": area}
    if not area or area <= 0:
        out["reason"] = "no_area"; return out
    if yield_override and yield_override > 0:
        mid = float(yield_override)
        lo, hi = mid * (1 - SPREAD), mid * (1 + SPREAD)
        out["yield_source"] = "yours"
    elif crop_key in YIELD_KG_PER_ACRE:
        lo, mid, hi = YIELD_KG_PER_ACRE[crop_key]
        out["yield_source"] = "reference"
    else:
        out["reason"] = "no_reference"; return out
    if not price or price <= 0:
        out["reason"] = "no_price"; return out

    kg = [lo * area, mid * area, hi * area]
    revenue = [k * price for k in kg]
    # money already received is part of the harvest sales, so it is never counted twice
    total_income = [max(r, income) for r in revenue]
    cost = expenses + max(0.0, remaining_cost or 0.0)
    profit = [t - cost for t in total_income]
    out.update({
        "ok": True, "price": price,
        "yield_per_acre": [_round(lo), _round(mid), _round(hi)],
        "kg": [_round(k) for k in kg], "maund": [_round(k / MAUND_KG, 1) for k in kg],
        "revenue": [_round(r) for r in revenue], "income_total": [_round(t) for t in total_income],
        "cost": _round(cost), "expenses": _round(expenses), "remaining_cost": _round(max(0.0, remaining_cost or 0.0)),
        "profit": [_round(p) for p in profit], "profit_per_acre": [_round(p / area) for p in profit],
        "break_even_price": _round(cost / kg[1], 1) if kg[1] else None,   # BDT/kg needed at the typical yield
        "break_even_yield": _round(cost / price / area) if price else None,  # kg/acre needed at this price
        "costs_known": remaining_cost is not None,
        "verdict": ("partial" if remaining_cost is None else
                    "profit" if profit[0] > 0 else "loss" if profit[2] < 0 else "uncertain"),
    })
    return out


# Growing seasons (rough guide from the PLANTING month - real calendars vary by region and variety)
_RICE = {"aus": ("Aus", "আউশ"), "aman": ("Aman", "আমন"), "boro": ("Boro", "বোরো")}
_OTHER = {"rabi": ("Rabi (winter)", "রবি (শীত)"), "kharif1": ("Kharif-1 (pre-monsoon)", "খরিফ-১ (প্রাক-বর্ষা)"),
          "kharif2": ("Kharif-2 (monsoon)", "খরিফ-২ (বর্ষা)")}


def season_of(crop_key, planting_date):
    """{'key','en','bn'} for the season a farm was planted in, or None if the date is missing/unreadable.
    Rice: Mar-May = Aus, Jun-Oct = Aman, Nov-Feb = Boro.  Other crops: Nov-Feb = Rabi, Mar-Jun = Kharif-1, Jul-Oct = Kharif-2."""
    try:
        m = int(str(planting_date)[5:7])
        if not 1 <= m <= 12 or str(planting_date)[4] != "-":
            return None
    except (TypeError, ValueError, IndexError):
        return None
    if crop_key == "rice":
        k = "aus" if 3 <= m <= 5 else "aman" if 6 <= m <= 10 else "boro"
        en, bn = _RICE[k]
    else:
        k = "rabi" if (m >= 11 or m <= 2) else "kharif1" if m <= 6 else "kharif2"
        en, bn = _OTHER[k]
    return {"key": k, "en": en, "bn": bn}


def actual_check(income_so_far, typical_revenue, harvest_date, today_iso):
    """Compare money actually recorded with the typical-case revenue estimate.
    Only judged after the expected harvest date - before that, sales are simply not all in yet."""
    if not income_so_far or income_so_far <= 0 or not typical_revenue or typical_revenue <= 0:
        return None
    pct = round(income_so_far / typical_revenue * 100)
    passed = bool(harvest_date) and str(harvest_date) <= str(today_iso)
    verdict = "early" if not passed else "below" if pct < 80 else "above" if pct > 120 else "close"
    return {"pct": pct, "verdict": verdict, "recorded": round(income_so_far), "typical": round(typical_revenue)}


def season_summary(rows):
    """Group the farms that have a forecast by season -> list of dicts (sorted by season name)."""
    g = {}
    for r in rows:
        x, se = r["fc"], r.get("season")
        if not x.get("ok") or not se:
            continue
        a = g.setdefault(se["key"], {"en": se["en"], "bn": se["bn"], "n": 0, "acres": 0.0, "income": 0, "cost": 0, "profit": 0, "partial": False})
        a["n"] += 1; a["acres"] += x["area"]; a["income"] += x["income_total"][1]
        a["cost"] += x["cost"]; a["profit"] += x["profit"][1]; a["partial"] = a["partial"] or not x["costs_known"]
    out = []
    for a in sorted(g.values(), key=lambda z: z["en"]):
        a["profit_per_acre"] = round(a["profit"] / a["acres"]) if a["acres"] else 0
        a["acres"] = round(a["acres"], 1)
        out.append(a)
    return out
