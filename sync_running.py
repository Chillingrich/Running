#!/usr/bin/env python3
"""
sync_running.py
Parse .fit files + push sessions.json to GitHub
วาง .fit ใน ~/Downloads แล้วรัน script นี้
"""

import os, json, base64, requests, glob, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── CONFIG ──────────────────────────────────────────────────────────────────
REPO      = "Chillingrich/Running"
DATA_FILE = "data/sessions.json"
FIT_DIR   = Path.home() / "Downloads"
BRANCH    = "main"

# GitHub token — เก็บใน ~/.running_token หรือ environment variable
TOKEN_FILE = Path.home() / ".running_token"

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def get_token():
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    token = input("🔑 GitHub Token (จะเก็บไว้ใน ~/.running_token): ").strip()
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    return token

def fetch_sessions(token):
    url = f"https://api.github.com/repos/{REPO}/contents/{DATA_FILE}"
    r = requests.get(url, headers={"Authorization": f"token {token}"})
    r.raise_for_status()
    data = r.json()
    content = json.loads(base64.b64decode(data["content"]))
    sha = data["sha"]
    return content, sha

def push_sessions(token, sessions, sha, message):
    url = f"https://api.github.com/repos/{REPO}/contents/{DATA_FILE}"
    content = base64.b64encode(json.dumps(sessions, indent=2, ensure_ascii=False).encode()).decode()
    r = requests.put(url, headers={"Authorization": f"token {token}"}, json={
        "message": message,
        "content": content,
        "sha": sha,
        "branch": BRANCH
    })
    r.raise_for_status()
    print(f"🚀 Pushed: {message}")

def dur_to_sec(d):
    parts = str(d).split(":")
    if len(parts) == 3: return int(parts[0])*3600 + int(parts[1])*60 + float(parts[2])
    if len(parts) == 2: return int(parts[0])*60 + float(parts[1])
    return float(d)

def speed_to_pace(speed_ms):
    if not speed_ms or speed_ms <= 0: return "—"
    sec = 1000 / speed_ms
    return f"{int(sec//60)}:{int(sec%60):02d}"

def avg(lst):
    return sum(lst)/len(lst) if lst else 0

