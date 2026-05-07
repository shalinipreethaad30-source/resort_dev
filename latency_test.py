"""
Vibe Munnar — TV Page Full Service Latency Test
================================================
Tests every API call the TV page makes when a guest interacts with each tile.

Usage:
  python test_latency.py
  python test_latency.py --host 192.168.1.10:8000
  python test_latency.py --room 205
  python test_latency.py --service food spa
  python test_latency.py --samples 3
  python test_latency.py --json

Available --service values:
  page, food, dine, spa, bar, entertainment,
  room_service, gallery, activities, live_tv,
  bookings, wifi, websocket, all  (default: all)
"""

import asyncio, time, argparse, sys, json
from datetime import datetime

try:
    import httpx
except ImportError:
    import subprocess
    print("Installing httpx..."); subprocess.check_call([sys.executable,"-m","pip","install","httpx","--quiet"])
    import httpx

try:
    import websockets
except ImportError:
    import subprocess
    print("Installing websockets..."); subprocess.check_call([sys.executable,"-m","pip","install","websockets","--quiet"])
    import websockets


# ── colours ───────────────────────────────────────────────────────────────────
RST,BOLD,DIM = "\033[0m","\033[1m","\033[2m"
GRN,YLW,RED,CYN,MAG,WHT = "\033[32m","\033[33m","\033[31m","\033[36m","\033[35m","\033[97m"


# ── service map — every tile / button on the TV page ─────────────────────────
SERVICES = {
    "page": [
        ("GET", "/tv/{room}",              "TV guest page"),
        ("GET", "/api/room-data/{room}",   "guest name + welcome message"),
        ("GET", "/api/current-theme",      "active theme"),
        ("GET", "/api/activities",         "today's experiences panel"),
        ("WS",  "/ws/tv-status",           "WebSocket TV status feed"),
    ],
    "food": [
        ("GET", "/api/menu-card",                        "menu card image"),
        ("GET", "/api/food-items?category=breakfast",    "food — breakfast"),
        ("GET", "/api/food-items?category=lunch",        "food — lunch"),
        ("GET", "/api/food-items?category=dinner",       "food — dinner"),
        ("GET", "/api/food-items?category=snacks",       "food — snacks"),
        ("GET", "/api/food-items?category=desserts",     "food — desserts"),
        ("GET", "/api/food-items?category=drinks",       "food — drinks"),
        ("GET", "/api/category-covers/food",             "food cover images"),
    ],
    "dine": [
        ("GET", "/api/dine-items",                       "all dine-in packages"),
        ("GET", "/api/dine-items?occasion=romantic",     "dine — romantic"),
        ("GET", "/api/dine-items?occasion=birthday",     "dine — birthday"),
        ("GET", "/api/dine-items?occasion=anniversary",  "dine — anniversary"),
        ("GET", "/api/dine-items?occasion=business",     "dine — business"),
        ("GET", "/api/dine-items?occasion=family",       "dine — family"),
        ("GET", "/api/category-covers/dine",             "dine cover images"),
    ],
    "spa": [
        ("GET", "/api/spa-items",                        "all spa treatments"),
        ("GET", "/api/spa-items?category=massage",       "spa — massage"),
        ("GET", "/api/spa-items?category=facial",        "spa — facial"),
        ("GET", "/api/spa-items?category=body",          "spa — body"),
        ("GET", "/api/category-covers/spa",              "spa cover images"),
    ],
    "bar": [
        ("GET", "/api/bar-items",                        "all bar items"),
        ("GET", "/api/bar-items?category=alcoholic",     "bar — alcoholic"),
        ("GET", "/api/bar-items?category=non-alcoholic", "bar — non-alcoholic"),
        ("GET", "/api/category-covers/bar",              "bar cover images"),
    ],
    "entertainment": [
        ("GET", "/api/entertainment-items",              "entertainment items"),
        ("GET", "/api/category-covers/entertainment",    "entertainment covers"),
    ],
    "room_service": [
        ("GET", "/api/room-service-items",               "room service items"),
    ],
    "gallery": [
        ("GET", "/api/gallery-items",                    "gallery images"),
    ],
    "activities": [
        ("GET", "/api/activities",                       "activities / experiences"),
    ],
    "live_tv": [
        ("GET", "/live-tv",                              "live TV page"),
    ],
    "bookings": [
        ("GET", "/api/room-data/{room}",                 "room + booking info"),
    ],
    "wifi": [
        ("GET", "/api/room-data/{room}",                 "room data (wifi details)"),
    ],
    "websocket": [
        ("WS",  "/ws/tv-status",                         "WebSocket TV status feed"),
    ],
}

