"""Where data, Blender assets and tools live on this machine.

Imported by WSL/Linux python (sobol TUI, converters), the preprocess python
(Windows .venv or native) and Blender's bundled python, so stdlib only.

Precedence: environment variable > local_paths.json next to this file
(gitignored; write it with sobol/setup_paths.py) > the defaults below, which
are Max's laptop as hardcoded before 2026-10-10 -- no file = no change.
Paths are stored as the TUI host sees them (WSL/Linux POSIX paths);
host_path() turns one into what the current interpreter can open.
"""
import json
import os
import re
import shutil
from pathlib import Path

CONFIG_NAME = "local_paths.json"

_DEFAULTS = {
    "data_dir": "/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code",
    "assets_dir": None,  # None = <data_dir>/BlenderConvert
    "blender_exe": "/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe",
    "preprocess_python": None,  # None = <data_dir>/.venv/Scripts/python.exe
    "cycles_device": "gpu",
    "wsl_distro": "Ubuntu",
}
KEYS = tuple(_DEFAULTS)
# HONOURS_BLENDER_ASSETS_DIR predates this module; keep its name.
_ENV = {
    "data_dir": "HONOURS_DATA_DIR",
    "assets_dir": "HONOURS_BLENDER_ASSETS_DIR",
    "blender_exe": "HONOURS_BLENDER_EXE",
    "preprocess_python": "HONOURS_PREPROCESS_PYTHON",
    "cycles_device": "HONOURS_CYCLES_DEVICE",
    "wsl_distro": "WSL_DISTRO_NAME",
}
_DEVICES = ("gpu", "cpu")
_MNT_DRIVE_RE = re.compile(r"^/mnt/([a-zA-Z])(/.*)?$")
_WIN_DRIVE_RE = re.compile(r"^([a-zA-Z]):[\\/](.*)$")
_PATH_KEYS = ("data_dir", "assets_dir", "blender_exe", "preprocess_python")

_cache = None


class ConfigError(ValueError):
    pass


def config_file() -> Path:
    env = os.environ.get("HONOURS_PATHS_FILE")
    return Path(env) if env else Path(os.path.dirname(os.path.abspath(__file__))) / CONFIG_NAME


def _read_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfigError(f"{path}: not valid JSON ({exc})") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a JSON object")
    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        raise ConfigError(f"{path}: unknown key(s) {unknown}; allowed: {list(KEYS)}")
    bad = sorted(k for k, v in data.items() if v is not None and not isinstance(v, str))
    if bad:
        raise ConfigError(f"{path}: {bad} must be strings (paths or names)")
    return data


def load(reload: bool = False) -> dict:
    global _cache
    if _cache is not None and not reload:
        return _cache
    path = config_file()
    cfg = dict(_DEFAULTS)
    cfg.update({k: v for k, v in _read_file(path).items() if v is not None})
    for key, var in _ENV.items():
        if os.environ.get(var):
            cfg[key] = os.environ[var]
    if os.name != "nt":  # "C:/x" as typed on a Windows-minded machine -> /mnt/c/x for WSL python
        for key in _PATH_KEYS:
            cfg[key] = _from_windows_drive(cfg[key])
    cfg["data_dir"] = cfg["data_dir"].rstrip("/\\")
    if cfg["assets_dir"] is None:
        cfg["assets_dir"] = cfg["data_dir"] + "/BlenderConvert"
    if cfg["preprocess_python"] is None:
        cfg["preprocess_python"] = cfg["data_dir"] + "/.venv/Scripts/python.exe"
    cfg["cycles_device"] = str(cfg["cycles_device"]).lower()
    if cfg["cycles_device"] not in _DEVICES:
        raise ConfigError(f"{path}: cycles_device must be one of {_DEVICES}, got {cfg['cycles_device']!r}")
    _cache = cfg
    return cfg


def _from_windows_drive(p):
    m = _WIN_DRIVE_RE.match(p) if isinstance(p, str) else None
    if not m:
        return p
    return f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/")


def data_dir() -> str:
    return load()["data_dir"]


def assets_dir() -> str:
    return load()["assets_dir"]


def blender_exe() -> str:
    return load()["blender_exe"]


def preprocess_python() -> str:
    return load()["preprocess_python"]


def cycles_device() -> str:
    return load()["cycles_device"]


def to_windows_path(p, distro=None) -> str:
    """WSL path -> path string a Windows program can open.

    /mnt/<drive>/... -> <DRIVE>:/...; any other POSIX-absolute path (e.g. the
    code under /home) -> \\\\wsl.localhost\\<distro>\\... . On WSL, POSIX-absolute
    inputs are resolved first (so "/mnt/c/foo/../bar" normalizes before the
    swap); a string that doesn't start with "/" -- e.g. an already
    Windows-style "C:/Users/..." -- is returned unchanged.
    """
    s = str(p)
    if not s.startswith("/"):
        return s
    if os.name != "nt":  # resolve() on Windows would mangle a POSIX path
        s = str(Path(s).resolve())
    m = _MNT_DRIVE_RE.match(s)
    if m:
        return f"{m.group(1).upper()}:{m.group(2) or '/'}"
    # env read here too, not only via load(): load() is cached, so a later env change would be missed
    distro = distro or os.environ.get("WSL_DISTRO_NAME") or load()["wsl_distro"]
    return "\\\\wsl.localhost\\" + distro + s.replace("/", "\\")


def host_path(p) -> str:
    """A configured (POSIX) path as this interpreter can open it."""
    return to_windows_path(p) if os.name == "nt" else str(p)


def is_windows_tool(exe) -> bool:
    """A Windows .exe launched from a POSIX host (WSL): needs Windows-form paths
    and WSLENV-forwarded env vars, and can't follow WSL symlinks."""
    return os.name != "nt" and str(exe).lower().endswith(".exe")


def exe_available(exe) -> bool:
    """A path to an existing file, or a bare name found on PATH."""
    return Path(exe).is_file() or shutil.which(str(exe)) is not None


def tool_path(p, exe) -> str:
    """Path argument for a child process: Windows form only when a POSIX host
    (WSL) launches a Windows .exe; native tools get the path unchanged."""
    if is_windows_tool(exe):
        return to_windows_path(p)
    return str(p)


# Overrides a Windows child (blender.exe, .venv python.exe) must see. WSL only
# passes env vars named in WSLENV; /p converts a WSL path to a Windows one.
_CHILD_VARS = {
    "HONOURS_PATHS_FILE": "/p",
    "HONOURS_DATA_DIR": "/p",
    "HONOURS_BLENDER_ASSETS_DIR": "/p",
    "HONOURS_CODE_DIR": "/p",
    "HONOURS_CYCLES_DEVICE": "",
}


def child_env(exe, environ=None):
    """Env for launching exe, or None (= inherit unchanged). Only a Windows .exe
    started from a POSIX host (WSL) needs HONOURS_* overrides listed in WSLENV."""
    environ = dict(os.environ if environ is None else environ)
    if not is_windows_tool(exe):
        return None
    # /p only for a WSL path: it mangles one already in Windows form (D:/x -> D;\\wsl...)
    wanted = [k + (flag if environ[k].startswith("/") else "")
              for k, flag in _CHILD_VARS.items() if environ.get(k)]
    if not wanted:
        return None
    have = [v for v in environ.get("WSLENV", "").split(":") if v]
    names = {v.split("/")[0] for v in have}
    environ["WSLENV"] = ":".join(have + [w for w in wanted if w.split("/")[0] not in names])
    return environ
