import os
import csv
import json
from datetime import datetime, timedelta
from garminconnect import Garmin

email = os.environ["GARMIN_EMAIL"]
password = os.environ["GARMIN_PASSWORD"]

client = Garmin(email, password)
client.login()

# ── Mode detection ────────────────────────────────────────────────────────────
# Full refetch on first Sunday of each month or if FULL_REFRESH env var is set
today = datetime.today()
is_full_refresh = (today.weekday() == 6 and today.day <= 7) or os.environ.get("FULL_REFRESH") == "true"
print(f"Mode: {'FULL REFRESH' if is_full_refresh else 'INCREMENTAL'}")

# ── Load existing data ────────────────────────────────────────────────────────
existing_runs = []
existing_strength = []

if os.path.exists("runs.csv") and not is_full_refresh:
    with open("runs.csv", "r", encoding="utf-8") as f:
        existing_runs = list(csv.DictReader(f))

if os.path.exists("strength.csv") and not is_full_refresh:
    with open("strength.csv", "r", encoding="utf-8") as f:
        existing_strength = list(csv.DictReader(f))

# Find cutoff date for incremental fetch
last_run_date = existing_runs[0]["date"] if existing_runs else "2000-01-01"
last_strength_date = existing_strength[0]["date"] if existing_strength else "2000-01-01"
cutoff = min(last_run_date, last_strength_date)
print(f"Fetching activities since: {cutoff}")

# ── Fetch activities ──────────────────────────────────────────────────────────
new_activities = []
batch_size = 100
start = 0

while True:
    batch = client.get_activities(start, batch_size)
    if not batch:
        break
    # In incremental mode, stop when we reach activities older than cutoff
    if not is_full_refresh:
        batch = [a for a in batch if a.get("startTimeLocal", "")[:10] >= cutoff]
        new_activities.extend(batch)
        if len(batch) < batch_size:
            break
    else:
        new_activities.extend(batch)
        if len(batch) < batch_size:
            break
    start += batch_size

print(f"Fetched {len(new_activities)} activities from Garmin")

# ── Filter functions ──────────────────────────────────────────────────────────
def is_running(a):
    type_key = a.get("activityType", {}).get("typeKey", "").lower()
    return type_key in ["running", "treadmill_running", "trail_running"]

def is_treadmill(a):
    return a.get("activityType", {}).get("typeKey", "").lower() == "treadmill_running"

def is_strength(a):
    type_key = a.get("activityType", {}).get("typeKey", "").lower()
    return type_key in ["strength_training", "fitness_equipment"]

new_running = [a for a in new_activities if is_running(a)]
new_strength = [a for a in new_activities if is_strength(a)]

# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt_time(seconds):
    if not seconds:
        return ""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}"

def calc_pace(duration_s, distance_m):
    if not distance_m or not duration_s:
        return ""
    pace_sec = (duration_s / 60) / (distance_m / 1000)
    pace_min = int(pace_sec)
    pace_s = int((pace_sec - pace_min) * 60)
    return f"{pace_min}:{pace_s:02d}"

def speed_to_pace(speed_mps):
    if not speed_mps or speed_mps == 0:
        return ""
    pace_sec = 1000 / speed_mps / 60
    pace_min = int(pace_sec)
    pace_s = int((pace_sec - pace_min) * 60)
    return f"{pace_min}:{pace_s:02d}"

def get_week(date):
    return date.isocalendar()[:2]

# ── Build run records ─────────────────────────────────────────────────────────
run_fieldnames = [
    "date", "name", "type", "distance_km", "moving_time", "elapsed_time",
    "avg_hr", "max_hr", "elevation_gain_m", "elevation_loss_m",
    "min_elevation_m", "max_elevation_m", "avg_pace_min_km", "max_pace_min_km",
    "avg_cadence", "calories", "training_load",
    "aerobic_training_effect", "anaerobic_training_effect", "vo2max_estimate"
]

