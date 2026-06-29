# Fred's Feats — Training Dashboard

Personal training dashboard pulling activity data automatically from Garmin Connect.

## Live Dashboard

[ricocousin.github.io/Garmin-Dashboard](https://ricocousin.github.io/Garmin-Dashboard)

## How it works

| File | Purpose |
|------|---------|
| `fetch_activities.py` | Fetches activities from Garmin and writes data files |
| `.github/workflows/fetch_activities.yml` | Runs the script automatically every morning at 6am Danish time |
| `index.html` | The dashboard, hosted via GitHub Pages |

**Daily:** incremental fetch — only new activities since the last run  
**First Sunday of each month:** full refresh of all historical data

## Data collected

**Running** (`runs.csv`)
- Date, name, type (outdoor / treadmill)
- Distance, moving time, elapsed time
- Average and max heart rate
- Elevation gain, loss, min, max
- Average and max pace
- Average cadence
- Calories, training load
- Aerobic and anaerobic training effect
- VO2 max estimate

**Strength** (`strength.csv`)
- Date, name, elapsed time, duration

**Summary** (`summary.json`)
- Yearly and previous year totals
- Weekly streaks
- Averages per week

**Lactate threshold** (`lactate.json`)
- Daily LT pace and heart rate estimate, appended over time

## Credentials

Garmin login credentials are stored as GitHub Secrets (`GARMIN_EMAIL`, `GARMIN_PASSWORD`) and never exposed in the code.

## Stack

- Python + [garminconnect](https://github.com/cyberjunky/python-garminconnect)
- GitHub Actions (automation)
- GitHub Pages (hosting)
- Chart.js + PapaParse (dashboard)
