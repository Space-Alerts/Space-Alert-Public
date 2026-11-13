# Space Weather Alert Monitor

Automated push notifications for **Solar Flares**, **Geomagnetic Storms (Kp Index)**, and **HF Radio Blackouts** using live data from the [NOAA Space Weather Prediction Center (SWPC)](https://spaceweather.gov), **GitHub Actions**, and **[ntfy.sh](https://ntfy.sh)**.

---

## How It Works

1. **Scheduled Checks:** GitHub Actions runs `flare_monitor.py` every **5 minutes** via `.github/workflows/monitor.yml`.
2. **Live NOAA Data:** The script fetches the latest X-ray flux, planetary Kp index, and NOAA Space Weather Scales.
3. **Smart Cooldowns:** `state.json` records the timestamp and peak value of each alert category so your phone is not spammed during prolonged solar events. It only re-alerts if the cooldown window has passed or the event intensifies significantly.
4. **Push Notifications:** When a threshold is crossed, a high-priority push notification is sent straight to your phone via `ntfy.sh`.

---

## Repository Files

* `flare_monitor.py` — Main monitoring script with threshold settings, NOAA data parsers, cooldown logic, and `TEST_MODE`.
* `state.json` — Automatically updated by GitHub Actions to track the last alert time and peak value for each hazard.
* `.github/workflows/monitor.yml` — GitHub Actions workflow schedule and one-click manual test runner.

---

## Configuration

To change your alert thresholds or cooldown period, open `flare_monitor.py` on GitHub, click the **pencil (edit)** icon, and update the variables at the top of the file:

```python
MIN_FLARE_CLASS = "M3.0"     # Examples: "C5.0", "M3.0", "M7.5", "X1.0"
MIN_KP_INDEX = 5.0           # 5.0 = G1 Storm, 6.0 = G2, 7.0 = G3, 8.0 = G4, 9.0 = G5
MIN_RADIO_BLACKOUT = 1       # 1 = R1 (M1+), 2 = R2 (M5+), 3 = R3 (X1+), 4 = R4, 5 = R5
COOLDOWN_HOURS = 2           # Minimum hours before re-alerting on the same category
```

### Reference Scales
* **Solar Flares (X-Ray Peak):** `C` (Minor) < `M1.0–M4.9` (Moderate) < `M5.0–M9.9` (Strong) < `X1.0+` (Severe/Extreme)
* **Geomagnetic Storms:** `Kp 5` (G1) · `Kp 6` (G2) · `Kp 7` (G3) · `Kp 8` (G4) · `Kp 9` (G5)
* **Radio Blackouts:** `R1` (Minor, M1+) · `R2` (Moderate, M5+) · `R3` (Strong, X1+) · `R4` (Severe, X10+) · `R5` (Extreme, X20+)

---

## Running a Manual Test Notification

1. Go to the **Actions** tab in this repository.
2. Select **Space Weather Monitor** from the left sidebar.
3. Click **Run workflow**.
4. Change **Send a test push notification right now?** to **`true`** and click **Run workflow**.
5. A test alert will arrive on your phone within ~15 seconds.

---

## Maintenance Notes

* **Secret Topic Name:** Your `ntfy.sh` topic is stored securely under **Settings > Secrets and variables > Actions** as `NTFY_TOPIC`. Store only the topic name itself (not the full URL).
* **60-Day GitHub Actions Pause:** GitHub automatically pauses scheduled workflows on public repositories if no commits are made for **60 days** (note that automated updates to `state.json` count as commits whenever an alert triggers). If you ever receive an email saying the workflow was disabled due to inactivity, go to the **Actions** tab and click **Enable workflow**.
