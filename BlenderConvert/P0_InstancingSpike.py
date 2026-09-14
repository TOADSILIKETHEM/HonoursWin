"""P0 performance spike — Option A (pure point-instancing) for Objective 3.

Measures whether Geometry Nodes "Instance on Points" holds up at 10^3-10^6 DEM
grains on *this* project's hardware, in **Cycles** (this project's render
engine — not EEVEE).

Spec: docs/superpowers/specs/2026-09-07-million-particle-viz-option-a-pure-instancing-design.md
      Phase P0 / Testing strategy item 5.

What it measures, per (N, subdiv) configuration:
  * Python update time  -- mesh.vertices.foreach_set("co") + radius attribute
                           foreach_set + mesh.update()
  * Depsgraph time      -- GN re-evaluation triggered by the moved points
  * Viewport redraw     -- ms/redraw and FPS, solid + rendered-preview shading
  * Cycles render time  -- s/frame at RENDER_RESOLUTION / RENDER_SAMPLES
  * Peak process RAM    -- Windows peak working set
  * GPU memory          -- via nvidia-smi when available

Nothing here reads simulation data. Points are synthetic, but sized to match
real geometry: a rubble pile of BODY_RADIUS_VIS Blender units whose grains
conserve total volume as N grows, anchored on the spec's np500 reference
(Reff_vis ~ 2.4 BU at N=500).

SAFETY: all work happens in a scratch scene named P0_Spike_Scene. Your current
scene is restored afterwards and the .blend is never saved.

USAGE
-----
A. Blender Scripting tab: set RESULTS_DIR below, press Run Script. Runs every
   configuration in CONFIGS and writes the results table.

B. Step-by-step (e.g. over MCP, to avoid one long blocking call):
       import P0_InstancingSpike as p0   # or exec() the file
       p0.run_one(100_000, subdiv=0)     # appends one row to the results file
       p0.write_report()                 # regenerate the markdown table

Results accumulate in RESULTS_DIR/p0_instancing_results.json, so partial runs
across several invocations still produce one complete table.
"""

import ctypes
import json
import math
import os
import platform
import subprocess
import sys
import time

import bpy
import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RESULTS_DIR = r"C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code\docs"

#: (n_points, icosphere_subdivisions) pairs, cheapest first so an aborted run
#: still leaves useful data.
CONFIGS = [
    (1_000, 0), (1_000, 1),
    (10_000, 0), (10_000, 1),
    (100_000, 0), (100_000, 1),
    (1_000_000, 0), (1_000_000, 1),
]

#: Skip the Cycles render above this N (set lower if 10^6 renders overrun your
#: patience -- update/viewport numbers are still collected).
RENDER_MAX_N = 1_000_000

RENDER_SAMPLES = 32
RENDER_RESOLUTION = (960, 540)

#: Cycles device for the scratch scene. A scene made with bpy.data.scenes.new()
#: defaults to CPU regardless of user preferences, so this must be set
#: explicitly or the spike silently measures CPU rendering.
RENDER_DEVICE = "GPU"

#: Devices swept by run_all(); the GPU/CPU split decides the batch-render budget.
RENDER_DEVICES = ("GPU", "CPU")

#: Frames of simulated motion to time per configuration; reported as a median.
UPDATE_TRIALS = 5
#: Viewport redraws to time per shading mode.
REDRAW_TRIALS = 10

#: Body geometry, from the spec's np500 reference: a ~15 BU pile whose grains
#: are Reff_vis ~ 2.4 BU at N=500 (GRAIN_VIS_SCALE=50).
BODY_RADIUS_VIS = 15.0
REF_N = 500
REF_GRAIN_RADIUS_VIS = 2.4

#: Camera distance as a multiple of BODY_RADIUS_VIS ("typical encounter" framing).
CAMERA_DISTANCE_FACTOR = 4.0

SCRATCH_SCENE_NAME = "P0_Spike_Scene"
RADIUS_ATTR = "radius"

RESULTS_JSON = "p0_instancing_results.json"
RESULTS_MD = "P0_INSTANCING_SPIKE.md"
#: PNGs dropped here (relative to RESULTS_DIR) are embedded in the report.
RENDERS_SUBDIR = "p0_renders"


# ---------------------------------------------------------------------------
# Environment probes
# ---------------------------------------------------------------------------

