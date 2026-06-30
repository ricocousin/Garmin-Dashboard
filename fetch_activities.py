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
    lt = client.get_lactate_threshold()
    lt_data = lt.get("speed_and_heart_rate", {})
    lt_hr = lt_data.get("heartRate")
    lt_speed = lt_data.get("speed")
    lt_date = lt_data.get("calendarDate", "")[:10]
    if lt_hr and lt_speed:
        pace_sec = (1 / (lt_speed * 10)) * (1000 / 60)
        pace_min = int(pace_sec)
        pace_s = int((pace_sec - pace_min) * 60)
        today_str = str(today.date())
        if not any(r["date"] == today_str for r in lt_records):
            lt_records.append({
                "date": today_str,
                "lt_hr": round(lt_hr),
                "lt_pace": f"{pace_min}:{pace_s:02d}",
                "lt_source_date": lt_date
            })
            print(f"LT recorded: {pace_min}:{pace_s:02d} /km @ {round(lt_hr)} bpm")
        else:
            print("LT already recorded today")
    else:
        print("LT data not available")
except Exception as e:
    print(f"LT fetch skipped: {e}")

with open(lt_file, "w", encoding="utf-8") as f:
    json.dump(lt_records, f, indent=2)

print(f"Done! {len(all_run_rows)} runs, {len(all_strength_rows)} strength sessions. Mode: {'full' if is_full_refresh else 'incremental'}")


# ── Coach evaluator block ─────────────────────────────────────────────────────
# Rules-based training status summary. No external API calls — pure logic
# over data we already have. Each threshold below has a comment explaining
# why that specific number was chosen, so it's easy to revisit and tune.
 
def parse_pace_sec(pace_str):
    if not pace_str:
        return None
    try:
        m, s = pace_str.split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return None
 
def parse_moving_time_mins(time_str):
    if not time_str:
        return 0
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = map(int, parts)
        return h * 60 + m + s / 60
    return 0
 
all_runs_sorted = sorted(all_run_rows, key=lambda x: x.get("date", ""))
all_strength_sorted = sorted(all_strength_rows, key=lambda x: x.get("date", ""))
 
today_date = today.date()
insights = []
quiet = {}  # category_key -> muted "nothing to report" reason
 
# ── 1. Volume trend: last 4 weeks vs the 4 weeks before that ───────────────────
# WHY 4 WEEKS: a single week is too noisy (one big run skews it), but a full
# 8-12 week window reacts too slowly to genuine recent changes. 4 weeks is
# roughly one training "block" and is a common coaching convention for
# short-term load comparison. The comparison window is also 4 weeks so both
# halves are equal length and the percentage change is meaningful.
def distance_in_window(start_days_ago, end_days_ago):
    start = today_date - timedelta(days=start_days_ago)
    end = today_date - timedelta(days=end_days_ago)
    return sum(
        float(r.get("distance_km") or 0) for r in all_runs_sorted
        if start <= datetime.strptime(r["date"], "%Y-%m-%d").date() <= end
    )
 
recent_4wk = distance_in_window(28, 1)
prior_4wk = distance_in_window(56, 29)
 
if prior_4wk > 0:
    volume_change_pct = ((recent_4wk - prior_4wk) / prior_4wk) * 100
    if volume_change_pct > 15:
        insights.append(f"Volume is trending up — {recent_4wk:.0f} km over the last 4 weeks vs {prior_4wk:.0f} km the 4 weeks before, a {volume_change_pct:.0f}% increase.")
    elif volume_change_pct < -15:
        insights.append(f"Volume has dropped — {recent_4wk:.0f} km over the last 4 weeks vs {prior_4wk:.0f} km the 4 weeks before, a {abs(volume_change_pct):.0f}% decrease.")
    else:
        quiet["volume"] = "Volume steady — no significant shift in the last 4 weeks."
else:
    quiet["volume"] = "Volume trend builds after 8 weeks of data — check back soon."
    
# ── 2. PB proximity: any run in the last 30 days within X% of a category PB ────
# WHY 30 DAYS: long enough to catch a recent strong block, short enough that
# "recent" still feels recent rather than dredging up something from 4 months ago.
# WHY 3%: a PB-category pace category is fairly forgiving since these are
# whole-run averages, not exact splits. 3% is tight enough to mean "genuinely
# close" (e.g. 4:30 vs 4:23 /km) without flagging routine training runs.
def best_pace_for_min_distance(min_dist):
    eligible = [r for r in all_runs_sorted if float(r.get("distance_km") or 0) >= min_dist and r.get("avg_pace_min_km")]
    if not eligible:
        return None
    return min(parse_pace_sec(r["avg_pace_min_km"]) for r in eligible)
 
