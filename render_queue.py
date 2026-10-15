"""Render the jobs another machine queued with sobol/render_dumps.py --queue.

The queueing machine preprocesses the dumps and writes the viz inputs plus one
job file per render into <data_dir>/DEMCSVs/ (synced by OneDrive). This script,
on the rendering machine, runs Blender on each job and writes the frames beside
them, so they sync back. Standard library only: Blender's own Python runs it.

    <python> Code/render_queue.py            # render every ready job, then stop
    <python> Code/render_queue.py --watch 10 # ... then look again every 10 min
    <python> Code/render_queue.py --list     # show the queue
    [--root DIR] [--blender EXE] [--max-frames N]  (--max-frames: test render, job stays queued)

Jobs: <root>/_render_queue/*.json (root default <data_dir>/DEMCSVs). A job being
rendered is renamed *.json.<host>.running; a finished one moves to done/, a
failed one to failed/ (move it back to retry). Every render runs with --resume,
so a stopped job restarted here keeps the frames it already has. A job whose
inputs have not finished syncing is skipped until a later pass.
Setup on a new machine: Code/docs/DESKTOP_RENDER.md.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))
import honours_paths  # noqa: E402

QUEUE_DIR_NAME = "_render_queue"  # sobol/render_dumps.py writes the same name
HEADLESS = CODE_DIR / "BlenderConvert" / "DEMHeadlessRender.py"
HOST = socket.gethostname()


def default_root() -> Path:
    return Path(honours_paths.host_path(honours_paths.data_dir())) / "DEMCSVs"


def inputs_ready(root: Path, job: dict) -> str:
    """'' when the job's viz inputs are all here, else what is still missing."""
    manifest = root / job["manifest"]
    if not manifest.is_file():
        return f"no {job['manifest']}"
    try:
        m = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"{job['manifest']} unreadable (still syncing?)"
    n = int(m.get("n_frames") or 0)
    viz = manifest.parent
    if m.get("points_dir"):
        have = len(list((viz / m["points_dir"]).glob("*.npz")))
        if have < n:
            return f"{have}/{n} point files"
    if m.get("bodies_csv_dir"):
        have = len(list((viz / m["bodies_csv_dir"]).glob("*.csv")))
        if have < n:
            return f"{have}/{n} bodies CSVs"
    return ""


def blender_command(root: Path, job: dict, blender: str, max_frames=None) -> list:
    args = list(job["args"])
    for flag in ("--manifest", "--output-dir"):
        i = args.index(flag) + 1
        args[i] = honours_paths.tool_path(root / args[i], blender)
    if max_frames is not None:
        if "--max-frames" in args:
            args[args.index("--max-frames") + 1] = str(max_frames)
        else:
            args += ["--max-frames", str(max_frames)]
        if "--encode-video" in args:  # a test render makes no mp4
            args.remove("--encode-video")
            if "--video-fps" in args:
                i = args.index("--video-fps")
                del args[i:i + 2]
    # --python-exit-code 1: without it Blender exits 0 after an uncaught exception
    return [blender, "--background", "--python-exit-code", "1", "--python",
            honours_paths.tool_path(HEADLESS, blender), "--", *args]


def run_job(root: Path, path: Path, blender: str, max_frames=None) -> bool:
    job = json.loads(path.read_text(encoding="utf-8"))
    out = root / job["output_dir"]
    out.mkdir(parents=True, exist_ok=True)
    cmd = blender_command(root, job, blender, max_frames)
    print(f"[{time.strftime('%H:%M:%S')}] render {job['output_dir']}", flush=True)
    t0 = time.monotonic()
    with open(out / "render.log", "a", encoding="utf-8") as log:
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {HOST} render_queue.py\n")
        log.flush()
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                            env=honours_paths.child_env(blender)).returncode
    frames = len(list(out.glob("frame_*.png")))
    ok = rc == 0 and frames > 0
    print(f"  {'done' if ok else 'FAILED'}: rc {rc}, {frames} frames, "
          f"{(time.monotonic() - t0) / 60:.1f} min (log: {out / 'render.log'})", flush=True)
    return ok


def claim(path: Path) -> Path:
    running = path.with_name(f"{path.name}.{HOST}.running")
    os.replace(path, running)
    return running


def finish(running: Path, ok: bool) -> None:
    dest = running.parent / ("done" if ok else "failed")
    dest.mkdir(exist_ok=True)
    os.replace(running, dest / running.name.split(f".{HOST}.running")[0])


def one_pass(root: Path, blender: str, max_frames=None) -> int:
    """Render every ready job once; return how many ran."""
    qdir = root / QUEUE_DIR_NAME
    # this host's own *.running first: a render stopped mid-way (closed window, reboot)
    jobs = sorted(qdir.glob(f"*.json.{HOST}.running")) + sorted(qdir.glob("*.json"))
    ran = 0
    for path in jobs:
        if not path.exists():  # another machine took it
            continue
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"skip {path.name}: unreadable (still syncing?)", flush=True)
            continue
        missing = inputs_ready(root, job)
        if missing:
            print(f"wait {path.name}: {missing}", flush=True)
            continue
        if max_frames is not None:  # test: leave the job queued
            ran += 1
            run_job(root, path, blender, max_frames)
            continue
        running = path if path.name.endswith(".running") else claim(path)
        ran += 1
        finish(running, run_job(root, running, blender))
    return ran


def show(root: Path) -> None:
    qdir = root / QUEUE_DIR_NAME
    for label, pattern in (("queued", "*.json"), ("running", "*.running"),
                           ("failed", "failed/*.json"), ("done", "done/*.json")):
        names = sorted(p.name for p in qdir.glob(pattern))
        print(f"{label}: {len(names)}")
        for n in names if label != "done" else names[-5:]:
            print(f"  {n}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--root", type=Path, help="DEMCSVs folder (default <data_dir>/DEMCSVs)")
    p.add_argument("--blender", help="Blender executable (default blender_exe in local_paths.json)")
    p.add_argument("--watch", type=float, metavar="MIN", help="keep looking for new jobs every MIN minutes")
    p.add_argument("--max-frames", type=int, help="test render of N frames; jobs stay queued")
    p.add_argument("--list", action="store_true", help="show the queue and exit")
    a = p.parse_args(argv)
    root = (a.root or default_root()).expanduser()
    if not (root / QUEUE_DIR_NAME).is_dir():
        sys.exit(f"no {QUEUE_DIR_NAME}/ in {root}: wrong --root / data_dir, or nothing queued yet")
    if a.list:
        show(root)
        return 0
    blender = a.blender or honours_paths.blender_exe()
    if not honours_paths.exe_available(blender):
        sys.exit(f"Blender not found: {blender} (set blender_exe with sobol/setup_paths.py or pass --blender)")
    while True:
        ran = one_pass(root, blender, a.max_frames)
        if a.watch is None:
            print(f"QUEUE_PASS_DONE ({ran} job(s))", flush=True)
            return 0
        if not ran:
            time.sleep(a.watch * 60)


if __name__ == "__main__":
    sys.exit(main())
