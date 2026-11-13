import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

# ==========================================
# CONFIGURATION (Edit these values anytime)
# ==========================================
MIN_FLARE_CLASS = "M3.0"     # Examples: "C5.0", "M3.0", "M7.5", "X1.0"
MIN_KP_INDEX = 5.0           # 5.0 = G1 Storm, 6.0 = G2, 7.0 = G3, 8.0 = G4, 9.0 = G5
MIN_RADIO_BLACKOUT = 1       # 1 = R1 (Minor/M1+), 2 = R2 (M5+), 3 = R3 (X1+), 4 = R4, 5 = R5
COOLDOWN_HOURS = 2           # Minimum hours before re-alerting on the same category

TEST_MODE = False            # Set to True (or run with --test) to send an immediate test alert
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "your-unique-topic-name")
# ==========================================

NOAA_XRAY_JSON_URL = "https://noaa.gov"
NOAA_XRAY_TXT_URL = "https://noaa.gov"
NOAA_KP_URL = "https://noaa.gov"
NOAA_SCALES_URL = "https://noaa.gov"

STATE_FILE = "state.json"

CLASS_MULTIPLIERS = {
    "A": 1e-8,
    "B": 1e-7,
    "C": 1e-6,
    "M": 1e-5,
    "X": 1e-4,
}


def fetch_text(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SpaceWeatherMonitor/1.0)",
        "Accept": "*/*",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8")


def fetch_json(url: str):
    return json.loads(fetch_text(url))


def class_to_flux(flare_str: str) -> float:
    cleaned = flare_str.strip().upper()
    letter = cleaned[0]
    number = float(cleaned[1:])
    return CLASS_MULTIPLIERS[letter] * number


def flux_to_class(flux: float) -> str:
    if flux >= 1e-4:
        return f"X{flux / 1e-4:.1f}"
    elif flux >= 1e-5:
        return f"M{flux / 1e-5:.1f}"
    elif flux >= 1e-6:
        return f"C{flux / 1e-6:.1f}"
    elif flux >= 1e-7:
        return f"B{flux / 1e-7:.1f}"
    return f"A{flux / 1e-8:.1f}"


def kp_to_g_scale(kp: float) -> str:
    if kp >= 9.0:
        return "G5 (Extreme)"
    elif kp >= 8.0:
        return "G4 (Severe)"
    elif kp >= 7.0:
        return "G3 (Strong)"
    elif kp >= 6.0:
        return "G2 (Moderate)"
    elif kp >= 5.0:
        return "G1 (Minor)"
    return "G0 (Quiet/Unsettled)"


def send_notification(title: str, body: str, tags: str = "sunny,warning", priority: str = "high"):
    url = f"https://ntfy.sh{NTFY_TOPIC}"
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
    req.add_header("Title", title)
    req.add_header("Priority", priority)
    req.add_header("Tags", tags)
    urllib.request.urlopen(req, timeout=15)


def load_state() -> dict:
    default_state = {
        "flare": {"last_alert_time": None, "peak_value": 0.0},
        "kp": {"last_alert_time": None, "peak_value": 0.0},
        "radio_blackout": {"last_alert_time": None, "peak_value": 0},
    }
    if not os.path.exists(STATE_FILE):
        return default_state
    with open(STATE_FILE, "r") as f:
        data = json.load(f)
    for key in default_state:
        if key not in data:
            data[key] = default_state[key]
    return data


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def should_trigger(category_state: dict, current_val: float, now: datetime, escalation_factor: float = 1.5) -> bool:
    last_str = category_state.get("last_alert_time")
    last_peak = float(category_state.get("peak_value", 0.0))

    if not last_str:
        return True

    last_time = datetime.fromisoformat(last_str)
    if (now - last_time) > timedelta(hours=COOLDOWN_HOURS):
        return True
    if escalation_factor and current_val >= (last_peak * escalation_factor):
        return True
    return False


def get_recent_xray_readings() -> list:
    try:
        data = fetch_json(NOAA_XRAY_JSON_URL)
        long_wave = [
            {"time_tag": row["time_tag"], "flux": float(row["flux"])}
            for row in data
            if row.get("energy") == "0.1-0.8nm" and row.get("flux") is not None
        ]
        if long_wave:
            return long_wave[-10:]
    except Exception:
        pass

    raw_txt = fetch_text(NOAA_XRAY_TXT_URL)
    readings = []
    for line in raw_txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(":"):
            continue
        parts = line.split()
        if len(parts) >= 8:
            try:
                year, month, day, hhmm = parts[0], parts[1], parts[2], parts[3]
                long_flux = float(parts[7])
                if long_flux > 0:
                    time_tag = f"{year}-{month}-{day}T{hhmm[:2]}:{hhmm[2:]}:00Z"
                    readings.append({"time_tag": time_tag, "flux": long_flux})
            except ValueError:
                continue
    return readings[-10:]


