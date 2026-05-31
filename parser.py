#!/usr/bin/env python3
"""
parser.py - Auto-parse all FIT files in /fits/ and update /data/sessions.json
Run by GitHub Actions on every push of .fit files
"""

import os, json, datetime
from garmin_fit_sdk import Decoder, Stream

FITS_DIR = 'fits'
OUTPUT = 'data/sessions.json'
SLOW = 1000 / 330  # 5:30/km in m/s = WU/CD threshold

def mps2pace(mps):
    if not mps or mps <= 0: return ''
    spk = 1000 / mps
    return f"{int(spk//60)}:{int(spk%60):02d}"

def safe_avg(lst):
    lst = [x for x in lst if x is not None and x == x and x > 0]
    return round(sum(lst)/len(lst), 1) if lst else None

def fingerprint(path):
    with open(path, 'rb') as f:
        raw = f.read(40)
    s = len(raw)
    for i, b in enumerate(raw): s += b * i
    return format(s, 'x')

def parse_fit(path):
    stream = Stream.from_file(path)
    decoder = Decoder(stream)
    messages, _ = decoder.read()

    session = messages.get('session_mesgs', [{}])[0]
    laps = messages.get('lap_mesgs', [])
    records = messages.get('record_mesgs', [])

    # Date (Bangkok UTC+7)
    start = session.get('start_time')
    if start:
        local = start.astimezone(datetime.timezone(datetime.timedelta(hours=7)))
        date = local.strftime('%Y-%m-%d')
    else:
        date = datetime.date.today().isoformat()

    temp = str(session.get('avg_temperature', ''))
    total_dist = (session.get('total_distance') or 0) / 1000

    # Classify laps
    cum = 0
    boundaries = []
    for i, lap in enumerate(laps):
        sp = lap.get('enhanced_avg_speed') or lap.get('avg_speed') or 0
        dist = lap.get('total_distance') or 0
        t = (lap.get('total_elapsed_time') or 0) / 60

        if i == 0 and sp < SLOW and t >= 2:
            tag = 'WU'
        elif i == len(laps) - 1 and sp < SLOW:
            tag = 'CD'
        elif dist < 150 and sp > 1000/400:
            tag = 'STRIDE'
        elif dist < 150 and sp < SLOW:
            tag = 'REST'
        else:
            tag = 'MAIN'

        lap['_tag'] = tag
        boundaries.append((cum, cum + dist, lap))
        cum += dist

    wu = {}; cd = {}; main_laps = []
    for _, _, lap in boundaries:
        tag = lap.get('_tag')
        sp = lap.get('enhanced_avg_speed') or lap.get('avg_speed') or 0
        dist = lap.get('total_distance') or 0
        hr = str(lap.get('avg_heart_rate', ''))
        if tag == 'WU':
            wu = {'dist': round(dist/1000, 2), 'pace': mps2pace(sp), 'hr': hr}
        elif tag == 'CD':
            cd = {'dist': round(dist/1000, 2), 'pace': mps2pace(sp), 'hr': hr}
        elif tag == 'MAIN':
            main_laps.append(lap)

    # Per-km splits for each main lap
    sets = []
    for set_num, lap in enumerate(main_laps, 1):
        lap_start = lap_end = None
        for s, e, l in boundaries:
            if l is lap:
                lap_start = s; lap_end = e; break
        if lap_start is None: continue

        lap_recs = [r for r in records if lap_start <= (r.get('distance') or 0) < lap_end]
        km_data = {}
        for r in lap_recs:
            rel = (r.get('distance') or 0) - lap_start
            km = int(rel // 1000) + 1
            if km not in km_data:
                km_data[km] = {'sp':[],'hr':[],'cad':[],'stride':[],'pwr':[],'stance':[],'vosc':[],'vr':[]}
            sp2 = r.get('enhanced_speed') or r.get('speed')
            if sp2 and sp2 > 0: km_data[km]['sp'].append(sp2)
            hr2 = r.get('heart_rate')
            if hr2: km_data[km]['hr'].append(hr2)
            cad = r.get('cadence')
            if cad: km_data[km]['cad'].append(cad * 2)
            stride = r.get('step_length')
            if stride and stride > 0: km_data[km]['stride'].append(stride)
            pwr = r.get('power')
            if pwr and pwr > 0: km_data[km]['pwr'].append(pwr)
            stance = r.get('stance_time')
            if stance and stance > 0: km_data[km]['stance'].append(stance)
            vosc = r.get('vertical_oscillation')
            if vosc and vosc > 0: km_data[km]['vosc'].append(vosc)
            vr = r.get('vertical_ratio')
            if vr and vr > 0: km_data[km]['vr'].append(vr)

        splits = []
        for km in sorted(km_data.keys()):
            d = km_data[km]
            sp_avg = safe_avg(d['sp'])
            splits.append({
                'km': km,
                'pace': mps2pace(sp_avg) if sp_avg else '',
                'hr': str(round(safe_avg(d['hr']))) if safe_avg(d['hr']) else '',
                'cadence': str(round(safe_avg(d['cad']))) if safe_avg(d['cad']) else '',
                'stride': str(round((safe_avg(d['stride']) or 0)/10, 1)) if safe_avg(d['stride']) else '',
                'power': str(round(safe_avg(d['pwr']))) if safe_avg(d['pwr']) else '',
                'stance': str(round(safe_avg(d['stance']))) if safe_avg(d['stance']) else '',
                'vosc': str(round(safe_avg(d['vosc']) or 0, 1)) if safe_avg(d['vosc']) else '',
                'vratio': str(round(safe_avg(d['vr']) or 0, 1)) if safe_avg(d['vr']) else '',
            })
        sets.append({'set': set_num, 'splits': splits})

    # Heuristic session type
    n_main = len(main_laps)
    n_strides = sum(1 for _, _, l in boundaries if l.get('_tag') == 'STRIDE')
    total_main_km = sum((l.get('total_distance', 0) or 0)/1000 for l in main_laps)

    if n_strides >= 4:
        stype = 'easy'
    elif n_main == 1:
        if total_main_km >= 20: stype = 'long'
        elif total_main_km >= 8: stype = '10km'
        else: stype = 'easy'
    elif n_main == 3:
        stype = '3x5km' if total_main_km / max(n_main, 1) >= 4 else '3x3km'
    else:
        stype = 'easy'

    fname = os.path.basename(path)
    fp = fingerprint(path)

    return {
        'id': int(local.timestamp() * 1000) if start else 0,
        'date': date,
        'type': stype,
        'shoe': '',
        'surface': 'Road',
        'temp': temp,
        'humidity': '',
        'rpe': 0,
        'highlighted': False,
        'fitFp': fp,
        'fitFile': fname,
        'notes': '',
        'wu': wu,
        'cd': cd,
        'sets': sets if sets else [{'set': 1, 'splits': []}],
    }


def main():
    # Load existing sessions
    if os.path.exists(OUTPUT):
        with open(OUTPUT) as f:
            existing = json.load(f)
    else:
        existing = []

    existing_fps = {s['fitFp'] for s in existing if s.get('fitFp')}
    added = 0

    for fname in sorted(os.listdir(FITS_DIR)):
        if not fname.endswith('.fit'):
            continue
        fpath = os.path.join(FITS_DIR, fname)
        fp = fingerprint(fpath)
        if fp in existing_fps:
            print(f"SKIP (duplicate): {fname}")
            continue
        try:
            sess = parse_fit(fpath)
            existing.append(sess)
            existing_fps.add(fp)
            added += 1
            n_splits = sum(len(st['splits']) for st in sess['sets'])
            print(f"OK: {fname} | {sess['date']} | {sess['type']} | {n_splits} splits")
        except Exception as e:
            print(f"ERR: {fname}: {e}")

    # Sort by date
    existing.sort(key=lambda s: s['date'])

    with open(OUTPUT, 'w') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Added {added} new sessions. Total: {len(existing)}")


if __name__ == '__main__':
    main()