if platform.system() == "Windows":
    from ctypes import wintypes

    class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    # Explicit restype/argtypes are load-bearing: with ctypes' defaults,
    # GetCurrentProcess returns c_int and truncates the 64-bit pseudo-handle,
    # so GetProcessMemoryInfo fails and silently reports 0 MB.
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcess.argtypes = []
    _psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    _psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS), wintypes.DWORD
    ]


def process_memory_mb():
    """(current_mb, peak_mb) working set of the Blender process.

    ``peak`` never decreases within a session, so ``current`` -- sampled while
    the configuration's scene is still built -- is the per-configuration
    number; ``peak`` bounds the whole run.
    """
    if platform.system() != "Windows":
        try:
            import resource
            # ru_maxrss is KB on Linux, bytes on macOS.
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
            return None, peak
        except Exception:
            return None, None

    try:
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        handle = _kernel32.GetCurrentProcess()
        if not _psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            return None, None
        mib = 1024.0 * 1024.0
        return counters.WorkingSetSize / mib, counters.PeakWorkingSetSize / mib
    except Exception:
        return None, None


def gpu_memory_mb():
    """(device_used_mb, device_total_mb) from nvidia-smi, or (None, None)."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=15,
        ).decode().strip().splitlines()[0]
        used, total = (float(v.strip()) for v in out.split(","))
        return used, total
    except Exception:
        return None, None


def gpu_process_memory_mb():
    """VRAM attributed to this process by nvidia-smi, or None.

    Consumer GPUs in WDDM mode frequently report per-process memory as
    "Not Supported", hence the device-total fallback in :class:`GPUSampler`.
    """
    pid = os.getpid()
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=15,
        ).decode().strip()
    except Exception:
        return None
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        if int(parts[0]) == pid:
            try:
                return float(parts[1])
            except ValueError:
                return None
    return None


class GPUSampler:
    """Poll GPU memory on a background thread for the duration of a render.

    Sampling *after* the render finishes measures nothing -- the allocation is
    already released -- so the peak must be captured while Cycles is running.
    """

    def __init__(self, interval=0.25):
        self.interval = interval
        self._thread = None
        self._stop = None
        self.baseline_device_mb = None
        self.peak_device_mb = None
        self.peak_process_mb = None

    def _run(self):
        while not self._stop.is_set():
            used, _total = gpu_memory_mb()
            if used is not None:
                self.peak_device_mb = (
                    used if self.peak_device_mb is None
                    else max(self.peak_device_mb, used)
                )
            per_process = gpu_process_memory_mb()
            if per_process is not None:
                self.peak_process_mb = (
                    per_process if self.peak_process_mb is None
                    else max(self.peak_process_mb, per_process)
                )
            self._stop.wait(self.interval)

    def __enter__(self):
        import threading
        self.baseline_device_mb, _ = gpu_memory_mb()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        return False

    @property
    def device_delta_mb(self):
        """Peak device usage above the pre-render baseline."""
        if self.peak_device_mb is None or self.baseline_device_mb is None:
            return None
        return max(0.0, self.peak_device_mb - self.baseline_device_mb)


def environment_info():
    scene = bpy.context.scene
    info = {
        "blender_version": bpy.app.version_string,
        "blender_version_tuple": list(bpy.app.version),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor(),
        "background": bool(bpy.app.background),
        "render_engine_at_start": scene.render.engine,
    }
    cycles_addon = bpy.context.preferences.addons.get("cycles")
    if cycles_addon:
        prefs = cycles_addon.preferences
        info["cycles_compute_device_type"] = prefs.compute_device_type
        try:
            info["cycles_devices"] = [
                {"name": d.name, "type": d.type, "enabled": bool(d.use)}
                for d in prefs.devices
            ]
        except Exception:
            info["cycles_devices"] = None
        try:
            # The startup scene's device, recorded for reference only: the
            # spike's scratch scene sets its own device per configuration.
            info["startup_scene_device"] = scene.cycles.device
        except Exception:
            info["startup_scene_device"] = None
    gpu_used, gpu_total = gpu_memory_mb()
    info["gpu_total_mb"] = gpu_total
    return info


# ---------------------------------------------------------------------------
# Synthetic grain field
# ---------------------------------------------------------------------------

def grain_radius_for(n_points):
    """Grain radius (BU) conserving total grain volume as N grows.

    Anchored on the spec's np500 reference so the visual density of the
    synthetic pile matches what a real high-N run would produce.
    """
    return REF_GRAIN_RADIUS_VIS * (REF_N / float(n_points)) ** (1.0 / 3.0)


def make_positions(n_points, seed=0, jitter=0.0):
    """Uniform-in-sphere point cloud of radius BODY_RADIUS_VIS, float32 (N, 3).

    ``jitter`` displaces every point by that many BU in a deterministic
    pseudo-random direction, standing in for one frame of DEM motion.
    """
    rng = np.random.default_rng(seed)
    directions = rng.normal(size=(n_points, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    radii = BODY_RADIUS_VIS * rng.random(n_points) ** (1.0 / 3.0)
    pos = (directions * radii[:, None]).astype(np.float32)
    if jitter:
        offsets = rng.normal(size=(n_points, 3)).astype(np.float32)
        offsets /= np.linalg.norm(offsets, axis=1, keepdims=True)
        pos += offsets * np.float32(jitter)
    return np.ascontiguousarray(pos)


# ---------------------------------------------------------------------------
# Scene construction
# ---------------------------------------------------------------------------

def _purge(datablock_collection, name):
    block = datablock_collection.get(name)
    if block is not None:
        datablock_collection.remove(block)


def teardown_scratch_scene():
    """Remove every datablock this spike creates. Safe to call repeatedly."""
    scene = bpy.data.scenes.get(SCRATCH_SCENE_NAME)
    if scene is not None:
        for obj in list(scene.objects):
            scene.collection.objects.unlink(obj)
        # Only remove the scene if it is not the sole scene left.
        if len(bpy.data.scenes) > 1:
            bpy.data.scenes.remove(scene)

    for name in ("P0_PointCloud", "P0_InstanceMesh", "P0_Camera", "P0_Sun"):
        _purge(bpy.data.objects, name)
    for name in ("P0_PointCloudMesh", "P0_IcoMesh"):
        _purge(bpy.data.meshes, name)
    _purge(bpy.data.cameras, "P0_CameraData")
    _purge(bpy.data.lights, "P0_SunData")
    _purge(bpy.data.node_groups, "P0_InstanceOnPoints")
    _purge(bpy.data.materials, "P0_GrainMaterial")


def _make_icosphere(subdiv, radius=1.0):
    """Unit icosphere mesh used as the shared GN instance."""
    import bmesh
    mesh = bpy.data.meshes.new("P0_IcoMesh")
    bm = bmesh.new()
    try:
        # subdivisions=1 is the 20-triangle base icosahedron in Blender's op.
        bmesh.ops.create_icosphere(
            bm, subdivisions=subdiv + 1, radius=radius,
        )
    except TypeError:
        # Older builds spell the radius argument differently.
        bmesh.ops.create_icosphere(
            bm, subdivisions=subdiv + 1, diameter=radius,
        )
    bm.to_mesh(mesh)
    bm.free()
    if hasattr(mesh, "shade_smooth"):
        mesh.shade_smooth()
    return mesh


def _grain_material():
    mat = bpy.data.materials.new("P0_GrainMaterial")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.28, 0.25, 0.22, 1.0)
        for socket_name, value in (("Roughness", 0.85), ("Specular", 0.2),
                                   ("Specular IOR Level", 0.2)):
            if socket_name in bsdf.inputs:
                bsdf.inputs[socket_name].default_value = value
    return mat


def _new_group_socket(group, name, in_out, socket_type):
    """Create a node-group interface socket across Blender 3.x and 4.x."""
    if hasattr(group, "interface"):  # Blender 4.0+
        return group.interface.new_socket(
            name=name, in_out=in_out, socket_type=socket_type
        )
    collection = group.inputs if in_out == "INPUT" else group.outputs
    return collection.new(socket_type, name)


def build_geometry_nodes(point_obj, instance_obj):
    """Instance on Points, scaled by the per-point ``radius`` attribute."""
    group = bpy.data.node_groups.new("P0_InstanceOnPoints", "GeometryNodeTree")
    _new_group_socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _new_group_socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")

    nodes, links = group.nodes, group.links
    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-600, 0)
    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (400, 0)

    n_attr = nodes.new("GeometryNodeInputNamedAttribute")
    n_attr.location = (-600, -220)
    n_attr.data_type = "FLOAT"
    n_attr.inputs["Name"].default_value = RADIUS_ATTR

    n_objinfo = nodes.new("GeometryNodeObjectInfo")
    n_objinfo.location = (-600, -420)
    n_objinfo.inputs["Object"].default_value = instance_obj
    # Local space keeps the instance mesh at unit scale regardless of where the
    # source object sits.
    n_objinfo.transform_space = "RELATIVE"

    n_iop = nodes.new("GeometryNodeInstanceOnPoints")
    n_iop.location = (0, 0)

    links.new(n_in.outputs[0], n_iop.inputs["Points"])
    links.new(n_objinfo.outputs["Geometry"], n_iop.inputs["Instance"])
    # Float -> Vector implicit conversion gives uniform scale.
    links.new(n_attr.outputs["Attribute"], n_iop.inputs["Scale"])
    links.new(n_iop.outputs["Instances"], n_out.inputs[0])

    modifier = point_obj.modifiers.new("P0_GN", "NODES")
    modifier.node_group = group
    return group, modifier


def build_scene(n_points, subdiv, device=None):
    """Create the scratch scene, point cloud, GN instancing, camera and light.

    Returns (scene, point_obj, mesh, previous_scene).
    """
    device = device or RENDER_DEVICE
    teardown_scratch_scene()

    window = bpy.context.window
    previous_scene = window.scene if window else bpy.context.scene
    scene = bpy.data.scenes.new(SCRATCH_SCENE_NAME)
    if window:
        window.scene = scene

    scene.render.engine = "CYCLES"
    scene.render.resolution_x, scene.render.resolution_y = RENDER_RESOLUTION
    scene.render.resolution_percentage = 100
    scene.cycles.samples = RENDER_SAMPLES
    scene.cycles.use_denoising = False
    scene.cycles.device = device

    material = _grain_material()

    # --- shared instance mesh (hidden; only GN references it) ---
    ico_mesh = _make_icosphere(subdiv)
    ico_mesh.materials.append(material)
    instance_obj = bpy.data.objects.new("P0_InstanceMesh", ico_mesh)
    scene.collection.objects.link(instance_obj)
    instance_obj.hide_render = True
    instance_obj.hide_viewport = True

    # --- point cloud ---
    positions = make_positions(n_points, seed=0)
    mesh = bpy.data.meshes.new("P0_PointCloudMesh")
    mesh.vertices.add(n_points)
    mesh.vertices.foreach_set("co", positions.ravel())
    mesh.update()

    attr = mesh.attributes.new(RADIUS_ATTR, "FLOAT", "POINT")
    radii = np.full(n_points, grain_radius_for(n_points), dtype=np.float32)
    attr.data.foreach_set("value", radii)

    point_obj = bpy.data.objects.new("P0_PointCloud", mesh)
    scene.collection.objects.link(point_obj)
    build_geometry_nodes(point_obj, instance_obj)

    # --- camera ---
    cam_data = bpy.data.cameras.new("P0_CameraData")
    cam_data.clip_start = 0.1
    cam_data.clip_end = 10_000.0
    cam_obj = bpy.data.objects.new("P0_Camera", cam_data)
    distance = BODY_RADIUS_VIS * CAMERA_DISTANCE_FACTOR
    cam_obj.location = (distance, -distance, distance * 0.5)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj
    _point_at_origin(cam_obj)

    # --- light ---
    sun_data = bpy.data.lights.new("P0_SunData", type="SUN")
    sun_data.energy = 5.0
    sun_obj = bpy.data.objects.new("P0_Sun", sun_data)
    sun_obj.location = (distance, distance, distance)
    scene.collection.objects.link(sun_obj)
    _point_at_origin(sun_obj)

    with scene_override(scene):
        bpy.context.view_layer.update()
    return scene, point_obj, mesh, previous_scene


def scene_override(scene):
    """Context override making ``scene`` the active scene.

    Required in ``--background``, where ``bpy.context.window`` is None and the
    scratch scene can never become the window's scene: without this, both
    ``view_layer.update()`` and ``render()`` would operate on the startup scene
    and every timing would be meaningless.
    """
    return bpy.context.temp_override(
        scene=scene, view_layer=scene.view_layers[0]
    )


def _point_at_origin(obj):
    from mathutils import Vector
    direction = Vector((0.0, 0.0, 0.0)) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------

def measure_update(mesh, n_points, scene, trials=UPDATE_TRIALS):
    """Time one frame's worth of point motion, the way the real script will.

    Returns (median_update_ms, median_depsgraph_ms). ``update`` covers
    foreach_set on co + radius + mesh.update(); ``depsgraph`` covers the GN
    re-evaluation the moved points force.
    """
    update_times, depsgraph_times = [], []
    radius_attr = mesh.attributes[RADIUS_ATTR]
    base_radius = grain_radius_for(n_points)

    with scene_override(scene):
        for trial in range(trials):
            # Array generation is preprocessing (npz load in the real
            # pipeline), so it is deliberately excluded from the timed section.
            positions = make_positions(n_points, seed=0,
                                       jitter=0.05 * (trial + 1))
            radii = np.full(n_points, base_radius, dtype=np.float32)

            t0 = time.perf_counter()
            mesh.vertices.foreach_set("co", positions.ravel())
            radius_attr.data.foreach_set("value", radii)
            mesh.update()
            t1 = time.perf_counter()
            bpy.context.view_layer.update()
            t2 = time.perf_counter()

            update_times.append((t1 - t0) * 1000.0)
            depsgraph_times.append((t2 - t1) * 1000.0)

    return float(np.median(update_times)), float(np.median(depsgraph_times))


def _viewport_areas():
    areas = []
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                areas.append((window, area))
    return areas


def measure_viewport(shading="SOLID", trials=REDRAW_TRIALS):
    """Median ms per viewport redraw, or None when no 3D viewport exists.

    ``shading`` is one of SOLID / MATERIAL / RENDERED.
    """
    if bpy.app.background:
        return None

    areas = _viewport_areas()
    if not areas:
        return None
    window, area = areas[0]
    space = area.spaces.active
    previous_shading = space.shading.type
    space.shading.type = shading

    try:
        with bpy.context.temp_override(window=window, area=area):
            # Warm-up draw, so shader/BVH build is not charged to the timing.
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            t0 = time.perf_counter()
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=trials)
            elapsed = time.perf_counter() - t0
    except Exception:
        return None
    finally:
        space.shading.type = previous_shading

    return (elapsed / trials) * 1000.0


def measure_render(scene):
    """Render one Cycles frame, sampling GPU memory while it runs.

    Returns a dict of render seconds and the GPU peaks observed during the
    render itself.
    """
    with scene_override(scene), GPUSampler() as sampler:
        t0 = time.perf_counter()
        bpy.ops.render.render(write_still=False)
        seconds = time.perf_counter() - t0

    return {
        "render_s": seconds,
        "gpu_baseline_mb": sampler.baseline_device_mb,
        "gpu_peak_device_mb": sampler.peak_device_mb,
        "gpu_delta_mb": sampler.device_delta_mb,
        "gpu_peak_process_mb": sampler.peak_process_mb,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _results_path(filename):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    return os.path.join(RESULTS_DIR, filename)


def load_results():
    path = _results_path(RESULTS_JSON)
    if not os.path.exists(path):
        return {"environment": None, "settings": {}, "rows": []}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_results(results):
    with open(_results_path(RESULTS_JSON), "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)


def run_one(n_points, subdiv, render=None, device=None):
    """Measure one (N, subdiv, device) configuration and record its row.

    ``render`` overrides the RENDER_MAX_N gate when given.
    """
    device = device or RENDER_DEVICE
    tris_per_instance = 20 * (4 ** subdiv)
    do_render = (n_points <= RENDER_MAX_N) if render is None else bool(render)

    print(f"[P0] N={n_points:,} subdiv={subdiv} device={device} "
          f"({tris_per_instance} tris/instance, "
          f"{tris_per_instance * n_points / 1e6:.1f}M tris total)")

    t_build = time.perf_counter()
    scene, point_obj, mesh, previous_scene = build_scene(
        n_points, subdiv, device=device
    )
    build_s = time.perf_counter() - t_build

    row = {
        "n_points": n_points,
        "subdiv": subdiv,
        "device": device,
        # Read back from the scene rather than echoing the request, so a
        # rejected device shows up as itself in the results.
        "device_effective": scene.cycles.device,
        "tris_per_instance": tris_per_instance,
        "total_tris_millions": tris_per_instance * n_points / 1e6,
        "grain_radius_vis": grain_radius_for(n_points),
        "scene_build_s": build_s,
    }

    try:
        row["update_ms"], row["depsgraph_ms"] = measure_update(
            mesh, n_points, scene
        )
        print(f"      update {row['update_ms']:.1f} ms  "
              f"depsgraph {row['depsgraph_ms']:.1f} ms")

        row["viewport_solid_ms"] = measure_viewport("SOLID")
        row["viewport_material_ms"] = measure_viewport("MATERIAL")
        for key in ("viewport_solid_ms", "viewport_material_ms"):
            if row[key]:
                print(f"      {key}: {row[key]:.1f} ms "
                      f"({1000.0 / row[key]:.1f} FPS)")

        if do_render:
            row.update(measure_render(scene))
            print(f"      cycles render {row['render_s']:.1f} s  "
                  f"gpu +{_fmt(row.get('gpu_delta_mb'), '.0f')} MB "
                  f"(peak device {_fmt(row.get('gpu_peak_device_mb'), '.0f')} MB)")
        else:
            row["render_s"] = None
            print("      cycles render skipped (RENDER_MAX_N)")

        # Sampled while the scene is still built, before teardown frees it.
        row["ram_mb"], row["peak_ram_mb"] = process_memory_mb()
        print(f"      RAM {_fmt(row.get('ram_mb'), '.0f')} MB "
              f"(process peak {_fmt(row.get('peak_ram_mb'), '.0f')} MB)")
    finally:
        window = bpy.context.window
        if window and previous_scene is not None:
            window.scene = previous_scene
        teardown_scratch_scene()

    results = load_results()
    if results.get("environment") is None:
        results["environment"] = environment_info()
    results["settings"] = {
        "render_samples": RENDER_SAMPLES,
        "render_resolution": list(RENDER_RESOLUTION),
        "update_trials": UPDATE_TRIALS,
        "redraw_trials": REDRAW_TRIALS,
        "body_radius_vis": BODY_RADIUS_VIS,
        "camera_distance_factor": CAMERA_DISTANCE_FACTOR,
    }
    _upsert_row(results, row)
    save_results(results)
    return row


def _upsert_row(results, row):
    """Replace any previous measurement of the same (N, subdiv, device)."""
    key = (row["n_points"], row["subdiv"], row.get("device"))
    results["rows"] = [
        r for r in results["rows"]
        if (r["n_points"], r["subdiv"], r.get("device")) != key
    ]
    results["rows"].append(row)
    results["rows"].sort(
        key=lambda r: (r["n_points"], r["subdiv"], str(r.get("device")))
    )


def _fmt(value, spec=".1f", missing="-"):
    return missing if value is None else format(value, spec)


def write_report():
    """Render the accumulated results as the markdown table the spec asks for."""
    results = load_results()
    rows, env = results["rows"], results.get("environment") or {}
    settings = results.get("settings", {})

    lines = [
        "# P0 — GN instancing performance spike (Option A)",
        "",
        "Measured by `BlenderConvert/P0_InstancingSpike.py`. Synthetic points, "
        "**Cycles**, project hardware.",
        "",
        "## Environment",
        "",
        f"- Blender: {env.get('blender_version', '?')}",
        f"- Platform: {env.get('platform', '?')}",
        f"- Cycles compute device type: "
        f"{env.get('cycles_compute_device_type', '?')} "
        f"(startup scene was set to {env.get('startup_scene_device', '?')}; "
        f"the spike sets its own per row — see the `device` column)",
    ]
    for device in (env.get("cycles_devices") or []):
        mark = "x" if device["enabled"] else " "
        lines.append(f"  - [{mark}] {device['name']} ({device['type']})")
    gpu_total = env.get("gpu_total_mb")
    if gpu_total:
        lines.append(f"- GPU memory total: {gpu_total:.0f} MB")
    lines += [
        f"- Render settings: {settings.get('render_resolution', '?')} @ "
        f"{settings.get('render_samples', '?')} samples, denoising off",
        f"- Body: {settings.get('body_radius_vis', '?')} BU radius, camera at "
        f"{settings.get('camera_distance_factor', '?')}x that distance",
        "",
        "## Results",
        "",
        "| N | subdiv | device | tris/inst | total tris | grain r (BU) | "
        "update ms | depsgraph ms | viewport solid | viewport material | "
        "Cycles s/frame | RAM MB | GPU peak MB | GPU delta MB |",
        "|---|--------|--------|-----------|------------|--------------|"
        "-----------|--------------|----------------|-------------------|"
        "----------------|--------|-------------|--------------|",
    ]

    for row in rows:
        def fps(key):
            value = row.get(key)
            if not value:
                return "-"
            return f"{value:.0f} ms ({1000.0 / value:.1f} fps)"

        lines.append(
            f"| {row['n_points']:,} | {row['subdiv']} | "
            f"{row.get('device_effective') or row.get('device') or '?'} | "
            f"{row['tris_per_instance']} | "
            f"{row['total_tris_millions']:.1f}M | "
            f"{row['grain_radius_vis']:.3f} | "
            f"{_fmt(row.get('update_ms'))} | "
            f"{_fmt(row.get('depsgraph_ms'))} | "
            f"{fps('viewport_solid_ms')} | "
            f"{fps('viewport_material_ms')} | "
            f"{_fmt(row.get('render_s'), '.1f')} | "
            f"{_fmt(row.get('ram_mb'), '.0f')} | "
            f"{_fmt(row.get('gpu_peak_device_mb'), '.0f')} | "
            f"{_fmt(row.get('gpu_delta_mb'), '.0f')} |"
        )

    renders_dir = os.path.join(RESULTS_DIR, RENDERS_SUBDIR)
    if os.path.isdir(renders_dir):
        pngs = sorted(f for f in os.listdir(renders_dir) if f.endswith(".png"))
        if pngs:
            lines += ["", "## Reference renders", ""]
            for png in pngs:
                label = os.path.splitext(png)[0].replace("_", " ")
                lines.append(f"### {label}")
                lines.append("")
                lines.append(f"![{label}]({RENDERS_SUBDIR}/{png})")
                lines.append("")

    failures = [r for r in rows if r.get("failed")]
    if failures:
        lines += ["", "## Ceilings hit", ""]
        for row in failures:
            lines.append(
                f"- **N={row['n_points']:,}, subdiv={row['subdiv']}, "
                f"device={row.get('device', '?')}** "
                f"({row['total_tris_millions']:.1f}M tris): "
                f"`{row.get('error', 'unknown error')}`"
            )

    lines += [
        "",
        "## Notes",
        "",
        "- `update ms` is `foreach_set('co')` + radius `foreach_set` + "
        "`mesh.update()` — the per-frame Python cost the spec flags as often "
        "underestimated. npz load time is excluded (it is preprocessing).",
        "- `depsgraph ms` is the GN re-evaluation the moved points force; the "
        "practical scrub cost is roughly update + depsgraph + viewport redraw.",
        "- Viewport columns are `-` when run headless or with no 3D viewport; "
        "they require a GUI session.",
        "- `RAM MB` is the Blender process working set sampled while the "
        "configuration's scene is still built, before teardown. **A working "
        "set does not fully return after teardown**, so rows measured later "
        "in a session inherit earlier allocations: compare within one device "
        "pass, and read cross-pass values as upper bounds rather than as that "
        "configuration's true cost.",
        "- `GPU peak` / `GPU delta` are sampled on a background thread **during** "
        "the Cycles render (peak device usage, and its rise above the "
        "pre-render baseline). Device totals include other applications; "
        "per-process VRAM is usually unavailable on consumer GPUs in WDDM mode.",
    ]

    path = _results_path(RESULTS_MD)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"[P0] report written: {path}")
    return path


def _record_failure(n_points, subdiv, device, error):
    """Persist a failed configuration — hitting a ceiling is a P0 result."""
    results = load_results()
    if results.get("environment") is None:
        results["environment"] = environment_info()
    _upsert_row(results, {
        "n_points": n_points,
        "subdiv": subdiv,
        "device": device,
        "tris_per_instance": 20 * (4 ** subdiv),
        "total_tris_millions": 20 * (4 ** subdiv) * n_points / 1e6,
        "grain_radius_vis": grain_radius_for(n_points),
        "failed": True,
        "error": f"{type(error).__name__}: {error}",
    })
    save_results(results)


def run_all(configs=None, devices=None):
    """Run every configuration on every device, recording ceilings.

    A configuration that exhausts RAM/VRAM is exactly the go/no-go signal the
    spike exists to find, so its failure is written to the results and the
    sweep continues with the remaining configurations.
    """
    for device in (devices or RENDER_DEVICES):
        for n_points, subdiv in (configs or CONFIGS):
            try:
                run_one(n_points, subdiv, device=device)
            except Exception as error:  # noqa: BLE001 - a ceiling is a result
                print(f"[P0] FAILED N={n_points:,} subdiv={subdiv} "
                      f"device={device}: {type(error).__name__}: {error}")
                _record_failure(n_points, subdiv, device, error)
                try:
                    teardown_scratch_scene()
                except Exception:
                    pass
    return write_report()


if __name__ == "__main__":
    run_all()