TILE_LABELS = {
    "page":          "TV PAGE LOAD",
    "food":          "FOOD MENU tile",
    "dine":          "DINE IN tile",
    "spa":           "SPA & WELLNESS tile",
    "bar":           "BAR tile",
    "entertainment": "ENTERTAINMENTS tile",
    "room_service":  "ROOM SERVICE tile",
    "gallery":       "GALLERY tile",
    "activities":    "TODAY'S EXPERIENCES panel",
    "live_tv":       "LIVE TV button",
    "bookings":      "MY BOOKINGS button",
    "wifi":          "WIFI TAP banner",
    "websocket":     "WEBSOCKET feed",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%I:%M:%S %p").lower()

def colour_ms(ms):
    if ms is None: return f"{RED}ERROR{RST}"
    s = f"{ms:.2f}ms"
    if ms < 100:  return f"{GRN}{s}{RST}"
    if ms < 400:  return f"{YLW}{s}{RST}"
    return f"{RED}{s}{RST}"

def log_line(etype, ms, path, status=None, note=None):
    cols = {"API_CALL":CYN,"SERVER_TIME":GRN,"WS_CONNECT":YLW,"WS_INTERVAL":YLW}
    col  = cols.get(etype, RED)
    print(
        f"  {DIM}{ts()}{RST}  "
        f"{col}{etype:<13}{RST}  "
        f"{colour_ms(ms):<28}  "
        f"{WHT}{path}{RST}"
        + (f"  {DIM}[{status}]{RST}" if status else "")
        + (f"  {DIM}{note}{RST}"     if note   else "")
    )


# ── probes ────────────────────────────────────────────────────────────────────

async def probe_http(client, base, path, label, out):
    t0 = time.perf_counter()
    try:
        r      = await client.get(base + path, follow_redirects=True)
        api_ms = (time.perf_counter() - t0) * 1000
        srv_h  = r.headers.get("x-process-time")
        srv_ms = float(srv_h) * 1000 if srv_h else None
        log_line("API_CALL",    api_ms, path, r.status_code, label)
        if srv_ms: log_line("SERVER_TIME", srv_ms, path)
        out.append({"path":path,"label":label,"api_ms":round(api_ms,2),
                    "srv_ms":round(srv_ms,2) if srv_ms else None,
                    "status":r.status_code,"ok":200<=r.status_code<400})
    except Exception as e:
        log_line("HTTP_ERROR", None, path, note=str(e)[:70])
        out.append({"path":path,"label":label,"api_ms":None,"ok":False,"error":str(e)})

async def probe_ws(base, path, label, out):
    t0 = time.perf_counter()
    try:
        async with websockets.connect(base+path, open_timeout=6) as ws:
            await asyncio.wait_for(ws.recv(), timeout=8)
            c_ms = (time.perf_counter()-t0)*1000
            t1   = time.perf_counter()
            await asyncio.wait_for(ws.recv(), timeout=12)
            i_ms = (time.perf_counter()-t1)*1000
            log_line("WS_CONNECT",  c_ms, path, note=label)
            log_line("WS_INTERVAL", i_ms, path, note="push interval (~5000ms expected)")
            out.append({"path":path,"label":label,"api_ms":round(c_ms,2),"interval_ms":round(i_ms,2),"ok":True})
    except asyncio.TimeoutError:
        log_line("WS_TIMEOUT", None, path, note="no message within timeout")
        out.append({"path":path,"label":label,"api_ms":None,"ok":False})
    except Exception as e:
        log_line("WS_ERROR",   None, path, note=str(e)[:70])
        out.append({"path":path,"label":label,"api_ms":None,"ok":False,"error":str(e)})


# ── summary ───────────────────────────────────────────────────────────────────

def print_summary(results):
    passed = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    times  = [r["api_ms"] for r in results if r.get("api_ms")]

    print(f"\n  {BOLD}{'─'*60}{RST}")
    print(f"  {BOLD}SUMMARY{RST}")
    print(f"  {'─'*60}")
    print(f"  Total     : {BOLD}{len(results)}{RST}  requests")
    print(f"  {GRN}Passed{RST}    : {len(passed)}")
    print(f"  {RED}Failed{RST}    : {len(failed)}")
    if times:
        avg = sum(times)/len(times)
        print(f"  Avg       : {colour_ms(avg)}")
        print(f"  Fastest   : {colour_ms(min(times))}")
        print(f"  Slowest   : {colour_ms(max(times))}")

        # per-service breakdown
        by_svc = {}
        for r in results:
            s = r.get("service","?")
            by_svc.setdefault(s,[])
            if r.get("api_ms"): by_svc[s].append(r["api_ms"])
        print(f"\n  {BOLD}Per-tile avg:{RST}")
        for svc, t in sorted(by_svc.items()):
            if t:
                a   = sum(t)/len(t)
                bar = "█" * min(24, int(a/15))
                print(f"    {TILE_LABELS.get(svc,svc):<30}  {colour_ms(a):<28}  {DIM}{bar}{RST}")

    if failed:
        print(f"\n  {RED}{BOLD}Failed endpoints:{RST}")
        for r in failed:
            print(f"    {RED}✗{RST}  {r['path']:<45}  {DIM}{r.get('label','')}{RST}")

    avg_val  = sum(times)/len(times) if times else 9999
    fail_pct = len(failed)/max(len(results),1)
    if fail_pct == 0 and avg_val < 200:   grade,gcol,note = "PASS",GRN,"all services healthy"
    elif fail_pct == 0 and avg_val < 500: grade,gcol,note = "PASS",GRN,"healthy but slow — check DB indexes"
    elif fail_pct <= 0.1:                 grade,gcol,note = "WARN",YLW,"a few endpoints failed"
    else:                                 grade,gcol,note = "FAIL",RED,"multiple services unreachable"

    print(f"\n  Grade: {gcol}{BOLD} {grade} {RST}  {DIM}{note}{RST}")
    print(f"  {'─'*60}\n")


# ── runner ────────────────────────────────────────────────────────────────────

async def run(host, room, service_keys, samples):
    http_base = f"http://{host}"
    ws_base   = f"ws://{host}"
    selected  = list(SERVICES.keys()) if "all" in service_keys else service_keys
    unknown   = [s for s in selected if s not in SERVICES]
    if unknown:
        print(f"{RED}Unknown service(s): {', '.join(unknown)}{RST}")
        print(f"Valid: {', '.join(SERVICES)} all"); sys.exit(1)

    total = sum(len(SERVICES[s]) for s in selected) * samples
    print(f"\n  {BOLD}Vibe Munnar — TV Page Latency Test{RST}")
    print(f"  host: {CYN}{host}{RST}   room: {CYN}{room}{RST}   samples: {CYN}{samples}{RST}   total calls: {CYN}{total}{RST}")
    print(f"  {'─'*60}")
    print(f"  {DIM}{'TIME':<14}{'TYPE':<15}{'LATENCY':<16}PATH{RST}")
    print(f"  {'─'*60}")

    all_results = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for svc in selected:
            print(f"\n  {BOLD}{MAG}▸ {TILE_LABELS.get(svc, svc.upper())}{RST}")
            for s in range(samples):
                if samples > 1: print(f"  {DIM}  sample {s+1}/{samples}{RST}")
                for method, tmpl, label in SERVICES[svc]:
                    path  = tmpl.replace("{room}", str(room))
                    local = []
                    if method == "WS":
                        await probe_ws(ws_base, path, label, local)
                    else:
                        await probe_http(client, http_base, path, label, local)
                    for item in local:
                        item["service"] = svc
                    all_results.extend(local)
                    await asyncio.sleep(0.06)

    print_summary(all_results)
    return all_results


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Vibe Munnar TV page — per-service latency tester",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--host",    default="localhost:8000")
    p.add_argument("--room",    default="101")
    p.add_argument("--service", default=["all"], nargs="+", metavar="SERVICE")
    p.add_argument("--samples", default=1, type=int)
    p.add_argument("--json",    action="store_true")
    args = p.parse_args()

    results = asyncio.run(run(args.host, args.room, args.service, args.samples))

    if args.json:
        with open("latency_results.json","w") as f:
            json.dump(results, f, indent=2, default=str)
        print("  Results saved → latency_results.json\n")

if __name__ == "__main__":
    main()