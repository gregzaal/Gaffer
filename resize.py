# BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# END GPL LICENSE BLOCK #####

# Args:
# img input path
# size X
# img output path

# example usage:
# blender --background --factory-startup --python resize.py -- "C:\big image.hdr" 200 "C:\small image.jpg"

import bpy
import sys
from math import floor

argv = sys.argv
argv = argv[argv.index("--") + 1 :]  # Get all args after  '--'
FILEPATH, SIZE_X, OUTPATH = argv
SIZE_X = int(SIZE_X)

context = bpy.context
scene = context.scene

if hasattr(scene, "use_nodes"):  # Deprecated in Blender 5.0
    scene.use_nodes = True

if hasattr(scene, "compositing_node_group"):
    node_tree = scene.compositing_node_group
    if not node_tree:
        # We need to create it first
        node_tree = bpy.data.node_groups.new(name="COMP", type="CompositorNodeTree")
        scene.compositing_node_group = node_tree
else:
    # Pre Blender 5.0
    node_tree = scene.node_tree

n_comp = None
if bpy.app.version < (5, 0, 0):
    # Remove default nodes, except composite
    for n in node_tree.nodes:
        if not n.type == "COMPOSITE":
            node_tree.nodes.remove(n)
        else:
            n_comp = n
else:
    # In Blender 5, there are no default nodes, so we need to make the group output node.
    n_comp = node_tree.nodes.new("NodeGroupOutput")
    node_tree.interface.new_socket(name="Output", in_out="OUTPUT", socket_type="NodeSocketColor")

img = bpy.data.images.load(FILEPATH)
n_img = node_tree.nodes.new("CompositorNodeImage")
n_img.image = img

n_blur = node_tree.nodes.new("CompositorNodeBlur")
if bpy.app.version < (5, 0, 0):
    n_blur.filter_type = "FLAT"
    n_blur.size_x = floor(img.size[0] / SIZE_X / 2)
    n_blur.size_y = n_blur.size_x

n_scale = node_tree.nodes.new("CompositorNodeScale")
if bpy.app.version < (5, 0, 0):
    n_scale.space = "RENDER_SIZE"
    n_scale.frame_method = "CROP"
else:
    n_scale.inputs["Type"].default_value = "Render Size"
    n_scale.inputs["Frame Type"].default_value = "Crop"

# Links
links = node_tree.links
links.new(n_img.outputs[0], n_blur.inputs[0])
links.new(n_blur.outputs[0], n_scale.inputs[0])
links.new(n_scale.outputs[0], n_comp.inputs[0])

# Render
r = scene.render
r.image_settings.file_format = "JPEG"
r.image_settings.quality = 95
r.resolution_x = SIZE_X
SIZE_Y = floor(SIZE_X / (img.size[0] / img.size[1]))
r.resolution_y = SIZE_Y
r.resolution_percentage = 100
r.filepath = OUTPATH

bpy.ops.render.render(write_still=True)
