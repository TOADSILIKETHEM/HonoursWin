import bpy
from mathutils import Vector

earth = bpy.data.objects.get("Earth")
if earth:
    cam_data = bpy.data.cameras.new("EarthCam")
    cam = bpy.data.objects.new("EarthCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)

    # Derive Earth radius from object bounds (BU) for scale-independent camera distance.
    earth_radius_bu = max(earth.dimensions) * 0.5
    if earth_radius_bu <= 0:
        earth_radius_bu = 0.1
        print("Warning: Earth dimensions invalid; using fallback radius 0.1 BU.")

    # k is camera center-distance in radii; altitude above surface is (k - 1) * radius.
    k = 4
    direction = Vector((1.0, -1.0, 0.6)).normalized()
    cam.parent = earth
    cam.location = direction * (earth_radius_bu * k)

    # Constraint order matters (top-to-bottom): move first, then aim with fixed up axis.
    track = cam.constraints.new(type='TRACK_TO')
    track.target = earth
    track.track_axis = 'TRACK_NEGATIVE_Z'
    track.up_axis = 'UP_Y'

    actual_center_distance = (cam.matrix_world.translation - earth.matrix_world.translation).length
    print("earth_radius_bu:", earth_radius_bu)
    print("target_center_distance:", earth_radius_bu * k)
    print("actual_center_distance:", actual_center_distance)

    bpy.context.scene.camera = cam