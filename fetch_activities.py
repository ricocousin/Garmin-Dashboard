import os
import csv
import json
from datetime import datetime, timedelta
from garminconnect import Garmin

email = os.environ["GARMIN_EMAIL"]
password = os.environ["GARMIN_PASSWORD"]

client = Garmin(email, password)
client.login()

# Fetch all activities in batches
all_activities = []
batch_size = 100
start = 0

while True:
    batch = client.get_activities(start, batch_size)
    if not batch:
        break
    all_activities.extend(batch)
    start += batch_size
    if len(batch) < batch_size:
        break

# ── Filter functions ─────────────────────────────────────────────────────────
def is_running(a):
    type_key = a.get("activityType", {}).get("typeKey", "").lower()
    return type_key in ["running", "treadmill_running", "trail_running"]

def is_treadmill(a):
    return a.get("activityType", {}).get("typeKey", "").lower() == "treadmill_running"

def is_strength(a):
    type_key = a.get("activityType", {}).get("typeKey", "").lower()
    return type_key in ["strength_training"]

running = [a for a in all_activities if is_running(a)]
strength = [a for a in all_activities if is_strength(a)]

# ── Helpers ──────────────────────────────────────────────────────────────────
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

def get_week(date):
    return date.isocalendar()[:2]

# ── Write runs.csv ───────────────────────────────────────────────────────────
run_fieldnames = [
    "date", "name", "type", "distance_km", "moving_time", "elapsed_time",
    "avg_hr", "max_hr", "elevation_gain_m", "elevation_loss_m",
    "min_elevation_m", "max_elevation_m", "avg_pace_min_km", "calories",
    "training_load", "aerobic_training_effect", "anaerobic_training_effect",
    "vo2max_estimate"
]

with open("runs.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=run_fieldnames)
    writer.writeheader()
    for a in sorted(running, key=lambda x: x.get("startTimeLocal", ""), reverse=True):
        dist = a.get("distance", 0)
        duration = a.get("movingDuration", 0)
        elev_gain = a.get("elevationGain", "")
        elev_loss = a.get("elevationLoss", "")
        min_elev = a.get("minElevation", "")
        max_elev = a.get("maxElevation", "")
        writer.writerow({
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
            "calories": a.get("calories", ""),
            "training_load": a.get("activityTrainingLoad", ""),
            "aerobic_training_effect": a.get("aerobicTrainingEffect", ""),
            "anaerobic_training_effect": a.get("anaerobicTrainingEffect", ""),
            "vo2max_estimate": a.get("vO2MaxValue", "")
        })

# ── Write strength.csv ───────────────────────────────────────────────────────
with open("strength.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["date", "name", "elapsed_time", "duration_min", "calories"])
    writer.writeheader()
    for a in sorted(strength, key=lambda x: x.get("startTimeLocal", ""), reverse=True):
        duration_s = a.get("duration", 0)
        writer.writerow({
            "date": a.get("startTimeLocal", "")[:10],
            "name": a.get("activityName", ""),
            "elapsed_time": fmt_time(duration_s),
            "duration_min": round(duration_s / 60, 1) if duration_s else "",
            "calories": a.get("calories", "")
        })

# ── Aggregate stats ──────────────────────────────────────────────────────────
today = datetime.today().date()
year_start = datetime(today.year, 1, 1).date()

run_dates = sorted(set(
    datetime.strptime(a.get("startTimeLocal", "")[:10], "%Y-%m-%d").date()
    for a in running if a.get("startTimeLocal")
))

runs_this_year = [a for a in running if a.get("startTimeLocal", "")[:10] >= str(year_start)]
strength_this_year = [a for a in strength if a.get("startTimeLocal", "")[:10] >= str(year_start)]

total_distance_this_year = sum(a.get("distance", 0) for a in runs_this_year) / 1000
total_strength_min_this_year = sum(a.get("duration", 0) for a in strength_this_year) / 60

weeks_with_runs = set(get_week(d) for d in run_dates)

strength_dates = sorted(set(
    datetime.strptime(a.get("startTimeLocal", "")[:10], "%Y-%m-%d").date()
    for a in strength if a.get("startTimeLocal")
))
weeks_with_strength = set(get_week(d) for d in strength_dates)

def calc_current_streak(weeks_set):
    streak = 0
    week = today - timedelta(days=today.weekday())
    while True:
        if get_week(week) in weeks_set:
            streak += 1
            week -= timedelta(weeks=1)
        else:
            break
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
    datetime.strptime(a.get("startTimeLocal", "")[:10], "%Y-%m-%d").date()
) for a in runs_this_year if a.get("startTimeLocal")))

summary = {
    "last_updated": str(today),
    "total_runs_all_time": len(running),
    "total_runs_this_year": len(runs_this_year),
    "total_distance_this_year_km": round(total_distance_this_year, 1),
    "avg_runs_per_week_this_year": round(len(runs_this_year) / max(weeks_in_year, 1), 1),
    "current_weekly_streak": calc_current_streak(weeks_with_runs),
    "longest_weekly_streak": calc_longest_streak(weeks_with_runs),
    "total_strength_this_year": len(strength_this_year),
    "total_strength_all_time": len(strength),
    "total_strength_min_this_year": round(total_strength_min_this_year, 0),
    "current_strength_weekly_streak": calc_current_streak(weeks_with_strength),
    "longest_strength_weekly_streak": calc_longest_streak(weeks_with_strength)
}

with open("summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2)
    
    # Fetch current lactate threshold estimate
import os

lt_records = []
lt_file = "lactate.json"

# Load existing history
if os.path.exists(lt_file):
    with open(lt_file, "r", encoding="utf-8") as f:
        lt_records = json.load(f)

try:
    status = client.get_training_status()
    lt_hr = status.get("latestLactateThresholdHeartRate")
    lt_speed = status.get("latestLactateThresholdSpeed")  # m/s
    if lt_hr and lt_speed:
        pace_sec = (1 / lt_speed) * (1000 / 60)
        pace_min = int(pace_sec)
        pace_s = int((pace_sec - pace_min) * 60)
        today_str = str(datetime.today().date())
        # Only add if not already recorded today
        if not any(r["date"] == today_str for r in lt_records):
            lt_records.append({
                "date": today_str,
                "lt_hr": round(lt_hr),
                "lt_pace": f"{pace_min}:{pace_s:02d}"
            })
except Exception as e:
    print(f"LT fetch skipped: {e}")

with open(lt_file, "w", encoding="utf-8") as f:
    json.dump(lt_records, f, indent=2)

print(f"LT records stored: {len(lt_records)}")

print(f"Done! {len(running)} runs, {len(strength)} strength sessions fetched.")