pb_categories = [("5K", 4), ("10K", 8), ("Half", 18), ("Marathon", 38), ("50K", 45)]
recent_cutoff = today_date - timedelta(days=30)
close_calls = []
 
for label, min_dist in pb_categories:
    pb_sec = best_pace_for_min_distance(min_dist)
    if not pb_sec:
        continue
    recent_eligible = [
        r for r in all_runs_sorted
        if float(r.get("distance_km") or 0) >= min_dist
        and r.get("avg_pace_min_km")
        and datetime.strptime(r["date"], "%Y-%m-%d").date() >= recent_cutoff
    ]
    for r in recent_eligible:
        r_sec = parse_pace_sec(r["avg_pace_min_km"])
        if r_sec and r_sec > pb_sec:  # not the PB itself
            pct_off = ((r_sec - pb_sec) / pb_sec) * 100
            if pct_off <= 3:
                close_calls.append((label, r["date"], pct_off))
 
if close_calls:
    label, date, pct_off = min(close_calls, key=lambda x: x[2])
    insights.append(f"Close call on your {label} best — within {pct_off:.1f}% of your PB pace on {date}.")
else:
    quiet["pb"] = "No close calls on a PB in the last 30 days."
 
# ── 3. LT trend: latest reading vs ~30 days prior ───────────────────────────────
# WHY 30 DAYS: lactate threshold genuinely shifts over weeks, not days — a
# day-to-day comparison would just be noise from a single test. 30 days gives
# the adaptation enough time to show up while still being "recent."
# WHY ±3 SEC/KM: LT pace readings from this kind of estimate carry some natural
# noise. A few seconds either way isn't meaningful; we want a change big enough
# to actually represent a fitness shift, not measurement jitter.

quiet["lt"] = "Lactate threshold trend builds after 30 days of daily readings — check back soon."
if os.path.exists(lt_file):
    with open(lt_file, "r", encoding="utf-8") as f:
        lt_history = json.load(f)
    lt_history = [r for r in lt_history if r.get("lt_pace") and 120 < (parse_pace_sec(r["lt_pace"]) or 0) < 900]
    lt_history_sorted = sorted(lt_history, key=lambda x: x["date"])
    if len(lt_history_sorted) >= 2:
        latest_lt = lt_history_sorted[-1]
        cutoff_30d = today_date - timedelta(days=30)
        older_candidates = [r for r in lt_history_sorted if datetime.strptime(r["date"], "%Y-%m-%d").date() <= cutoff_30d]
        if older_candidates:
            baseline_lt = older_candidates[-1]
            latest_sec = parse_pace_sec(latest_lt["lt_pace"])
            baseline_sec = parse_pace_sec(baseline_lt["lt_pace"])
            if latest_sec and baseline_sec:
                diff = baseline_sec - latest_sec
                if diff > 3:
                    insights.append(f"Lactate threshold has improved — {latest_lt['lt_pace']} /km now vs {baseline_lt['lt_pace']} /km on {baseline_lt['date']}.")
                    del quiet["lt"]
                elif diff < -3:
                    insights.append(f"Lactate threshold has eased — {latest_lt['lt_pace']} /km now vs {baseline_lt['lt_pace']} /km on {baseline_lt['date']}.")
                    del quiet["lt"]
                else:
                    quiet["lt"] = "Lactate threshold stable — no meaningful change in the last 30 days."
 
# ── 4. Training balance: strength sessions vs runs, recent vs YTD norm ─────────
# WHY 3 WEEKS: short enough to catch "I haven't lifted in a while" while it's
# still actionable, long enough to not flag a single rest week as a problem.
# WHY ±0.3 RATIO POINTS: the run:strength ratio naturally fluctuates week to
# week. A shift of 0.3 or more in the ratio (e.g. from 1.5 runs-per-lift to
# 1.8+) represents a real behavioural change, not noise.

def sessions_in_window(rows, start_days_ago, end_days_ago):
    start = today_date - timedelta(days=start_days_ago)
    end = today_date - timedelta(days=end_days_ago)
    return len([
        r for r in rows
        if start <= datetime.strptime(r["date"], "%Y-%m-%d").date() <= end
    ])
 
recent_runs_3wk = sessions_in_window(all_runs_sorted, 21, 1)
recent_strength_3wk = sessions_in_window(all_strength_sorted, 21, 1)
ytd_runs = len(runs_this_year)
ytd_strength = len(strength_this_year)
 
if recent_strength_3wk == 0 and recent_runs_3wk >= 3:
    insights.append(f"No strength sessions in the last 3 weeks despite {recent_runs_3wk} runs — strength training has dropped off.")
