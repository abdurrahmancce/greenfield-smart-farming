"""Yield and profit/loss forecast for GreenField - simple, transparent arithmetic (no machine learning).

    expected yield  = area (acres) x yield per acre          (a low / typical / high range)
    expected income = expected yield x price per kg
    expected profit = income - (expenses so far + costs still to come)

The yield-per-acre ranges below are ROUGH typical figures for Bangladesh, written down from general
knowledge and NOT checked against official statistics line by line. They only start the estimate: a farmer's
own number (entered per farm) always replaces them, and the page says which one was used.
Prices come from, in this order: the farmer's own price for the farm, the price the farmer last recorded on the
Market page, or - as a last resort - 70% of the sample wholesale reference (farm-gate is usually below wholesale).
Weather, disease and market swings are not modelled, so the result is an estimate, never a promise.
"""
MAUND_KG = 40.0                      # 1 maund = 40 kg (Bangladesh)
FARMGATE_FACTOR = 0.70               # market-table prices are Dhaka wholesale samples; farm-gate is usually lower, so use 70%
SPREAD = 0.20                        # a farmer-entered yield is shown as  -20% .. +20%

# crop key (see farm_tasks.crop_key) -> (low, typical, high) kg per acre
YIELD_KG_PER_ACRE = {
    "rice":    (1000, 1500, 2000),   # paddy
    "wheat":   (800, 1200, 1600),
    "potato":  (6000, 8000, 10000),
    "tomato":  (5000, 8000, 12000),
    "maize":   (2000, 3000, 3800),
    "mustard": (350, 500, 700),
    "jute":    (700, 900, 1100),     # fibre
    "onion":   (3500, 5000, 6500),
    "garlic":  (2000, 2800, 3600),
    "brinjal": (6000, 9000, 12000),
    "chilli":  (400, 700, 1000),     # dry chilli
    "lentil":  (300, 450, 600),
    "ginger":  (2500, 3500, 5000),
}
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
