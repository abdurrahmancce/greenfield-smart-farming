"""Rule-based "what should I do today" engine for GreenField.

Everything here is transparent and explainable: simple agronomy rules (days after planting, days since last
irrigation) combined with the short-term weather forecast. It does NOT use AI, and every task says why it appears.
General guidance only - the farmer should always follow local Agriculture Officer (DAE) advice.
"""
import time
from datetime import datetime, date

# ── crop knowledge (general Bangladesh guidance) ───────────────────────────────────────────────
IRRIGATION_DAYS = {"rice": 3, "wheat": 12, "potato": 9, "tomato": 6, "maize": 10, "mustard": 15, "jute": 10,
                   "onion": 8, "garlic": 8, "brinjal": 6, "chilli": 6, "lentil": 20, "ginger": 7}
TOPDRESS_DAP = {"rice": [15, 40, 60], "wheat": [18, 50], "potato": [25, 45], "tomato": [20, 40, 60],
                "maize": [25, 50], "mustard": [25], "jute": [25, 45], "onion": [25, 50], "garlic": [30, 55],
                "brinjal": [25, 50, 75], "chilli": [25, 50, 75], "lentil": [30], "ginger": [45, 90, 135]}
EXPECTED_DAYS = {"rice": 130, "wheat": 110, "potato": 90, "tomato": 90, "maize": 120, "mustard": 100, "jute": 120,
                 "onion": 100, "garlic": 100, "brinjal": 80, "chilli": 120, "lentil": 100, "ginger": 240}
BLIGHT_CROPS = {"potato", "tomato"}
DISEASE_NAME = {"potato": "late blight", "tomato": "late blight / leaf mould", "rice": "blast and sheath blight",
                "wheat": "rust and blast", "mustard": "Alternaria blight", "maize": "leaf blight"}
ALIASES = {"corn": "maize", "paddy": "rice", "brinjal": "brinjal", "eggplant": "brinjal", "aubergine": "brinjal",
           "chili": "chilli", "chillies": "chilli", "capsicum": "chilli"}