elif ytd_strength > 0 and ytd_runs > 0:
    ytd_ratio = ytd_runs / ytd_strength
    recent_ratio = (recent_runs_3wk / recent_strength_3wk) if recent_strength_3wk > 0 else None
    if recent_ratio and abs(recent_ratio - ytd_ratio) > 0.3:
        if recent_ratio > ytd_ratio:
            insights.append(f"Running has been prioritised over strength recently — {recent_runs_3wk} runs to {recent_strength_3wk} strength sessions in the last 3 weeks, vs a {ytd_ratio:.1f}:1 norm this year.")
        else:
            quiet["balance"] = "Run/strength balance steady — no notable shift this period."
    else:
        quiet["balance"] = "Run/strength balance steady — no notable shift this period."
else:
    quiet["balance"] = "Balance tracking builds once both running and strength data accumulate."
    
# ── 5. Activity silence: days since last run / last strength session ───────────
# WHY 7 DAYS for running: at 4x/week training frequency, 7 days without a run
# is roughly double the normal gap and worth flagging — shorter would trigger
# on completely normal rest days.
# WHY 10 DAYS for strength: strength sessions are naturally less frequent than
# runs in this setup, so the silence threshold is set a bit longer to avoid
# false positives on a normal lighter week.
if all_runs_sorted:
    last_run_date = datetime.strptime(all_runs_sorted[-1]["date"], "%Y-%m-%d").date()
    days_since_run = (today_date - last_run_date).days
    if days_since_run >= 7:
        insights.append(f"It's been {days_since_run} days since your last run ({last_run_date}).")
    else:
        quiet["run_silence"] = f"Recently active — last run {days_since_run} day{'s' if days_since_run != 1 else ''} ago."

if all_strength_sorted:
    last_strength_date = datetime.strptime(all_strength_sorted[-1]["date"], "%Y-%m-%d").date()
    days_since_strength = (today_date - last_strength_date).days
    if days_since_strength >= 10:
        insights.append(f"It's been {days_since_strength} days since your last strength session ({last_strength_date}).")
    else:
        quiet["strength_silence"] = f"Recently active — last strength session {days_since_strength} day{'s' if days_since_strength != 1 else ''} ago."
 
# ── 6. Year-over-year pace of accumulation ──────────────────────────────────────
# WHY: compares how much distance you'd covered by "today's date" last year
# vs this year, giving a fair apples-to-apples comparison regardless of when
# in the year it is. WHY ±10%: tighter than the 4-week volume threshold
# because this is a much longer baseline (months of data), so even a modest
# percentage difference represents a real, sustained pattern rather than
# short-term noise.
try:
    today_last_year = today_date.replace(year=today_date.year - 1)
except ValueError:
    today_last_year = today_date.replace(year=today_date.year - 1, day=28)
 
dist_this_year_to_date = sum(
    float(r.get("distance_km") or 0) for r in runs_this_year
)
dist_last_year_to_date = sum(
    float(r.get("distance_km") or 0) for r in runs_prev_year
    if datetime.strptime(r["date"], "%Y-%m-%d").date() <= today_last_year
)
 
if dist_last_year_to_date > 0:
    yoy_pct = ((dist_this_year_to_date - dist_last_year_to_date) / dist_last_year_to_date) * 100
    if abs(yoy_pct) > 10:
        direction = "ahead of" if yoy_pct > 0 else "behind"
        insights.append(f"You're {abs(yoy_pct):.0f}% {direction} last year's pace — {dist_this_year_to_date:.0f} km vs {dist_last_year_to_date:.0f} km by this date in {today_last_year.year}.")
    else:
        quiet["yoy"] = "On pace with last year — no significant year-over-year shift."
else:
    quiet["yoy"] = "Year-over-year comparison needs last year's data by this date."
    
# ── Assemble final summary ──────────────────────────────────────────────────────
# WHY MAX 4 INSIGHTS: more than this starts to feel like a wall of text rather
# than a quick scan. We prioritise the most "actionable" categories first —
# silence and close-call PBs are time-sensitive, trends are more background.
priority_order = ["last run", "last strength", "Close call", "Volume is trending", "Volume has dropped",
                   "Lactate threshold", "strength training has dropped off", "prioritised over strength",
                   "ahead of", "behind"]
 
def priority_key(insight):
    for i, keyword in enumerate(priority_order):
        if keyword in insight:
            return i
    return len(priority_order)
 
insights_sorted = sorted(insights, key=priority_key)[:4]

if not insights_sorted:
    insights_sorted = ["Training is steady — no major shifts in volume, balance, or pace recently."]

coach_summary = {
    "last_updated": str(today_date),
    "insights": insights_sorted,
    "quiet": list(quiet.values())
}

with open("coach_summary.json", "w", encoding="utf-8") as f:
    json.dump(coach_summary, f, indent=2)
 
print(f"Coach summary: {len(insights_sorted)} insight(s) generated")
for i in insights_sorted:
    print(f"  - {i}")
