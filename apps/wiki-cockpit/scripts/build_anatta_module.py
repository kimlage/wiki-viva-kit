"""Build the first-party Hydrology House shell used by the Anatta beauty slice."""

from pathlib import Path

import bpy
import math


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "public/assets/anatta-beauty/hydrology-house.glb"


def material(name: str, color: tuple[float, float, float, float], roughness: float):
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    principled = value.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Roughness"].default_value = roughness
    return value


def box(
    name: str,
    location: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    surface,
    rotation: tuple[float, float, float] = (0, 0, 0),
    bevel: float = 0.045,
):
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        modifier = obj.modifiers.new(name="EdgeSoftening", type="BEVEL")
        modifier.width = bevel
        modifier.segments = 2
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.data.materials.append(surface)
    return obj


bpy.ops.wm.read_factory_settings(use_empty=True)

stone = material("StoneShell", (0.31, 0.32, 0.29, 1), 0.92)
wood = material("TimberFrame", (0.22, 0.14, 0.085, 1), 0.84)
roof = material("WeatheredRoof", (0.18, 0.13, 0.105, 1), 0.9)
metal = material("DarkMetal", (0.045, 0.055, 0.052, 1), 0.68)

box("stone_plinth", (0, 0, 0.08), (4.7, 4.0, 0.38), stone, bevel=0.08)
box("left_wall", (-2.08, 0.15, 1.5), (0.3, 3.62, 2.95), stone, bevel=0.075)
box("right_wall", (2.08, 0.15, 1.5), (0.3, 3.62, 2.95), stone, bevel=0.075)
box("rear_sill", (0, 1.72, 0.52), (4.18, 0.24, 0.72), stone, bevel=0.055)
box("rear_header", (0, 1.72, 2.65), (4.18, 0.24, 0.34), wood)
box("rear_post_l", (-1.83, 1.72, 1.55), (0.25, 0.24, 2.55), wood)
box("rear_post_r", (1.83, 1.72, 1.55), (0.25, 0.24, 2.55), wood)

for x in (-1.8, 1.8):
    box(f"front_post_{x}", (x, -1.76, 1.5), (0.22, 0.22, 3.1), wood)
box("front_header", (0, -1.76, 2.72), (4.18, 0.22, 0.25), wood)

roof_angle = math.radians(27)
box(
    "roof_left",
    (-1.08, 0, 3.12),
    (2.85, 4.45, 0.18),
    roof,
    rotation=(0, roof_angle, 0),
    bevel=0.055,
)
box(
    "roof_right",
    (1.08, 0, 3.12),
    (2.85, 4.45, 0.18),
    roof,
    rotation=(0, -roof_angle, 0),
    bevel=0.055,
)
box("roof_ridge", (0, 0, 3.74), (0.16, 4.58, 0.16), metal, bevel=0.035)

box("entry_deck", (0, -2.68, 0.26), (4.05, 1.65, 0.22), wood, bevel=0.055)
for index in range(10):
    x = -1.78 + index * 0.395
    box(f"deck_plank_{index:02d}", (x, -2.7, 0.4), (0.34, 1.62, 0.065), wood, bevel=0.012)

for x in (-1.78, 1.78):
    box(f"deck_rail_top_{x}", (x, -2.72, 1.13), (0.09, 1.58, 0.09), metal, bevel=0.02)
    for y in (-3.36, -2.75, -2.14):
        box(f"deck_rail_post_{x}_{y}", (x, y, 0.77), (0.09, 0.09, 0.76), metal, bevel=0.018)

for index in range(3):
    box(
        f"entry_step_{index}",
        (0, -3.58 - index * 0.34, 0.17 - index * 0.075),
        (3.38 - index * 0.22, 0.46, 0.16),
        wood,
        bevel=0.035,
    )

for x in (-1.62, 1.62):
    for y in (-1.1, 1.08):
        box(f"foundation_{x}_{y}", (x, y, -0.68), (0.28, 0.28, 1.55), wood, bevel=0.035)

box("interior_table", (0, 0.62, 0.78), (2.35, 1.2, 0.18), wood, bevel=0.065)
for x in (-0.94, 0.94):
    for y in (0.18, 1.02):
        box(f"table_leg_{x}_{y}", (x, y, 0.42), (0.13, 0.13, 0.7), metal, bevel=0.025)

bpy.ops.export_scene.gltf(
    filepath=str(OUTPUT),
    export_format="GLB",
    export_apply=True,
    export_yup=True,
    export_materials="EXPORT",
    export_texcoords=True,
    export_normals=True,
)