_TXT = {
 "rain_alert":   ("Heavy rain / storm expected", "ভারী বৃষ্টি / ঝড়ের সম্ভাবনা",
                  "About {rain} mm of rain and wind up to {wind} km/h are forecast in the next 24 h. Harvest anything ripe, "
                  "clear drains, and secure plastic covers or stakes.",
                  "আগামী ২৪ ঘণ্টায় প্রায় {rain} মিমি বৃষ্টি ও ঘণ্টায় {wind} কিমি পর্যন্ত বাতাসের সম্ভাবনা। পাকা ফসল তুলে নিন, নালা পরিষ্কার রাখুন, "
                  "প্লাস্টিক ও খুঁটি শক্ত করুন।"),
 "heat_alert":   ("Heat stress risk", "তাপের চাপের ঝুঁকি",
                  "Up to {temp}°C expected. Irrigate in the early morning or evening, not at midday, and mulch if you can.",
                  "{temp}°C পর্যন্ত তাপমাত্রার সম্ভাবনা। দুপুরে নয়, ভোরে বা সন্ধ্যায় সেচ দিন; সম্ভব হলে মালচিং করুন।"),
 "irrigate":     ("Irrigate today", "আজ সেচ দিন",
                  "Last irrigation was {days} days ago ({crop} usually needs water every ~{every} days) and no rain is expected.",
                  "শেষ সেচ {days} দিন আগে ({crop} সাধারণত ~{every} দিন পরপর পানি চায়) এবং বৃষ্টির সম্ভাবনা নেই।"),
 "irrigate_never": ("Check soil moisture", "মাটির আর্দ্রতা দেখুন",
                  "No irrigation has been logged for this farm yet. Check soil moisture and log your next irrigation.",
                  "এই খামারের কোনো সেচ এখনও লেখা নেই। মাটির আর্দ্রতা দেখুন এবং পরের সেচ লিখে রাখুন।"),
 "skip_irrigation": ("Skip irrigation — rain coming", "সেচ দরকার নেই — বৃষ্টি আসছে",
                  "About {rain} mm of rain is forecast in the next 24 h, so you can hold off irrigating.",
                  "আগামী ২৪ ঘণ্টায় প্রায় {rain} মিমি বৃষ্টির সম্ভাবনা, তাই এখন সেচ না দিলেও চলবে।"),
 "rice_water":   ("Check standing water in the field", "জমির দাঁড়ানো পানি দেখুন",
                  "Rice does best with about 3–5 cm of standing water during growth. Top up if the field is drying.",
                  "বৃদ্ধির সময় ধানের জমিতে ৩–৫ সেমি পানি ভালো। জমি শুকিয়ে এলে পানি দিন।"),
 "topdress":     ("Top-dress fertilizer window", "উপরি সার প্রয়োগের সময়",
                  "It is about day {dap} after planting — a usual time for top-dressing {crop}. Use the Fertilizer Calculator "
                  "for the amount and follow your local DAE dose.",
                  "রোপণের প্রায় {dap} দিন পার হয়েছে — {crop}-এ উপরি সার দেওয়ার সাধারণ সময়। পরিমাণের জন্য সার ক্যালকুলেটর দেখুন এবং স্থানীয় কৃষি অফিসের মাত্রা মানুন।"),
 "fungal":       ("High fungal-disease risk", "ছত্রাকজনিত রোগের উচ্চ ঝুঁকি",
                  "Humid, wet weather ({hum}% humidity) favours {disease}. Inspect leaves (both sides) today; photograph anything "
                  "suspicious in the Disease Detector.",
                  "আর্দ্র ও ভেজা আবহাওয়া ({hum}% আর্দ্রতা) {disease}-এর জন্য অনুকূল। আজ পাতার দুই দিক দেখুন; সন্দেহজনক কিছু পেলে রোগ নির্ণয়ে ছবি তুলুন।"),
 "harvest_soon": ("Harvest approaching", "ফসল তোলার সময় ঘনিয়ে আসছে",
                  "About {left} days to the expected harvest ({crop}). Arrange labour, drying space and storage.",
                  "প্রত্যাশিত ফসল তোলার আর প্রায় {left} দিন ({crop})। শ্রমিক, শুকানোর জায়গা ও সংরক্ষণের ব্যবস্থা করুন।"),
 "harvest_now":  ("Check if ready to harvest", "ফসল পাকল কিনা দেখুন",
                  "It has been {dap} days since planting (expected ~{exp}). Check maturity signs and plan the harvest.",
                  "রোপণের পর {dap} দিন হয়েছে (প্রত্যাশিত ~{exp})। পাকার লক্ষণ দেখে ফসল তোলার পরিকল্পনা করুন।"),
 "followup":     ("Follow up on last diagnosis", "আগের রোগ নির্ণয়ের ফলোআপ",
                  "{dx} was found {days} day(s) ago. Re-check the plants and see whether treatment is working.",
                  "{days} দিন আগে {dx} ধরা পড়েছিল। গাছগুলো আবার দেখুন এবং চিকিৎসা কাজ করছে কিনা যাচাই করুন।"),
}
_LINKS = {"irrigate": "/irrigation", "irrigate_never": "/irrigation", "topdress": "/fertilizer", "fungal": "/disease",
          "followup": "/disease", "harvest_soon": "/growth", "harvest_now": "/growth", "rice_water": "/irrigation",
          "skip_irrigation": "/irrigation"}
_ICON = {"rain_alert": "⛈️", "heat_alert": "🌡️", "irrigate": "💧", "irrigate_never": "💧", "skip_irrigation": "🌧️",
         "rice_water": "🌾", "topdress": "🧪", "fungal": "🍄", "harvest_soon": "🧺", "harvest_now": "🌾", "followup": "🔎"}
_PRI = {"rain_alert": 0, "heat_alert": 0, "irrigate": 0, "fungal": 0, "harvest_now": 0, "topdress": 1, "harvest_soon": 1,
        "followup": 1, "irrigate_never": 2, "skip_irrigation": 2, "rice_water": 2}


def crop_key(name):
    n = (name or "").lower()
    for a, k in ALIASES.items():
        if a in n:
            return k
    for k in IRRIGATION_DAYS:
        if k in n:
            return k
    return ""


