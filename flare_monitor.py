import json
import os
from datetime import datetime, timezone, timedelta
import urllib.request

# ==========================================
# CONFIGURATION (Edit these values anytime)
# ==========================================
MIN_FLARE_CLASS = "M3.0"  # Examples: "C5.0", "M3.0", "M7.5", "X1.0"
COOLDOWN_HOURS = 2        # Minimum hours before alerting again (unless a much stronger peak occurs)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "your-unique-topic-name")
# ==========================================

NOAA_XRAY_URL = "https://noaa.gov"
STATE_FILE = "state.json"

CLASS_MULTIPLIERS = {
    "A": 1e-8,
    "B": 1e-7,
    "C": 1e-6,
    "M": 1e-5,
    "X": 1e-4,
}

def class_to_flux(flare_str: str) -> float:
    letter = flare_str[0].upper()
    number = float(flare_str[1:])
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

def send_notification(flare_label: str, flux: float, timestamp: str):
    url = f"https://ntfy.sh{NTFY_TOPIC}"
    message = (
        f"Solar Flare Alert: {flare_label} detected!\n"
        f"Peak X-Ray Flux: {flux:.2e} W/m²\n"
        f"Time (UTC): {timestamp}"
    ).encode("utf-8")
    
    req = urllib.request.Request(url, data=message, method="POST")
    req.add_header("Title", f"Solar Flare {flare_label}")
    req.add_header("Priority", "high")
    req.add_header("Tags", "sunny,warning")
    urllib.request.urlopen(req)

def main():
    threshold_flux = class_to_flux(MIN_FLARE_CLASS)

    # Fetch live NOAA GOES X-ray data
    with urllib.request.urlopen(NOAA_XRAY_URL, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))

    # Filter for long-wavelength channel (0.1-0.8nm) used for flare classification
    long_wave = [row for row in data if row.get("energy") == "0.1-0.8nm"]
    if not long_wave:
        print("No 0.1-0.8nm data available.")
        return

    # Check the last 10 minutes of readings
    recent_readings = long_wave[-10:]
    peak_reading = max(recent_readings, key=lambda x: x["flux"])
    current_flux = float(peak_reading["flux"])
    flare_label = flux_to_class(current_flux)

    print(f"Current peak (last 10m): {flare_label} ({current_flux:.2e} W/m²) | Threshold: {MIN_FLARE_CLASS}")

    if current_flux < threshold_flux:
        return

    # Load previous alert state
    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    now = datetime.now(timezone.utc)
    last_alert_str = state.get("last_alert_time")
    last_peak = float(state.get("peak_flux_in_event", 0.0))

    should_alert = False
    if not last_alert_str:
        should_alert = True
    else:
        last_alert_time = datetime.fromisoformat(last_alert_str)
        # Alert if cooldown has passed OR if the flare intensified by at least 50%
        if (now - last_alert_time) > timedelta(hours=COOLDOWN_HOURS):
            should_alert = True
        elif current_flux >= (last_peak * 1.5):
            should_alert = True

    if should_alert:
        send_notification(flare_label, current_flux, peak_reading["time_tag"])
        state["last_alert_time"] = now.isoformat()
        state["peak_flux_in_event"] = current_flux
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        print(f"Alert sent for {flare_label}!")
    else:
        print("Threshold met, but alert suppressed due to active cooldown.")

if __name__ == "__main__":
    main()
