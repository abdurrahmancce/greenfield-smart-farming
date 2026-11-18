"""Measure the REAL accuracy of GreenField's photo diagnosis.

Usage (PowerShell, from the project folder, with GEMINI_API_KEY set):
    python tools/eval_disease.py path\\to\\images [--limit 40] [--out results.csv] [--pause 4]

The free AI quota often answers "busy" - the script waits and retries each photo (up to 4 times)
and writes every result to a CSV, so the run can be repeated safely. Photos that still fail are
COUNTED and reported, never silently dropped, so the accuracy number is honest.

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
    import csv, time
    root = sys.argv[1]
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
    limit, out, pause = int(arg("--limit", 40)), arg("--out", "eval-results.csv"), float(arg("--pause", 4))
    items = []
    for lab in sorted(os.listdir(root)):
        d = os.path.join(root, lab)
        if os.path.isdir(d):
            fs = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
            items += [(lab, f) for f in fs]
    random.seed(1); random.shuffle(items); items = items[:limit]
    done = {}
    if os.path.exists(out):                                   # resume: skip photos already answered
        for r in csv.DictReader(open(out, encoding="utf-8")):
            if r["status"] == "answered": done[r["file"]] = r
    rows = list(done.values()); errors = 0
    for i, (lab, f) in enumerate(items, 1):
        if f in done: continue
        res = None
        for attempt in range(4):
            try:
                res = vision.analyze(open(f, "rb").read(), "", "", "en"); break
            except Exception as e:
                print(f"[{i}] retry {attempt + 1}/4: {e}"); time.sleep(pause * (attempt + 1) * 2)
        if res is None:
            errors += 1; rows.append({"file": f, "true": lab, "status": "error", "correct": "", "diagnosis": "", "confidence": "", "agreement": ""}); continue
        c = correct(lab, res)
        diag = res["primary_diagnosis"] or res["health_status"]
        rows.append({"file": f, "true": lab, "status": "answered", "correct": int(c), "diagnosis": diag,
                     "confidence": res["confidence"], "agreement": res.get("verification", {}).get("agreement", "")})
        print(f"[{i}/{len(items)}] {'OK ' if c else 'BAD'} true={lab} -> {diag} ({res['confidence']}%)")
        time.sleep(pause)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "true", "status", "correct", "diagnosis", "confidence", "agreement"]); w.writeheader(); w.writerows(rows)
    ans = [r for r in rows if r["status"] == "answered"]
    errors = len(rows) - len(ans)
    ok = sum(int(r["correct"]) for r in ans); n = len(ans) or 1
    # 95% Wilson interval: with few photos the true accuracy is uncertain, and that matters
    z = 1.96; p = ok / n
    lo = (p + z*z/(2*n) - z*((p*(1-p)/n + z*z/(4*n*n)) ** .5)) / (1 + z*z/n)
    hi = (p + z*z/(2*n) + z*((p*(1-p)/n + z*z/(4*n*n)) ** .5)) / (1 + z*z/n)
    print(f"\nPHOTOS: {len(rows)} tried, {len(ans)} answered, {errors} failed (quota/network)")
    print(f"TOP-1 ACCURACY (answered only): {ok}/{n} = {100*p:.0f}%   (95% range {100*lo:.0f}-{100*hi:.0f}%)")
    buckets = collections.defaultdict(lambda: [0, 0])
    for r in ans:
        cf = float(r["confidence"] or 0); b = "80-100" if cf >= 80 else "60-79" if cf >= 60 else "0-59"
        buckets[b][0] += 1; buckets[b][1] += int(r["correct"])
    print("\nCalibration (shown % vs real hit-rate):")
    for b in ("80-100", "60-79", "0-59"):
        t, c = buckets[b]
        print(f"  shown {b:>6}%: {t:3d} photos, actually right {100*c/t:.0f}%" if t else f"  shown {b:>6}%: no photos")
    per = collections.defaultdict(lambda: [0, 0])
    for r in ans: per[r["true"]][0] += 1; per[r["true"]][1] += int(r["correct"])
    print("\nPer disease (weakest first):")
    for lab, (t, c) in sorted(per.items(), key=lambda kv: kv[1][1] / kv[1][0]):
        print(f"  {lab:<36} {c}/{t}")

if __name__ == "__main__": main()
