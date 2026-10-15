# Rendering on a second Windows machine (no WSL)

The laptop (WSL, all code and dumps) preprocesses a run and queues its renders.
Any Windows machine that syncs the same OneDrive renders them with its own
Blender and GPU. Frames sync back. The second machine needs no WSL, no
PHANTOM, no sarracen and no dumps: only this repo, Blender 5.2 and pandas.

```
laptop (WSL)                                   OneDrive                                  desktop (Windows)
render_dumps.py ... --queue  ──►  DEMCSVs/<name>/run_0001_viz_instance/  (~13 MB)  ──►  render_queue.py
                                  DEMCSVs/_render_queue/<job>.json                       └► blender.exe (GPU)
                              ◄── DEMCSVs/<name>/run_0001_render_*/frame_*.png, animation.mp4 ◄──
```

Tested 2026-10-15 on the laptop: queue (WSL) → runner under Blender's Windows Python → 3 frames + mp4 on OPTIX.

## Queue a run (laptop, WSL)

Same flags as a normal `render_dumps.py` render, plus `--queue`:

```bash
python3 sobol/render_dumps.py mia_ozstar/fullsize/<run> --name mia_full_<run> --prefix fly \
  --dem-model particle --np-apophis <N> --encounter hyperbola \
  --samples 100 --slowmo 5 --video --camera-mode auto earth_chase --queue
```

- One job per path × camera in `DEMCSVs/_render_queue/`. `--resume` is always on in jobs.
- Without `--queue` the laptop renders that run itself. Split work by run: queue some, render others locally. Never both for the same run.

## One-time setup (desktop)

Do these in order; each has a check.

1. **OneDrive.** `%USERPROFILE%\OneDrive\Documents\GC-Max_desktop\Honours\Code\DEMCSVs\_render_queue` must exist (made 2026-10-15). If the OneDrive root differs, note the real path for step 4.
2. **Code checkout, outside OneDrive.** The OneDrive `Code` folder holds stale old copies of the scripts; never run code from there.
   ```powershell
   git clone https://github.com/TOADSILIKETHEM/HonoursWin.git $env:USERPROFILE\HonoursCode\Code
   ```
   (Private repo: `gh auth login` or a Git Credential Manager login first.) Update later with `git -C $env:USERPROFILE\HonoursCode\Code pull`.
3. **Blender 5.2 LTS + pandas.** Check for `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`; else install 5.2.x from blender.org (`winget install BlenderFoundation.Blender.LTS.5.2` if winget lists it). Then, in an **admin** terminal:
   ```powershell
   & "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -m pip install pandas
   & "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -c "import pandas; print(pandas.__version__)"
   ```
4. **`local_paths.json`** in the checkout (`%USERPROFILE%\HonoursCode\Code\local_paths.json`, gitignored). Forward slashes:
   ```json
   {
     "data_dir": "C:/Users/<you>/OneDrive/Documents/GC-Max_desktop/Honours/Code",
     "blender_exe": "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe",
     "cycles_device": "gpu"
   }
   ```
   `assets_dir` defaults to `<data_dir>/BlenderConvert` (`Blenders/11.blend`, `TheEarth1.blend`, HDRI), which OneDrive already syncs.
5. **Check:** `& "<blender python>" -I $env:USERPROFILE\HonoursCode\Code\render_queue.py --list` prints the queue (not "no _render_queue/").
6. **GPU test**, once a job is queued: `... render_queue.py --max-frames 2`. It renders 2 frames and leaves the job queued. Open the frames; `render.log` in the output folder should show `Cycles device=GPU backend=OPTIX` (or CUDA/HIP). An AMD/Intel GPU is picked up automatically; with none, set `"cycles_device": "cpu"`.

`<blender python>` = `C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe`. Any Python 3.9+ also works; the runner is standard library only.

## Render (desktop)

```powershell
& "<blender python>" -I $env:USERPROFILE\HonoursCode\Code\render_queue.py --watch 10
```

Renders every ready job, then checks again every 10 min. Leave the window open (or run it from a `.bat` in Startup). Without `--watch` it does one pass and stops.

- Job states: `*.json` queued; `*.json.<host>.running` rendering; `done/`; `failed/` (log at `<output_dir>\render.log`; move the file back up to retry).
- A stopped render (closed window, reboot) is picked up first next time and resumes from the frames on disk.
- Jobs whose inputs are still syncing print `wait ...` and are retried next pass.
- Keep the laptop from editing a folder the desktop is rendering into: OneDrive makes `-<PC name>` conflict copies.

## Traps

- **Code version.** The desktop renders with whatever `HonoursWin` master holds. Uncommitted laptop changes (e.g. a Blender look tweak) are not there: commit + push and `git pull` on the desktop, or the two machines' frames will differ.
- **Stale copies.** Never run `render_queue.py` or Blender scripts from the OneDrive `Code\BlenderConvert` folder (see `../CLAUDE.md` § Stale-copy trap).
- **Disk.** A 251-frame 1080p render is ~300 MB of PNGs, synced to both machines.
