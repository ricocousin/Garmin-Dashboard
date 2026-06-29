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
    return type_key in ["running", "treadmill_running"]

def is_treadmill(a):
    return a.get("activityType", {}).get("typeKey", "").lower() == "treadmill_running"

def is_strength(a):
    type_key = a.get("activityType", {}).get("typeKey", "").lower()
    return type_key in ["strength_training", "fitness_equipment"]

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
        duration = a.get("movingD
