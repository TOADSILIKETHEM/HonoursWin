"""Earth orientation (spin phase + axial tilt) in the sim's J2000 ecliptic frame.

Pure Python, no bpy -- imported by DEMCinematicSetup.py and
DEMGrainsBlenderEarthCam.py, tested by tests/test_earth_orientation.py.

Frames:
  body  = Earth-fixed (TheEarth1.blend local axes): +X Greenwich meridian on
          the equator, +Y 90 deg E, +Z north pole. Checked 2026-10-04 from the
          Surface UVs: u=0.5 -> +X, u=0.75 -> +Y, top -> +Z (NASA equirect maps).
  J2000 = Horizons "Ecliptic of J2000.0" (sobol/earth.txt).
  sim   = bodies CSV x/y/z and Blender scene axes = J2000 rotated +90 deg about
          the ecliptic pole: set_solarsystem's add_body passes the Horizons
          node longitude to set_binary as posang_ascnode, and set_binary.f90
          uses big_omega = posang_ascnode + pi/2. Shift is uniform for Sun,
          planets, Moon, Apophis (checked on a real run: Earth heliocentric
          longitude 290.07 vs 200.01 J2000).

Chain: body -R_z(GMST)-> mean equator of date -R_x(-eps_A)-> mean ecliptic of
date -R_z(-p_A)-> J2000 ecliptic -R_z(SIM_FRAME_ROTATION_DEG)-> sim. Sim time_s is TDB seconds since the
.setup ``epoch``; UT1 = TDB - DELTA_T_S. Neglected: nutation (<= ~20 arcsec),
ecliptic motion (~47 arcsec/century), polar motion -- all far below a pixel.
"""

import math
from datetime import datetime

EARTH_SIDEREAL_DAY_S = 86164.0905
# TT - UT1 (TDB ~= TT to 2 ms). ~69.1 s in 2025; 1 s = 0.004 deg of spin.
DELTA_T_S = 69.0
# phantom/src/setup/setup_solarsystem.f90 default and every sobol.setup so far.
DEFAULT_EPOCH_TDB = '2029-04-10'
# phantom/src/setup/set_binary.f90: big_omega = posang_ascnode + 0.5*pi.
SIM_FRAME_ROTATION_DEG = 90.0

_J2000_JD = 2451545.0
_ARCSEC = math.pi / (180.0 * 3600.0)


def julian_date(epoch):
    """JD of a Horizons-style epoch string ('2029-04-10', '2029-Apr-10 06:00:00', ...)."""
    s = epoch.strip()
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d',
                '%Y-%b-%d %H:%M:%S.%f', '%Y-%b-%d %H:%M:%S', '%Y-%b-%d %H:%M', '%Y-%b-%d'):
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f'unparseable epoch {epoch!r}')
    # Unix epoch 1970-01-01 00:00 = JD 2440587.5 (calendar arithmetic only, no time zone).
    days = (dt - datetime(1970, 1, 1)).total_seconds() / 86400.0
    return 2440587.5 + days


def _gmst_unwrapped_deg(jd_ut1):
    d = jd_ut1 - _J2000_JD
    T = d / 36525.0
    return 280.46061837 + 360.98564736629 * d + 0.000387933 * T * T - T ** 3 / 38710000.0


def gmst_deg(jd_ut1):
    """Greenwich mean sidereal time in degrees (Meeus eq. 12.4, IAU 1982)."""
    return _gmst_unwrapped_deg(jd_ut1) % 360.0


def _quat_axis_angle(axis, angle):
    h = 0.5 * angle
    s = math.sin(h)
    return (math.cos(h), axis[0] * s, axis[1] * s, axis[2] * s)


def _quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def rotate(q, v):
    """Rotate vector v by unit quaternion q = (w, x, y, z)."""
    w, x, y, z = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v); v' = v + w t + cross(q.xyz, t)
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx))


def earth_quaternion(time_s, epoch=DEFAULT_EPOCH_TDB, frame_rotation_deg=SIM_FRAME_ROTATION_DEG):
    """(w, x, y, z) rotating Earth-fixed vectors into the sim frame (J2000
    ecliptic for ``frame_rotation_deg=0``) at ``time_s`` TDB seconds after
    ``epoch``. Feed straight to ``mathutils.Quaternion`` as the Surface/Clouds
    rotation."""
    jd_tdb = julian_date(epoch) + time_s / 86400.0
    T = (jd_tdb - _J2000_JD) / 36525.0
    eps = (84381.406 - 46.836769 * T) * _ARCSEC          # mean obliquity of date (IAU 2006)
    p_A = (5028.796195 * T + 1.1054348 * T * T) * _ARCSEC  # precession in longitude
    # Unwrapped: a 360 deg jump would flip the quaternion's sign, and Blender
    # interpolates quaternion keys per component (q -> -q passes through zero).
    theta = math.radians(_gmst_unwrapped_deg(jd_tdb - DELTA_T_S / 86400.0))
    q_spin = _quat_axis_angle((0.0, 0.0, 1.0), theta)
    q_tilt = _quat_axis_angle((1.0, 0.0, 0.0), -eps)
    q_prec = _quat_axis_angle((0.0, 0.0, 1.0), -p_A + math.radians(frame_rotation_deg))
    return _quat_mul(q_prec, _quat_mul(q_tilt, q_spin))


def ecliptic_to_geographic(vec, time_s, epoch=DEFAULT_EPOCH_TDB, frame_rotation_deg=SIM_FRAME_ROTATION_DEG):
    """Geocentric direction in the sim frame (J2000 ecliptic for
    ``frame_rotation_deg=0``) -> (east longitude, latitude) in degrees."""
    w, x, y, z = earth_quaternion(time_s, epoch, frame_rotation_deg)
    bx, by, bz = rotate((w, -x, -y, -z), vec)
    lon = math.degrees(math.atan2(by, bx))
    lat = math.degrees(math.atan2(bz, math.hypot(bx, by)))
    return lon, lat


class SpinStepCheck:
    """Watches the gaps between Earth spin keys. Blender interpolates quaternion
    keys per component; with the unwrapped GMST above that still turns forward
    up to 360 deg per key (unevenly past ~180 deg) and backwards beyond it.
    ``warning`` returns at most one message per run, for the first bad gap."""

    UNEVEN_DEG = 180.0

    def __init__(self):
        self._prev = None
        self._warned = False

    def warning(self, time_s, frame):
        prev, self._prev = self._prev, time_s
        if prev is None or self._warned:
            return None
        step = abs(time_s - prev) / EARTH_SIDEREAL_DAY_S * 360.0
        if step <= self.UNEVEN_DEG:
            return None
        self._warned = True
        how = ('runs backwards (> 360 deg per key)' if step > 360.0
               else 'turns unevenly (> 180 deg per key)')
        return (f'WARNING: Earth spins {step:.0f} deg between keys at frame {frame}; '
                f'the interpolated spin {how}. Later gaps not reported.')