def build_run_row(a):
    dist = a.get("distance", 0)
    duration = a.get("movingDuration", 0)
    elev_gain = a.get("elevationGain", "")
    elev_loss = a.get("elevationLoss", "")
    min_elev = a.get("minElevation", "")
    max_elev = a.get("maxElevation", "")
    max_speed = a.get("maxSpeed", None)
    cadence = a.get("averageRunningCadenceInStepsPerMinute", "")

    return {
        "date": a.get("startTimeLocal", "")[:10],
        "name": a.get("activityName", ""),
        "type": "treadmill" if is_treadmill(a) else "outdoor",
        "distance_km": round(dist / 1000, 2) if dist else "",
        "moving_time": fmt_time(duration),
        "elapsed_time": fmt_time(a.get("duration", 0)),
        "avg_hr": a.get("averageHR", ""),
        "max_hr": a.get("maxHR", ""),
        "elevation_gain_m": round(elev_gain, 1) if elev_gain else "",
        "elevation_loss_m": round(elev_loss, 1) if elev_loss else "",
        "min_elevation_m": round(min_elev, 1) if min_elev else "",
        "max_elevation_m": round(max_elev, 1) if max_elev else "",
        "avg_pace_min_km": calc_pace(duration, dist),
        "max_pace_min_km": speed_to_pace(max_speed),
        "avg_cadence": round(cadence) if cadence else "",
        "calories": a.get("calories", ""),
        "training_load": a.get("activityTrainingLoad", ""),
        "aerobic_training_effect": a.get("aerobicTrainingEffect", ""),
        "anaerobic_training_effect": a.get("anaerobicTrainingEffect", ""),
        "vo2max_estimate": a.get("vO2MaxValue", "")
    }

# ── Build strength records ────────────────────────────────────────────────────
strength_fieldnames = ["date", "name", "elapsed_time", "duration_min"]

def build_strength_row(a):
    duration_s = a.get("duration", 0)
    return {
        "date": a.get("startTimeLocal", "")[:10],
        "name": a.get("activityName", ""),
        "elapsed_time": fmt_time(duration_s),
        "duration_min": round(duration_s / 60, 1) if duration_s else ""
    }

# ── Merge new + existing, deduplicate by date+name ───────────────────────────
def merge(new_rows, existing_rows, key_fields):
    existing_keys = {tuple(r[k] for k in key_fields) for r in existing_rows}
    merged = list(new_rows)
    for r in existing_rows:
        key = tuple(r[k] for k in key_fields)
        if key not in {tuple(n[k] for k in key_fields) for n in new_rows}:
            merged.append(r)
    return sorted(merged, key=lambda x: x.get("date", ""), reverse=True)

new_run_rows = [build_run_row(a) for a in new_running]
new_strength_rows = [build_strength_row(a) for a in new_strength]

if is_full_refresh:
    all_run_rows = sorted(new_run_rows, key=lambda x: x.get("date", ""), reverse=True)
    all_strength_rows = sorted(new_strength_rows, key=lambda x: x.get("date", ""), reverse=True)
else:
    all_run_rows = merge(new_run_rows, existing_runs, ["date", "name"])
    all_strength_rows = merge(new_strength_rows, existing_strength, ["date", "name"])

