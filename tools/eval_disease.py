"""Measure the REAL accuracy of GreenField's photo diagnosis.

Usage (PowerShell, from the project folder, with GEMINI_API_KEY set):
    python tools/eval_disease.py path\\to\\images [--limit 40]

Folder layout: one sub-folder per true label, e.g.
    images/Tomato_early_blight/*.jpg
    images/Tomato_healthy/*.jpg
    images/Potato_late_blight/*.jpg
(PlantVillage dataset from Kaggle works as-is; use ~10-20 photos per class.)

It prints top-1 accuracy and a calibration table: when the app says "80-100%",
how often is it actually right? That is the true meaning of the percentage.
"""
import os, sys, re, random, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import vision

def norm(t): return set(re.findall(r"[a-z]{3,}", re.sub(r"\([^)]*\)", " ", t.lower().replace("_", " "))))
STOP = {"leaf","disease","plant","the","and","spot","tomato","potato","grape","apple","corn","rice","pepper","bell","maize"}

def correct(label, res):
    """Strict: every distinctive word of the true label must appear in the AI's diagnosis
    (so 'Late blight' is NOT accepted for 'Early blight')."""
    if "healthy" in label.lower(): return res["health_status"] == "healthy"
    if res["health_status"] == "healthy": return False
    need = norm(label) - STOP
    got = norm(res["primary_diagnosis"])
    if "turcicum" in got: got.add("northern")            # same disease, other name
    if "puccinia" in got: got.add("rust")
    return bool(need) and need <= got

def main():
    root = sys.argv[1]
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 40
    items = []
    for lab in sorted(os.listdir(root)):
        d = os.path.join(root, lab)
        if os.path.isdir(d):
            fs = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
            items += [(lab, f) for f in fs]
    random.seed(1); random.shuffle(items); items = items[:limit]
    buckets = collections.defaultdict(lambda: [0, 0]); ok = 0
    for i, (lab, f) in enumerate(items, 1):
        try:
            res = vision.analyze(open(f, "rb").read(), "", "", "en")
        except Exception as e:
            print(f"[{i}] ERROR {e}"); continue
        c = correct(lab, res); ok += c
        b = "80-100" if res["confidence"] >= 80 else "60-79" if res["confidence"] >= 60 else "0-59"
        buckets[b][0] += 1; buckets[b][1] += c
        print(f"[{i}/{len(items)}] {'OK ' if c else 'BAD'} true={lab} -> {res['primary_diagnosis'] or res['health_status']} ({res['confidence']}%, {res.get('verification',{}).get('agreement')})")
    n = sum(v[0] for v in buckets.values()) or 1
    print(f"\nTOP-1 ACCURACY: {ok}/{n} = {100*ok/n:.0f}%\n\nCalibration (shown % vs real hit-rate):")
    for b in ("80-100", "60-79", "0-59"):
        t, c = buckets[b]
        print(f"  shown {b:>6}%: {t:3d} photos, actually right {100*c/t:.0f}%" if t else f"  shown {b:>6}%: no photos")

if __name__ == "__main__": main()