# ─── FIT PARSER ──────────────────────────────────────────────────────────────
def parse_fit(fit_path):
    try:
        from garmin_fit_sdk import Decoder, Stream
    except ImportError:
        print("❌ garmin-fit-sdk not installed: pip3 install garmin-fit-sdk")
        return None

    stream = Stream.from_file(str(fit_path))
    decoder = Decoder(stream)
    messages, errors = decoder.read()

    laps    = messages.get("lap_mesgs", [])
    records = messages.get("record_mesgs", [])
    session = messages.get("session_mesgs", [{}])[0]

    if not laps:
        print(f"  ⚠️  No laps found in {fit_path.name}")
        return None

    # ── Date ──
    ts = session.get("start_time") or laps[0].get("start_time")
    if ts:
        if hasattr(ts, "astimezone"):
            date_str = ts.astimezone(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
        else:
            date_str = str(ts)[:10]
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # ── Identify lap roles ──
    # WU = first lap if distance < 2km and not the only lap
    # CD = last lap(s) if distance < 2km
    # Main = largest contiguous block of 1km laps OR single big lap

    total_laps = len(laps)
    wu_lap  = None
    cd_laps = []
    main_laps = []

    # Simple heuristic: WU = lap[0] if dist < 2000m, CD = last lap(s) < 2000m
    if total_laps >= 2 and laps[0].get("total_distance", 0) < 2000:
        wu_lap = laps[0]
        remaining = laps[1:]
    else:
        remaining = laps

    # CD = trailing laps < 2000m
    while remaining and remaining[-1].get("total_distance", 0) < 2000:
        cd_laps.insert(0, remaining.pop())

    main_laps = remaining

    # ── WU ──
    wu = {}
    if wu_lap:
        d = wu_lap.get("total_distance", 0) / 1000
        t = wu_lap.get("total_timer_time", 0)
        wu = {
            "dist": str(round(d, 2)),
            "pace": speed_to_pace(d*1000/t) if t > 0 else "",
            "hr":   str(wu_lap.get("avg_heart_rate", "") or "")
        }

    # ── CD ──
    cd = {}
    if cd_laps:
        d = sum(l.get("total_distance", 0) for l in cd_laps) / 1000
        t = sum(l.get("total_timer_time", 0) for l in cd_laps)
        hrs = [l.get("avg_heart_rate", 0) or 0 for l in cd_laps]
        cd = {
            "dist": str(round(d, 2)),
            "pace": speed_to_pace(d*1000/t) if t > 0 else "",
            "hr":   str(round(avg(hrs))) if any(hrs) else ""
        }

    # ── Per-km splits from records (main lap window) ──
    splits = []
    if main_laps and records:
        main_start = main_laps[0].get("start_time")
        main_end   = main_laps[-1].get("timestamp")

        if main_start and main_end:
            main_recs = [r for r in records if main_start <= r["timestamp"] <= main_end]
        else:
            main_recs = records

        if main_recs:
            dist_origin = main_recs[0].get("distance", 0)
            km_num = 1
            chunk_start = 0

            for i, rec in enumerate(main_recs):
                dist_from_start = rec.get("distance", 0) - dist_origin
                is_last = (i == len(main_recs) - 1)

                if dist_from_start >= km_num * 1000 or is_last:
                    chunk = main_recs[chunk_start:i+1]
                    if not chunk:
                        km_num += 1
                        chunk_start = i + 1
                        continue

                    speeds  = [c.get("speed", 0) for c in chunk if c.get("speed", 0) > 0]
                    hrs     = [c.get("heart_rate", 0) for c in chunk if c.get("heart_rate", 0) > 0]
                    cads    = [c.get("cadence", 0)*2 for c in chunk if c.get("cadence", 0) > 0]
                    powers  = [c.get("power", 0) for c in chunk if c.get("power", 0) > 0]
                    strides = [c.get("step_length", 0)/10 for c in chunk if c.get("step_length", 0) > 0]
                    voscs   = [c.get("vertical_oscillation", 0)/10 for c in chunk if c.get("vertical_oscillation", 0) > 0]
                    vratios = [c.get("vertical_ratio", 0) for c in chunk if c.get("vertical_ratio", 0) > 0]
                    stances = [c.get("stance_time", 0) for c in chunk if c.get("stance_time", 0) > 0]

                    splits.append({
                        "km":      km_num,
                        "pace":    speed_to_pace(avg(speeds)),
                        "hr":      str(round(avg(hrs)))      if hrs     else "",
                        "cadence": str(round(avg(cads)))     if cads    else "",
                        "stride":  str(round(avg(strides),1))if strides else "",
                        "power":   str(round(avg(powers)))   if powers  else "",
                        "stance":  str(round(avg(stances),1))if stances else "",
                        "vosc":    str(round(avg(voscs),1))  if voscs   else "",
                        "vratio":  str(round(avg(vratios),1))if vratios else "",
                    })

                    km_num += 1
                    chunk_start = i + 1

    # ── Main KM ──
    main_km = round(sum(l.get("total_distance", 0) for l in main_laps) / 1000, 2)
    wu_km   = float(wu.get("dist", 0) or 0)
    cd_km   = float(cd.get("dist", 0) or 0)
    total_km = round(wu_km + main_km + cd_km, 2)

    # ── Avg pace/HR from session ──
    avg_speed = session.get("avg_speed", 0) or 0
    avg_pace  = speed_to_pace(avg_speed)
    avg_hr    = session.get("avg_heart_rate", None)

    # ── Guess type ──
    main_pace_sec = 1000/avg_speed if avg_speed > 0 else 999
    if main_pace_sec < 260:   stype = "threshold"
    elif main_pace_sec < 290: stype = "marathon"
    elif total_km > 20:       stype = "long"
    else:                     stype = "easy"

    label_id = fit_path.stem  # filename without .fit

    return {
        "labelId":  label_id,
        "date":     date_str,
        "type":     stype,
        "totalKm":  total_km,
        "mainKm":   main_km,
        "avgPace":  avg_pace,
        "avgHR":    avg_hr,
        "fitFile":  fit_path.name,
        "wu":       wu,
        "cd":       cd,
        "splits":   splits,
    }

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  🏃 Running Sync v1.0")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    token = get_token()

    # ── Find .fit files in Downloads ──
    fit_files = list(FIT_DIR.glob("*.fit"))
    if not fit_files:
        print(f"⚪ No .fit files found in {FIT_DIR}")
    else:
        print(f"\n📂 Found {len(fit_files)} .fit file(s):")
        for f in fit_files:
            print(f"  {f.name}")

    # ── Fetch current sessions ──
    print("\n📥 Fetching sessions from GitHub...")
    sessions, sha = fetch_sessions(token)
    print(f"  {len(sessions)} sessions loaded")

    existing_labels = {s.get("corosLabelId","") for s in sessions}
    existing_fits   = {s.get("fitFile","") for s in sessions}

    added = 0
    updated = 0

    for fit_path in fit_files:
        print(f"\n🔍 Parsing {fit_path.name}...")
        result = parse_fit(fit_path)
        if not result:
            continue

        label_id = result["labelId"]
        date_str = result["date"]
        splits   = result["splits"]

        print(f"  📅 Date: {date_str} | {result['mainKm']}km | {result['avgPace']}/km | {len(splits)} splits")

        # Find existing session by corosLabelId or date
        idx = next((i for i, s in enumerate(sessions) if s.get("corosLabelId") == label_id), None)
        if idx is None:
            idx = next((i for i, s in enumerate(sessions)
                       if s.get("date") == date_str and not s.get("fitFile")), None)

        if idx is not None:
            # Merge into existing session
            s = sessions[idx]
            s["fitFile"]  = result["fitFile"]
            s["totalKm"]  = result["totalKm"]
            s["mainKm"]   = result["mainKm"]
            s["avgPace"]  = result["avgPace"]
            if result["avgHR"]: s["avgHR"] = result["avgHR"]
            s["wu"] = result["wu"]
            s["cd"] = result["cd"]
            s["sets"] = [{"set": 1, "splits": splits}]
            sessions[idx] = s
            print(f"  ✅ Merged into existing session ({date_str})")
            updated += 1
        else:
            # Create new session
            sessions.append({
                "id":            int(datetime.now().timestamp() * 1000),
                "corosLabelId":  label_id if label_id.isdigit() else "",
                "date":          date_str,
                "type":          result["type"],
                "shoe":          "",
                "surface":       "Road",
                "temp":          "",
                "notes":         "",
                "rpe":           0,
                "highlighted":   False,
                "totalKm":       result["totalKm"],
                "mainKm":        result["mainKm"],
                "avgPace":       result["avgPace"],
                "avgHR":         result["avgHR"],
                "fitFile":       result["fitFile"],
                "wu":            result["wu"],
                "cd":            result["cd"],
                "sets":          [{"set": 1, "splits": splits}]
            })
            print(f"  ✅ Created new session ({date_str})")
            added += 1

        # Move processed .fit to archive folder
        archive = FIT_DIR / "fit_archive"
        archive.mkdir(exist_ok=True)
        fit_path.rename(archive / fit_path.name)
        print(f"  📦 Moved to fit_archive/")

    # ── Push if changed ──
    if added + updated > 0:
        sessions.sort(key=lambda x: x.get("date",""), reverse=True)
        msg = f"sync: {added} added, {updated} updated ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
        push_sessions(token, sessions, sha, msg)
        print(f"\n🎉 Done! {added} added, {updated} updated")
    else:
        print("\n⚪ No changes to push")

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    input("\nกด Enter เพื่อปิด...")

if __name__ == "__main__":
    main()
