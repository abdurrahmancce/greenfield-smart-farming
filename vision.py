"""
GreenField — photo-based plant health analysis.

A photo is sent to a vision-capable AI model together with the crop, any notes the
farmer typed, and a strict instruction set (plant-pathologist role, honest
confidence, say "unclear" rather than guess). The model must answer in a fixed JSON
shape which is then validated / clamped here before it reaches the browser.

Providers (first one with a key is used):
  1. Google Gemini   - env GEMINI_API_KEY   (free tier at https://aistudio.google.com/apikey)
  2. Anthropic Claude - env ANTHROPIC_API_KEY
Nothing is stored: the photo is analysed and discarded.
"""
import base64
import json
import os
import re

import requests

# Newer Google projects cannot use gemini-2.5-*; try current models in order (first one that exists wins).
GEMINI_MODELS = [m.strip() for m in os.environ.get(
    "GEMINI_MODEL", "gemini-3.8-flash,gemini-3.5-flash-lite,gemini-3.6-flash,gemini-2.5-flash").split(",") if m.strip()]
_good_model = None
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
TIMEOUT = 35            # per request
DEADLINE = 85           # total seconds for all fallbacks (gunicorn kills a worker at 120s)
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_BYTES = 6 * 1024 * 1024


def provider():
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def sniff_mime(data: bytes):
    """Trust the bytes, not the browser-supplied content type."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


SCHEMA_HELP = """{
  "is_plant": true|false,                      // is a plant / crop / leaf / fruit actually visible?
  "image_quality": "good"|"fair"|"poor",       // focus, light, distance
  "plant_identified": "string",                // e.g. "Tomato (leaf)"; "" if not sure
  "health_status": "healthy"|"disease"|"pest"|"nutrient_deficiency"|"environmental_stress"|"unclear",
  "primary_diagnosis": "string",               // common name, e.g. "Early blight (Alternaria solani)"; "" if healthy/unclear
  "confidence": 0-100,                         // be honest and conservative
  "severity": "None"|"Low"|"Medium"|"High",
  "visible_evidence": ["what exactly you can SEE that supports the diagnosis"],
  "other_possibilities": [{"name":"string","confidence":0-100}],   // max 3
  "treatment": {
     "immediate_steps": ["actions for the next 24-48 hours"],
     "organic_options": ["low-cost / organic options"],
     "chemical_options": ["generic active ingredient names with a note to follow the label; no brand claims"]
  },
  "prevention": ["how to stop it coming back"],
  "needs_expert": true|false,                  // true if confidence < 60, image poor, or severe/spreading
  "retake_tips": ["only if image_quality is not good or health_status is unclear"],
  "summary": "2-3 plain sentences a farmer can understand"
}"""


def build_prompt(crop, notes, lang):
    language = ("Bengali (Bangla, simple everyday words a farmer in Bangladesh understands; "
                "keep scientific names and chemical names in English in brackets)"
                if lang == "bn" else "English (clear, simple wording)")
    return f"""You are an expert plant pathologist and agronomist advising a smallholder farmer in Bangladesh.
Analyse the attached photograph of a plant.

Context from the farmer:
- Crop: {crop or 'not specified'}
- Notes: {notes or 'none'}

Rules (very important):
1. Base every statement ONLY on what is actually visible in the photo plus the context above. Never invent symptoms.
2. If the photo does not clearly show a plant (or is too blurry/dark/far to judge), set is_plant or image_quality accordingly, set health_status to "unclear", and explain how to retake it. Do NOT guess a disease.
3. If the plant looks healthy, say so (health_status "healthy", severity "None"). Do not manufacture a problem.
4. Confidence must be calibrated: many diseases look alike from one photo, so use 85+ only when the signs are classic and unmistakable. List realistic alternatives in other_possibilities.
5. Treatment advice must be practical and safe: prefer cultural and organic steps first, then generic chemical active ingredients with "follow label dose and pre-harvest interval". No made-up doses. Mention removing/isolating infected plant parts where relevant.
6. Set needs_expert true whenever confidence is below 60, the image is poor, or the problem is severe or spreading fast; the farmer can then contact the local Sub-Assistant Agriculture Officer (DAE) or call the Krishi Call Center 16123.
7. Write all text values in {language}.

