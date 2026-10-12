# Apophis DEM visualisation pipeline

Turns PHANTOM discrete-element (DEM) simulation dumps of a rubble-pile asteroid
into Blender Cycles renders: the grains, Earth, and a camera that tracks the body
through the flyby.

The code is split across two repos that sit side by side:

| Repo | Folder | What it holds |
|------|--------|---------------|
| `TOADSILIKETHEM/sobol` | `sobol/` | Render driver (`render_dumps.py`), setup tool, sim + render TUI |
| `TOADSILIKETHEM/HonoursWin` | `Code/` | Dump readers, preprocess, Blender scripts (this README) |

## What you need

- **Host:** Linux, or Windows with WSL2 (Ubuntu). Both are tested.
  - On WSL you can run either a Linux Blender inside WSL or the Windows `blender.exe`.
- **Blender 5.2.x** (tested on 5.2.1 LTS).
  - Blender's own Python needs `pandas`, which Blender doesn't ship: run `<blender dir>/5.2/python/bin/python3.13 -m pip install pandas`. On Windows the Python is in `C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe`; run it from an admin terminal.
  - On a minimal Linux or WSL install, Blender also needs X libraries: `sudo apt install libsm6 libice6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libgl1`.
- **Python 3.11+**, for the driver and the preprocess.
- **GPU:** NVIDIA (OPTIX/CUDA), AMD (HIP), Intel (oneAPI) or Apple (Metal).
  - With no supported GPU, set `--device cpu` in `setup_paths.py` (below). It's much slower, so keep `--samples` low.

## Install

```bash
mkdir ~/viz && cd ~/viz
git clone git@github.com:TOADSILIKETHEM/sobol.git sobol
git clone git@github.com:TOADSILIKETHEM/HonoursWin.git Code
python3 -m venv venv && . venv/bin/activate
pip install -r sobol/requirements.txt -r Code/requirements-preprocess.txt
```

Get `honours_viz_pack.zip` from Max and unzip it anywhere. It contains:
- one example run (391 grains, 97 frames, hyperbolic flyby past Earth);
- the public JPL Apophis shape model.

It has **no** Blender materials, textures or starfield. Without them the renders
still work: Earth is a plain sphere, the grains are a plain rock colour and the sky
is black. If you have your own, put them in the assets folder (see below) under
`Blenders/11.blend` (material "Procedural rock"), `TheEarth1.blend` (objects
Surface/Atmosphere/Clouds) and the HDRI path that `setup_paths.py --check` prints.

## Configure

```bash
python3 sobol/setup_paths.py --data-dir <pack>/data --blender <path to blender> \
    --python ~/viz/venv/bin/python [--device cpu]
python3 sobol/setup_paths.py --check
```

This writes `Code/local_paths.json`, which git ignores. Every row in `--check` must
say `OK`; rows marked `warn` are optional assets. Keys, and the env vars that
override them:

| Key | Env override | Meaning |
|-----|--------------|---------|
| `data_dir` | `HONOURS_DATA_DIR` | Outputs go to `<data_dir>/DEMCSVs/<name>/` |
| `assets_dir` | `HONOURS_BLENDER_ASSETS_DIR` | Optional `.blend`/HDRI assets (default `<data_dir>/BlenderConvert`) |
| `blender_exe` | `HONOURS_BLENDER_EXE` | Blender 5.2 executable, as a path or a name on `PATH` |
| `preprocess_python` | `HONOURS_PREPROCESS_PYTHON` | Python with `requirements-preprocess.txt` |
| `cycles_device` | `HONOURS_CYCLES_DEVICE` | `gpu` (default) or `cpu` |
| `wsl_distro` | `WSL_DISTRO_NAME` | WSL distro name, used to turn `/home/...` into `\\wsl.localhost\<distro>\...` for Windows programs (written automatically) |
| - | `HONOURS_PATHS_FILE` | Use a different config file |
| - | `HONOURS_CODE_DIR` | `Code/` checkout, if it is not next to `sobol/` |

On WSL with the Windows `blender.exe`, give WSL paths (`/mnt/c/...`, `/home/...`).
The tools convert them for Windows programs, and forward the `HONOURS_*` overrides
through `WSLENV`.

