#!/usr/bin/env python3
"""Pretend to be a soil-moisture sensor, so the Soil Sensors page can be tried without any hardware.

The readings are SIMULATED (a field that slowly dries, gets 'irrigated' when it is too dry, and a day/night
temperature swing). They are not real measurements - use this for demos and testing only.

Usage (PowerShell):
    $env:GF_TOKEN = "gfs_...."            # the token shown once when you create the sensor
    python tools/sensor_simulator.py --url https://greenfield-smart-farming-1.onrender.com --count 12 --every 5

    --count N   how many readings to send (default 12)       --every S  seconds between readings (default 5)
    --start M   starting moisture % (default 55)             --dry      start dry (25%) to trigger the alert
Only the standard library is used. The token is read from the GF_TOKEN environment variable (not from the
command line), so it does not end up in your shell history.
"""
import argparse, json, math, os, random, sys, time, urllib.error, urllib.request


def send(url, token, moisture, temp):
    req = urllib.request.Request(url.rstrip("/") + "/api/sensor/ingest",
                                 data=json.dumps({"moisture": round(moisture, 1), "temp": round(temp, 1)}).encode(),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:200]
    except urllib.error.URLError as e:
        return 0, str(e.reason)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--every", type=float, default=5)
    ap.add_argument("--start", type=float, default=55)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    token = os.environ.get("GF_TOKEN", "")
    if not token.startswith("gfs_"):
        sys.exit("Set the GF_TOKEN environment variable to your sensor token (it starts with gfs_).")
    moist = 25.0 if a.dry else a.start
    hour = time.localtime().tm_hour
    for i in range(a.count):
        temp = 27 + 5 * math.sin((hour + i / 4 - 9) / 24 * 2 * math.pi) + random.uniform(-0.4, 0.4)
        moist = max(5.0, moist - random.uniform(0.3, 1.6) + random.uniform(-0.3, 0.3))      # soil dries out
        if moist < 20 and not a.dry:                                                         # 'irrigation' happens
            moist = random.uniform(65, 75)
        status, msg = send(a.url, token, moist, temp)
        print(f"[{i + 1}/{a.count}] moisture {moist:5.1f}%  temp {temp:4.1f}C  ->  HTTP {status} {msg}")
        if status not in (201,):
            sys.exit("Stopped: the server did not accept the reading (check the URL and token).")
        if i < a.count - 1:
            time.sleep(a.every)


if __name__ == "__main__":
    main()