def check_solar_flares(state: dict, now: datetime) -> bool:
    threshold_flux = class_to_flux(MIN_FLARE_CLASS)
    recent = get_recent_xray_readings()
    if not recent:
        print("No X-ray 0.1-0.8nm data available.")
        return False

    peak_reading = max(recent, key=lambda x: x["flux"])
    current_flux = peak_reading["flux"]
    flare_label = flux_to_class(current_flux)

    print(f"Flare Peak (10m): {flare_label} ({current_flux:.2e} W/m2) | Threshold: {MIN_FLARE_CLASS}")

    if current_flux >= threshold_flux and should_trigger(state["flare"], current_flux, now, escalation_factor=1.5):
        send_notification(
            title=f"Solar Flare Alert: {flare_label}",
            body=(
                f"Class {flare_label} solar flare detected!\n"
                f"Peak X-Ray Flux: {current_flux:.2e} W/m2\n"
                f"Time (UTC): {peak_reading['time_tag']}"
            ),
            tags="sunny,warning",
        )
        state["flare"]["last_alert_time"] = now.isoformat()
        state["flare"]["peak_value"] = current_flux
        print(f"-> Sent Solar Flare alert ({flare_label})!")
        return True
    return False


def check_geomagnetic_kp(state: dict, now: datetime) -> bool:
    data = fetch_json(NOAA_KP_URL)
    if not data:
        print("No Kp index data available.")
        return False

    latest = data[-1]
    if isinstance(latest, dict):
        timestamp = latest.get("time_tag", "Unknown")
        current_kp = float(latest.get("Kp") or latest.get("kp_index") or 0.0)
    else:
        timestamp = latest[0]
        current_kp = float(latest[1])

    g_label = kp_to_g_scale(current_kp)
    g_short = g_label.split()[0]
    print(f"Kp Index Latest: Kp {current_kp:.2f} ({g_label}) | Threshold: Kp {MIN_KP_INDEX}")

    last_str = state["kp"].get("last_alert_time")
    last_kp = float(state["kp"].get("peak_value", 0.0))
    cooldown_ok = not last_str or (now - datetime.fromisoformat(last_str)) > timedelta(hours=COOLDOWN_HOURS)
    escalated = current_kp >= (last_kp + 1.0)

    if current_kp >= MIN_KP_INDEX and (cooldown_ok or escalated):
        send_notification(
            title=f"Geomagnetic Storm: Kp {current_kp:.1f} ({g_short})",
            body=(
                f"Geomagnetic activity reached {g_label}.\n"
                f"Planetary Kp Index: {current_kp:.2f}\n"
                f"Window (UTC): {timestamp}"
            ),
            tags="zap,earth_americas",
        )
        state["kp"]["last_alert_time"] = now.isoformat()
        state["kp"]["peak_value"] = current_kp
        print(f"-> Sent Geomagnetic Storm alert (Kp {current_kp})!")
        return True
    return False


def check_radio_blackouts(state: dict, now: datetime) -> bool:
    data = fetch_json(NOAA_SCALES_URL)
    current_conditions = data.get("0", {})
    r_data = current_conditions.get("R", {})
    r_scale = int(r_data.get("Scale") or 0)
    r_text = r_data.get("Text", "none")

    print(f"Radio Blackout Current: R{r_scale} ({r_text}) | Threshold: R{MIN_RADIO_BLACKOUT}")

    last_str = state["radio_blackout"].get("last_alert_time")
    last_r = int(state["radio_blackout"].get("peak_value", 0))
    cooldown_ok = not last_str or (now - datetime.fromisoformat(last_str)) > timedelta(hours=COOLDOWN_HOURS)
    escalated = r_scale > last_r

    if r_scale >= MIN_RADIO_BLACKOUT and (cooldown_ok or escalated):
        send_notification(
            title=f"Radio Blackout Alert: R{r_scale} ({r_text.capitalize()})",
            body=(
                f"NOAA Radio Blackout Scale reached R{r_scale} ({r_text}).\n"
                f"High-frequency (HF) radio degradation on the sunlit side of Earth.\n"
                f"Observed: {current_conditions.get('DateStamp', '')} {current_conditions.get('TimeStamp', '')} UTC"
            ),
            tags="radio,warning",
        )
        state["radio_blackout"]["last_alert_time"] = now.isoformat()
        state["radio_blackout"]["peak_value"] = r_scale
        print(f"-> Sent Radio Blackout alert (R{r_scale})!")
        return True
    return False


def run_test_mode():
    print("Running in TEST MODE...")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    send_notification(
        title="TEST: Space Weather Monitor Active",
        body=(
            f"Push notifications are working!\n"
            f"Thresholds -> Flare: {MIN_FLARE_CLASS} | Kp: {MIN_KP_INDEX} | Radio: R{MIN_RADIO_BLACKOUT}\n"
            f"Sent at: {now_str}"
        ),
        tags="white_check_mark,satellite",
        priority="default",
    )
    print("Test notification sent successfully via ntfy.sh!")


def main():
    print("Starting Space Weather Monitor...")
    is_test = TEST_MODE or ("--test" in sys.argv) or (os.environ.get("TEST_MODE", "").lower() == "true")
    if is_test:
        run_test_mode()
        return

    now = datetime.now(timezone.utc)
    state = load_state()