## First render

```bash
python3 sobol/render_dumps.py <pack>/example_run/run_0001 --name example \
    --samples 32 --max-frames 10 --resolution 960x540
```

Frames land in `<data_dir>/DEMCSVs/example/run_0001_render_instance_grains/`. Relative paths are fine; the tools store and pass absolute ones. If an optional asset was missing, the result line ends with `WARNING missing assets (plain fallback): ...`.
Drop `--max-frames` for the full run, raise `--samples` (default 500) for less
noise, and add `--video` for an mp4. `--paths instance_grains composite` also
renders the composite view (envelope mesh plus ejecta).

## Your own dumps

`render_dumps.py` reads a PHANTOM run folder directly.

- **A run made by `sobol`** has `sobol_00000, sobol_00001, ...` and a `sobol.setup`. Pass the folder; nothing else is needed.
- **Any other PHANTOM DEM run** (different dump prefix, no `sobol.setup`) needs you to describe it:

  ```bash
  python3 sobol/render_dumps.py <run dir> --prefix body --dem-model particle \
      --np-apophis 32530 --apophis-only --name my_run
  ```

  - `--dem-model particle`: grains are SPH-type particles (current DEM).
  - `--dem-model sink`: grains are sink particles (older DEM).
  - `--np-apophis`: number of grains. Dumps with far fewer grains are treated as partial dumps and skipped.
  - `--apophis-only`: the dumps contain no Earth/Moon/Sun sink particles.

  The tool refuses to guess `--dem-model`: reading particle dumps as sinks fails silently.
- **A `phantomflyby` run** (one sink, the Earth perturber, no Sun) needs `--encounter hyperbola`, so the sink is named Earth and placed/spun. Without it a lone sink is read as the Sun and the tool stops before Blender (`--encounter ephemeris` renders it as the Sun anyway).
- Renamed dumps are hardlinked into a temporary `_staged_<run dir name>/` folder beside the dumps and removed once read; your dumps are never changed. If that folder can't be written, use `--stage-dir <dir>`. If it can't hardlink, it symlinks, or copies when the reader is a Windows `python.exe`.
- Output folders are named after the run directory when it is `run_NNNN` (as `sobol` names them), otherwise `run_0001`.

## Units and data

- PHANTOM code units: `udist = 1 km`, `umass = 1 solar mass`, `G = 1`.
- Grains are drawn 50 times larger than the body offset (`GRAIN_VIS_SCALE`), so the body stays visible next to Earth.
- The intermediate formats (bodies CSV, grain `.npz`, viz manifests) are described in `Code/docs/PIPELINE_REFERENCE.md`. A converter from a different DEM code would write those.

## Other entry points

- `sobol/tui_sim_render.py` runs a PHANTOM sim, converts it and renders, all in one terminal UI. It needs a PHANTOM build (`sobol/CLAUDE.md`). It is also the only route to the `per_sphere` and `instance_static` render paths.
- The Blender scripts in `BlenderConvert/` can be pasted into Blender's Scripting tab. Set the paths in their Configuration block. If Blender is started outside this checkout, set `HONOURS_CODE_DIR` first.
- The point-mass scripts (`CSVconvert/ToCSVFirst.py`, `BlenderConvert/CSVtoBlender.py`, `OnlyEarth_ApophisTrueSize.py`, `workinglargescaleimport.py`) are legacy. Edit the constants at the top of each.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No GPU found for Cycles` | `setup_paths.py --device cpu`, or install the GPU driver |
| `ModuleNotFoundError: pandas` in `render.log` | Install pandas into Blender's Python (see What you need) |
| `libSM.so.6: cannot open shared object file` | Install the X libraries (see What you need) |
| `preprocess python not found` / `missing: sarracen` | Point `--python` at the venv with `requirements-preprocess.txt` |
| `has no sobol.setup ... pass --dem-model` | See Your own dumps |
| Black sky, plain grains, warnings about `11.blend` / `TheEarth1.blend` / HDRI | Expected without the optional assets |
| Anything else | `python3 sobol/setup_paths.py --check`, then the `render.log` / `preprocess.log` next to the frames |