# ── Write runs.csv ────────────────────────────────────────────────────────────
with open("runs.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=run_fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(all_run_rows)

# ── Write strength.csv ────────────────────────────────────────────────────────
with open("strength.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=strength_fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(all_strength_rows)

# ── Aggregate stats ───────────────────────────────────────────────────────────
year_start = datetime(today.year, 1, 1).date()
prev_year_start = datetime(today.year - 1, 1, 1).date()
prev_year_end = datetime(today.year - 1, 12, 31).date()

runs_this_year = [a for a in all_run_rows if a.get("date", "")[:4] == str(today.year)]
runs_prev_year = [a for a in all_run_rows
    if str(prev_year_start) <= a.get("date", "") <= str(prev_year_end)]

strength_this_year = [a for a in all_strength_rows if a.get("date", "")[:4] == str(today.year)]

total_distance_this_year = sum(float(a.get("distance_km") or 0) for a in runs_this_year)
total_distance_prev_year = sum(float(a.get("distance_km") or 0) for a in runs_prev_year)
total_strength_min_this_year = sum(float(a.get("duration_min") or 0) for a in strength_this_year)

run_dates = sorted(set(
    datetime.strptime(a["date"], "%Y-%m-%d").date()
    for a in all_run_rows if a.get("date")
))

weeks_with_runs = set(get_week(d) for d in run_dates)
strength_dates = sorted(set(
    datetime.strptime(a["date"], "%Y-%m-%d").date()
    for a in all_strength_rows if a.get("date")
))
weeks_with_strength = set(get_week(d) for d in strength_dates)

def calc_current_streak(weeks_set):
    streak = 0
    week = today.date() - timedelta(days=today.weekday())
    while get_week(week) in weeks_set:
        streak += 1
        week -= timedelta(weeks=1)
    return streak

def calc_longest_streak(weeks_set):
    if not weeks_set:
        return 0
    sorted_weeks = sorted(weeks_set)
    longest = current = 1
    for i in range(1, len(sorted_weeks)):
        y1, w1 = sorted_weeks[i-1]
        y2, w2 = sorted_weeks[i]
        diff = (datetime.strptime(f"{y2} {w2} 1", "%G %V %u").date() -
                datetime.strptime(f"{y1} {w1} 1", "%G %V %u").date()).days
        if diff == 7:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest

weeks_in_year = len(set(get_week(
    datetime.strptime(a["date"], "%Y-%m-%d").date()
) for a in runs_this_year if a.get("date")))

summary = {
    "last_updated": str(today.date()),
    "total_runs_this_year": len(runs_this_year),
    "total_distance_this_year_km": round(total_distance_this_year, 1),
    "total_distance_prev_year_km": round(total_distance_prev_year, 1),
    "avg_runs_per_week_this_year": round(len(runs_this_year) / max(weeks_in_year, 1), 1),
    "current_weekly_streak": calc_current_streak(weeks_with_runs),
    "longest_weekly_streak": calc_longest_streak(weeks_with_runs),
    "total_strength_this_year": len(strength_this_year),
    "total_strength_min_this_year": round(total_strength_min_this_year, 0),
    "current_strength_weekly_streak": calc_current_streak(weeks_with_strength),
    "longest_strength_weekly_streak": calc_longest_streak(weeks_with_strength)
}

with open("summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2)

# ── Lactate threshold ─────────────────────────────────────────────────────────
lt_records = []
lt_file = "lactate.json"

if os.path.exists(lt_file):
    with open(lt_file, "r", encoding="utf-8") as f:
        lt_records = json.load(f)

try:
    status = client.get_training_status(today.strftime("%Y-%m-%d"))
    lt_hr = status.get("latestLactateThresholdHeartRate")
    lt_speed = status.get("latestLactateThresholdSpeed")
    if lt_hr and lt_speed:
        pace_sec = (1 / lt_speed) * (1000 / 60)
        pace_min = int(pace_sec)
        pace_s = int((pace_sec - pace_min) * 60)
        today_str = str(today.date())
        if not any(r["date"] == today_str for r in lt_records):
            lt_records.append({
                "date": today_str,
                "lt_hr": round(lt_hr),
                "lt_pace": f"{pace_min}:{pace_s:02d}"
            })
            print(f"LT recorded: {pace_min}:{pace_s:02d} /km @ {round(lt_hr)} bpm")
        else:
            print("LT already recorded today")
    else:
        print("LT data not available from Garmin")
except Exception as e:
    print(f"LT fetch skipped: {e}")

with open(lt_file, "w", encoding="utf-8") as f:
    json.dump(lt_records, f, indent=2)

print(f"Done! {len(all_run_rows)} runs, {len(all_strength_rows)} strength sessions. Mode: {'full' if is_full_refresh else 'incremental'}")
