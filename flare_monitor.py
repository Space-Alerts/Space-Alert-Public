import json, os, sys, urllib.request
from datetime import datetime, timezone, timedelta

# ==========================================
# CONFIGURATION (Edit these values anytime)
# ==========================================
MIN_FLARE_CLASS = "M3.0"     # Examples: "C5.0", "M3.0", "M7.5", "X1.0"
MIN_KP_INDEX = 5.0           # 5.0 = G1 Storm, 6.0 = G2, 7.0 = G3, 8.0 = G4, 9.0 = G5
MIN_RADIO_BLACKOUT = 1       # 1 = R1 (M1+), 2 = R2 (M5+), 3 = R3 (X1+), 4 = R4, 5 = R5
COOLDOWN_HOURS = 2           # Minimum hours before re-alerting on the same category
TEST_MODE = False            # Set to True (or run with --test) to send an immediate test alert
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "your-unique-topic-name")
# ==========================================

BASE = "https://services.swpc.noaa.gov"
XRAY_JSON = f"{BASE}/json/goes/primary/xrays-6-hour.json"
XRAY_TXT = f"{BASE}/text/goes-xray-flux-primary.txt"
KP_JSON = f"{BASE}/products/noaa-planetary-k-index.json"
SCALES_JSON = f"{BASE}/products/noaa-scales.json"
STATE_FILE = "state.json"
MULT = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "SpaceWeatherMonitor/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")


def flux_to_class(f: float) -> str:
    for lvl, val in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7)):
        if f >= val:
            return f"{lvl}{f / val:.1f}"
    return f"A{f / 1e-8:.1f}"


def notify(title: str, body: str, tags: str = "sunny,warning", prio: str = "high"):
    url = "https://ntfy.sh" + NTFY_TOPIC.strip()
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
    req.add_header("Title", title)
    req.add_header("Priority", prio)
    req.add_header("Tags", tags)
    urllib.request.urlopen(req, timeout=15)


def load_state() -> dict:
    base = {k: {"last_alert_time": None, "peak_value": 0.0} for k in ("flare", "kp", "radio_blackout")}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            base.update(json.load(f))
    return base


def can_alert(st: dict, val: float, now: datetime, mult: float = 1.5, add: float = 0.0) -> bool:
    last = st.get("last_alert_time")
    peak = float(st.get("peak_value", 0.0))
    if not last or (now - datetime.fromisoformat(last)) > timedelta(hours=COOLDOWN_HOURS):
        return True
    return (mult > 0 and val >= peak * mult) or (add > 0 and val >= peak + add)


def get_xrays() -> list:
    try:
        rows = json.loads(fetch(XRAY_JSON))
        lw = [{"t": r["time_tag"], "f": float(r["flux"])} for r in rows if r.get("energy") == "0.1-0.8nm"]
        if lw:
            return lw[-10:]
    except Exception:
        pass
    out = []
    for line in fetch(XRAY_TXT).splitlines():
        p = line.split()
        if len(p) >= 8 and p[0].isdigit() and float(p[7]) > 0:
            out.append({"t": f"{p[0]}-{p[1]}-{p[2]}T{p[3][:2]}:{p[3][2:]}:00Z", "f": float(p[7])})
    return out[-10:]


def check_flares(state: dict, now: datetime) -> bool:
    clean_min = MIN_FLARE_CLASS.strip().upper()
    letter = clean_min[0]
    thresh = MULT[letter] * float(clean_min[1:])
    recent = get_xrays()
    peak = max(recent, key=lambda x: x["f"])
    lbl = flux_to_class(peak["f"])
    print(f"Flare Peak (10m): {lbl} ({peak['f']:.2e} W/m2) | Threshold: {MIN_FLARE_CLASS}")
    if peak["f"] >= thresh and can_alert(state["flare"], peak["f"], now, mult=1.5):
        notify(f"Solar Flare Alert: {lbl}", f"Class {lbl} flare!\nFlux: {peak['f']:.2e} W/m2\nUTC: {peak['t']}")
        state["flare"] = {"last_alert_time": now.isoformat(), "peak_value": peak["f"]}
        return True
    return False


def check_kp(state: dict, now: datetime) -> bool:
    latest = json.loads(fetch(KP_JSON))[-1]
    if isinstance(latest, dict):
        ts = latest.get("time_tag", "Unknown")
        kp = float(latest.get("Kp") or latest.get("kp_index") or 0)
    else:
        ts = latest[0]
        kp = float(latest[1])
    g = f"G{min(5, int(kp) - 4)}" if kp >= 5 else "G0"
    print(f"Kp Index Latest: Kp {kp:.2f} ({g}) | Threshold: Kp {MIN_KP_INDEX}")
    if kp >= MIN_KP_INDEX and can_alert(state["kp"], kp, now, mult=0, add=1.0):
        notify(f"Geomagnetic Storm: Kp {kp:.1f} ({g})", f"Kp reached {kp:.2f} ({g})\nUTC: {ts}", "zap,earth_americas")
        state["kp"] = {"last_alert_time": now.isoformat(), "peak_value": kp}
        return True
    return False


def check_radio(state: dict, now: datetime) -> bool:
    cur = json.loads(fetch(SCALES_JSON)).get("0", {})
    r_obj = cur.get("R", {})
    r_val = int(r_obj.get("Scale") or 0)
    r_txt = r_obj.get("Text", "none")
    print(f"Radio Blackout: R{r_val} ({r_txt}) | Threshold: R{MIN_RADIO_BLACKOUT}")
    if r_val >= MIN_RADIO_BLACKOUT and can_alert(state["radio_blackout"], r_val, now, mult=0, add=1.0):
        notify(f"Radio Blackout: R{r_val} ({r_txt})", f"Scale R{r_val} ({r_txt})\nUTC: {cur.get('TimeStamp', '')}", "radio,warning")
        state["radio_blackout"] = {"last_alert_time": now.isoformat(), "peak_value": r_val}
        return True
    return False


def main():
    print("Starting Space Weather Monitor...")
    if TEST_MODE or "--test" in sys.argv or os.environ.get("TEST_MODE", "").lower() == "true":
        notify("TEST: Space Weather Monitor", f"Notifications active! Flare>={MIN_FLARE_CLASS}, Kp>={MIN_KP_INDEX}, R>={MIN_RADIO_BLACKOUT}", "white_check_mark", "default")
        print("Test notification sent!")
        return
    now = datetime.now(timezone.utc)
    state = load_state()
    changed = False
    for fn in (check_flares, check_kp, check_radio):
        try:
            changed |= fn(state, now)
        except Exception as e:
            print(f"Error in {fn.__name__}: {e}")
    if changed:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    print("Monitor check completed.")


if __name__ == "__main__":
    main()
