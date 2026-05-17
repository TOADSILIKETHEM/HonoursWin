import bpy

# --- Settings -----------------------------------------------------------------
CLIP_START = 1e-7   # BU
CLIP_END   = 1000.0 # BU

APOPHIS_VIEW_DISTANCE = 5e-4  # ~10x Apophis diameter
# -------------------------------------------------------------------------------

def setup_viewports():
    for area in bpy.context.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for space in area.spaces:
            if space.type != 'VIEW_3D':
                continue
            space.clip_start = CLIP_START
            space.clip_end   = CLIP_END

            apophis = bpy.data.objects.get('Apophis')
            if apophis:
                r3d = space.region_3d
                r3d.view_location = apophis.location.copy()
                r3d.view_distance = APOPHIS_VIEW_DISTANCE

    bpy.context.preferences.inputs.use_zoom_to_mouse       = True
    bpy.context.preferences.inputs.use_mouse_depth_navigate = True  # renamed in Blender 5.x

    print(
        f'Viewports updated:\n'
        f'  clip_start             = {CLIP_START}\n'
        f'  clip_end               = {CLIP_END}\n'
        f'  view_distance          = {APOPHIS_VIEW_DISTANCE}\n'
        f'  zoom_to_mouse          = True\n'
        f'  mouse_depth_navigate   = True'
    )

setup_viewports()