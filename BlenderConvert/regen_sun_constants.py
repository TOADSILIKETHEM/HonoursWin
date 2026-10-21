"""Regenerate the real-2029 constants in sun_geometry.py from JPL Horizons.

Stdlib + numpy (via sun_geometry). Queries Horizons VECTORS for Apophis (99942)
and the Sun (10), geocentric (CENTER='500@399'), ecliptic of J2000, km and km/s,
1-minute steps over 2029-04-13 21:30-22:00 TDB. Takes the minimum-|r| Apophis row
as closest approach and prints the constant lines to paste into sun_geometry.py,
plus the Sun in the pericentre frame as a check.

Needs network access. Run: python3 regen_sun_constants.py
"""

import csv
import datetime
import io
import json
import math
import urllib.parse
import urllib.request

import numpy as np

import sun_geometry

API = 'https://ssd.jpl.nasa.gov/api/horizons.api'
START, STOP, STEP = '2029-04-13 21:30', '2029-04-13 22:00', '1 min'


def fetch_rows(command):
    """Horizons VECTORS rows for ``command`` as (calendar string, 6 floats: x y z vx vy vz)."""
    params = {
        'format': 'json', 'COMMAND': f"'{command}'", 'EPHEM_TYPE': 'VECTORS',
        'CENTER': "'500@399'", 'REF_PLANE': 'ECLIPTIC', 'REF_SYSTEM': 'ICRF',
        'OUT_UNITS': 'KM-S', 'VEC_TABLE': '2', 'CSV_FORMAT': 'YES', 'TIME_TYPE': 'TDB',
        'START_TIME': f"'{START}'", 'STOP_TIME': f"'{STOP}'", 'STEP_SIZE': f"'{STEP}'",
    }
    url = API + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as resp:
        text = json.load(resp)['result']
    block = text.split('$$SOE')[1].split('$$EOE')[0]
    rows = []
    for rec in csv.reader(io.StringIO(block.strip())):
        if len(rec) < 8:
            continue
        rows.append((rec[1].strip(), [float(c) for c in rec[2:8]]))
    return rows


def main():
    apo = fetch_rows('99942')
    sun = fetch_rows('10')
    i = min(range(len(apo)), key=lambda k: np.linalg.norm(apo[k][1][:3]))
    when, state = apo[i]
    assert sun[i][0] == when, (sun[i][0], when)
    r, v = np.array(state[:3]), np.array(state[3:])
    s = np.array(sun[i][1][:3])
    d_sun = np.linalg.norm(s)
    s_unit = s / d_sun
    print(f'# closest approach row: {when}  |r| = {np.linalg.norm(r):.1f} km')
    t = datetime.datetime.strptime(when.replace('A.D. ', '').split('.')[0], '%Y-%b-%d %H:%M:%S')
    print(f"CA_EPOCH_TDB = '{t:%Y-%m-%d %H:%M:%S}'")
    print(f'R_CA_KM = ({r[0]:.10f}, {r[1]:.10f}, {r[2]:.10f})')
    print(f'V_CA_KMS = ({v[0]:.10f}, {v[1]:.10f}, {v[2]:.10f})')
    print(f'SUN_CA_UNIT = ({s_unit[0]:.10f}, {s_unit[1]:.10f}, {s_unit[2]:.10f})')
    print(f'SUN_DISTANCE_CA_KM = {d_sun:.1f}')
    ang = math.asin(sun_geometry.SUN_RADIUS_KM / d_sun)
    print(f'# angular radius {ang:.6f} rad = {math.degrees(ang):.4f} deg')
    F = sun_geometry.pericentre_frame(r, v)
    print('Sun in pericentre frame: (%.4f, %.4f, %.4f)' % tuple(F @ s_unit))


if __name__ == '__main__':
    main()