def _d(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def summarize_forecast(items):
    """OpenWeather 5-day/3-hour list -> dict for the next 24 hours (first 8 slots)."""
    sl = (items or [])[:8]
    if not sl:
        return None
    rain = sum((i.get("rain") or {}).get("3h", 0) or 0 for i in sl)
    return {"rain_mm": round(rain, 1),
            "pop": max((i.get("pop") or 0) for i in sl),
            "temp_max": round(max(i["main"]["temp"] for i in sl)),
            "temp_min": round(min(i["main"]["temp"] for i in sl)),
            "humidity": round(sum(i["main"]["humidity"] for i in sl) / len(sl)),
            "wind_kmh": round(max((i.get("wind") or {}).get("speed", 0) for i in sl) * 3.6)}


_fc_cache = {}


def fetch_forecast(city, api_key, requests_mod, ttl=1800):
    """Cached 24-hour forecast summary for a city, or None if unavailable."""
    if not api_key or not city:
        return None
    k = city.strip().lower()
    hit = _fc_cache.get(k)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        r = requests_mod.get("https://api.openweathermap.org/data/2.5/forecast",
                             params={"q": city, "appid": api_key, "units": "metric", "cnt": 8}, timeout=5)
        data = summarize_forecast(r.json().get("list")) if r.status_code == 200 else None
    except Exception:
        data = None
    _fc_cache[k] = (time.time(), data)
    return data


def build_tasks(farm, growth=None, last_irrigation=None, scan=None, wx=None, today=None, lang="en"):
    """farm: dict(id,farm_name,crop_type,planting_date); growth: dict(expected_days,growth_stage) or None;
    last_irrigation: 'YYYY-MM-DD' or None; scan: dict(diagnosis,health_status,severity,created_at) or None;
    wx: summarize_forecast() dict or None. Returns a list of task dicts (unsorted)."""
    bn = lang == "bn"
    today = today or date.today()
    out = []
    ck = crop_key(farm.get("crop_type"))
    crop_label = farm.get("crop_type") or ""
    planted = _d(farm.get("planting_date"))
    dap = (today - planted).days if planted else None

    def add(kind, **kw):
        t = _TXT[kind]
        out.append({"id": f"{farm['id']}:{kind}", "kind": kind, "icon": _ICON[kind], "priority": _PRI[kind],
                    "title": t[1] if bn else t[0], "detail": (t[3] if bn else t[2]).format(**kw),
                    "farm_id": farm["id"], "farm": farm.get("farm_name", ""), "link": _LINKS.get(kind, "")})

    rain = wx["rain_mm"] if wx else 0
    # weather alerts
    if wx and (rain >= 15 or (wx["pop"] >= 0.8 and wx["wind_kmh"] >= 40) or wx["wind_kmh"] >= 55):
        add("rain_alert", rain=rain, wind=wx["wind_kmh"])
    if wx and wx["temp_max"] >= 36:
        add("heat_alert", temp=wx["temp_max"])
    # irrigation
    every = IRRIGATION_DAYS.get(ck, 7)
    if ck:
        li = _d(last_irrigation)
        if wx and rain >= 5:
            add("skip_irrigation", rain=rain)
        elif li is not None:
            days = (today - li).days
            if days >= every:
                add("irrigate", days=days, crop=crop_label, every=every)
        elif dap is not None and dap >= 0:
            add("irrigate_never")
        if ck == "rice" and not (wx and rain >= 5):
            add("rice_water")
    # fertilizer top-dressing windows
    if dap is not None and ck in TOPDRESS_DAP:
        for d0 in TOPDRESS_DAP[ck]:
            if d0 - 1 <= dap <= d0 + 4:
                add("topdress", dap=dap, crop=crop_label)
                break
    # fungal risk from weather
    if wx and (wx["humidity"] >= 85 or rain >= 3) and 15 <= wx["temp_max"] <= 32 and ck in DISEASE_NAME:
        add("fungal", hum=wx["humidity"], disease=DISEASE_NAME[ck])
    # harvest timing
    exp = (growth or {}).get("expected_days") or EXPECTED_DAYS.get(ck)
    if dap is not None and exp and dap >= 0:
        left = exp - dap
        if left <= 0:
            add("harvest_now", dap=dap, exp=exp)
        elif left <= 10:
            add("harvest_soon", left=left, crop=crop_label)
    # follow-up on a recent problem scan
    if scan and scan.get("health_status") not in ("healthy", "unclear", "", None):
        sd = _d(scan.get("created_at"))
        if sd is not None:
            ago = (today - sd).days
            if 2 <= ago <= 10:
                add("followup", dx=scan.get("diagnosis") or "a problem", days=ago)
    return out


def sort_tasks(tasks):
    return sorted(tasks, key=lambda t: (t["priority"], t["farm"], t["kind"]))