Reply with ONLY one JSON object, no markdown, exactly this shape:
{SCHEMA_HELP}"""


class VisionError(Exception):
    pass


def _call_gemini(img_b64, mime, prompt, models=None):
    """Try current Gemini models in order. Skips a model that is missing (404), rejects our options (400),
    is overloaded (5xx) or too slow (timeout) and moves on to the next, within an overall deadline."""
    global _good_model
    import time as _t
    base = {
        "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": img_b64}}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    order = list(models) if models else ([_good_model] if _good_model else []) + [m for m in GEMINI_MODELS if m != _good_model]
    start, last = _t.time(), "no model tried"
    for model in order:
        for fast in (True, False):          # first ask for low "thinking" (much quicker); retry plain if rejected
            left = DEADLINE - (_t.time() - start)
            if left < 8:
                raise VisionError("The AI took too long to answer. Please try again.")
            payload = json.loads(json.dumps(base))
            if fast:
                payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "low"}
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            t0 = _t.time()
            try:
                r = requests.post(url, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                                  json=payload, timeout=min(TIMEOUT, left))
            except requests.Timeout:
                print(f"[vision] {model} timed out after {_t.time()-t0:.0f}s")
                last = "timeout"
                break                        # next model
            print(f"[vision] {model} fast={fast} -> {r.status_code} in {_t.time()-t0:.1f}s")
            if r.status_code == 400 and fast:
                print("[vision]", r.text[:200]); continue      # retry same model without thinking option
            if r.status_code in (400, 404) or r.status_code >= 500:
                print("[vision]", r.text[:200]); last = r.status_code; break
            if r.status_code == 429:
                raise VisionError("The free AI quota is busy right now. Please try again in a minute.")
            if r.status_code in (401, 403):
                print("[vision] auth error:", r.text[:200])
                raise VisionError("The AI key was rejected. The site owner should check GEMINI_API_KEY.")
            if r.status_code != 200:
                raise VisionError(f"AI service error ({r.status_code}).")
            try:
                parts = r.json()["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            except (KeyError, IndexError, ValueError):
                last = "empty"; break
            if text.strip():
                if not models:
                    _good_model = model
                return text
            last = "empty"; break
    if last == "timeout":
        raise VisionError("The AI took too long to answer. Please try again.")
    raise VisionError(f"AI service error ({last}): no Gemini model answered.")


def _call_anthropic(img_b64, mime, prompt):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": ANTHROPIC_MODEL, "max_tokens": 1800, "temperature": 0.2,
              "messages": [{"role": "user", "content": [
                  {"type": "image", "source": {"type": "base64", "media_type": mime, "data": img_b64}},
                  {"type": "text", "text": prompt}]}]},
        timeout=TIMEOUT)
    if r.status_code == 429:
        raise VisionError("The AI service is busy right now. Please try again in a minute.")
    if r.status_code != 200:
        raise VisionError(f"AI service error ({r.status_code}).")
    try:
        return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
    except (KeyError, ValueError):
        raise VisionError("The AI could not analyse this image. Try a clearer photo.")


def _extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    raise VisionError("The AI reply could not be read. Please try again.")


def _s(v, limit=400):
    return str(v).strip()[:limit] if v is not None else ""


def _list(v, n=8, limit=300):
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    return [_s(x, limit) for x in v if _s(x)][:n]


def _pct(v):
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def clean(raw):
    """Validate / clamp the model output so the UI never gets surprises."""
    if not isinstance(raw, dict):
        raise VisionError("The AI reply could not be read. Please try again.")
    status = _s(raw.get("health_status")).lower()
    if status not in {"healthy", "disease", "pest", "nutrient_deficiency", "environmental_stress", "unclear"}:
        status = "unclear"
    quality = _s(raw.get("image_quality")).lower()
    if quality not in {"good", "fair", "poor"}:
        quality = "fair"
    sev = _s(raw.get("severity")).capitalize()
    if sev not in {"None", "Low", "Medium", "High"}:
        sev = "None" if status == "healthy" else "Medium"
    is_plant = bool(raw.get("is_plant", True))
    conf = _pct(raw.get("confidence"))
    treat = raw.get("treatment") if isinstance(raw.get("treatment"), dict) else {}
    others = []
    for o in (raw.get("other_possibilities") or [])[:3]:
        if isinstance(o, dict) and _s(o.get("name")):
            others.append({"name": _s(o["name"], 120), "confidence": _pct(o.get("confidence"))})
    if not is_plant:
        status = "unclear"
    out = {
        "is_plant": is_plant,
        "image_quality": quality,
        "plant_identified": _s(raw.get("plant_identified"), 120),
        "health_status": status,
        "primary_diagnosis": _s(raw.get("primary_diagnosis"), 160),
        "confidence": conf,
        "severity": sev,
        "visible_evidence": _list(raw.get("visible_evidence")),
        "other_possibilities": others,
        "treatment": {
            "immediate_steps": _list(treat.get("immediate_steps")),
            "organic_options": _list(treat.get("organic_options")),
            "chemical_options": _list(treat.get("chemical_options")),
        },
        "prevention": _list(raw.get("prevention")),
        "retake_tips": _list(raw.get("retake_tips"), 5),
        "summary": _s(raw.get("summary"), 700),
    }
    # Safety nets the model might forget.
    needs = bool(raw.get("needs_expert"))
    if status in {"disease", "pest", "nutrient_deficiency", "environmental_stress"} and (
            conf < 60 or quality == "poor" or sev == "High"):
        needs = True
    if status == "unclear":
        needs = True
    out["needs_expert"] = needs
    return out


_STOP = {"disease", "leaf", "leaves", "spot", "spots", "blight", "damage", "infection", "of", "the", "and", "or",
         "fungus", "virus", "symptoms", "disorder", "rot", "mite", "mites"}


def _sci(name):
    m = re.search(r"\(([^)]+)\)", name or "")
    return re.sub(r"[^a-z ]", "", m.group(1).lower()).strip() if m else ""


def _tokens(name):
    base = re.sub(r"\([^)]*\)", " ", (name or "").lower())
    base = base.replace("erineum", "blister").replace("erinose", "blister")      # same mite, two names
    return {w for w in re.findall(r"[a-z]+", base) if w not in _STOP and len(w) > 2}


def _same_dx(a, b):
    """True if two diagnosis names clearly refer to the same problem."""
    if not a or not b:
        return False
    sa, sb = _sci(a), _sci(b)
    if sa and sb and (sa == sb or sa.split()[0] == sb.split()[0]):
        return True
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb and len(ta & tb) / len(ta | tb) >= 0.5:
        return True
    return False


def _listed(name, res):
    return any(_same_dx(name, o["name"]) for o in res.get("other_possibilities", []))


def combine(a, b):
    """Cross-check two independent model answers and turn their (self-reported) confidences into one
    conservative figure. Agreement raises trust; disagreement lowers it and asks for an expert."""
    if b is None:
        a["confidence"] = min(a["confidence"], 80)
        a["verification"] = {"checks": 1, "agreement": "single"}
        return a
    both_healthy = a["health_status"] == "healthy" and b["health_status"] == "healthy"
    same_status = a["health_status"] == b["health_status"]
    if both_healthy or (same_status and _same_dx(a["primary_diagnosis"], b["primary_diagnosis"])):
        level = "agree"
        a["confidence"] = min(a["confidence"], b["confidence"], 92)
    elif _listed(b["primary_diagnosis"], a) or _listed(a["primary_diagnosis"], b):
        level = "partial"
        a["confidence"] = min(a["confidence"], b["confidence"], 70)
    else:
        level = "disagree"
        a["confidence"] = min(a["confidence"], b["confidence"], 55)
        a["needs_expert"] = True
        if b["primary_diagnosis"] and not _listed(b["primary_diagnosis"], a):
            a["other_possibilities"] = (a["other_possibilities"] + [
                {"name": b["primary_diagnosis"], "confidence": min(b["confidence"], 55)}])[:3]
    a["verification"] = {"checks": 2, "agreement": level}
    return a


def analyze(image_bytes, crop="", notes="", lang="en"):
    prov = provider()
    if not prov:
        raise VisionError("NO_KEY")
    if not image_bytes or len(image_bytes) > MAX_BYTES:
        raise VisionError("Image is too large (max 6 MB) or empty.")
    mime = sniff_mime(image_bytes)
    if mime not in ALLOWED_MIME:
        raise VisionError("Unsupported image type. Please upload a JPG, PNG or WebP photo.")
    b64 = base64.b64encode(image_bytes).decode()
    prompt = build_prompt(crop, notes[:600], lang)
    try:
        if prov == "gemini":
            from concurrent.futures import ThreadPoolExecutor
            second = next((m for m in GEMINI_MODELS[1:] if m), None)
            with ThreadPoolExecutor(max_workers=2) as ex:
                fa = ex.submit(_call_gemini, b64, mime, prompt)
                fb = ex.submit(_call_gemini, b64, mime, prompt, [second]) if second else None
                text_a = fa.result()
                result = clean(_extract_json(text_a))
                other = None
                if fb is not None:
                    try:
                        other = clean(_extract_json(fb.result()))
                    except Exception as e:           # second opinion is optional
                        print("[vision] second check failed:", repr(e))
            result = combine(result, other)
        else:
            result = combine(clean(_extract_json(_call_anthropic(b64, mime, prompt))), None)
    except requests.Timeout:
        raise VisionError("The AI took too long to answer. Please try again.")
    except requests.RequestException:
        raise VisionError("Could not reach the AI service. Check the connection and try again.")
    result["provider"] = prov
    return result
