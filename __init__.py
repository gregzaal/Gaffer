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

bl_info = {
    "name": "Gaffer",
    "description": "Manage all your lights together quickly and efficiently from the 3D View toolbar",
    "author": "Greg Zaal",
    "version": (2, 5),
    "blender": (2, 77, 0),
    "location": "3D View > Tools",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "3D View"}

if "bpy" in locals():
    import imp
    imp.reload(constants)
    imp.reload(functions)
    imp.reload(operators)
    imp.reload(ui)
else:
    from . import constants, functions, operators, ui

import bpy
from collections import OrderedDict
import bgl, blf
from math import pi, cos, sin, log
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.app.handlers import persistent


def do_set_world_refl_only(context):
    scene = context.scene
    if scene.gaf_props.WorldReflOnly and not scene.gaf_props.WorldVis:
        scene.gaf_props.WorldVis = True
        scene.gaf_props.WorldReflOnly = True
    if scene.gaf_props.WorldVis:
        world = scene.world
        world.cycles_visibility.glossy = True
        world.cycles_visibility.camera = not scene.gaf_props.WorldReflOnly
        world.cycles_visibility.diffuse = not scene.gaf_props.WorldReflOnly
        world.cycles_visibility.transmission = not scene.gaf_props.WorldReflOnly
        world.cycles_visibility.scatter = not scene.gaf_props.WorldReflOnly
        world.update_tag()


def _update_world_refl_only(self, context):
    do_set_world_refl_only(context)


def do_set_world_vis(context):
    scene = context.scene
    if scene.gaf_props.WorldVis:
        scene.gaf_props.WorldReflOnly = False
    elif scene.gaf_props.WorldReflOnly:
        scene.gaf_props.WorldReflOnly = False
    world = scene.world
    world.cycles_visibility.glossy = scene.gaf_props.WorldVis
    world.cycles_visibility.camera = scene.gaf_props.WorldVis
    world.cycles_visibility.diffuse = scene.gaf_props.WorldVis
    world.cycles_visibility.transmission = scene.gaf_props.WorldVis
    world.cycles_visibility.scatter = scene.gaf_props.WorldVis
    world.update_tag()


def _update_world_vis(self, context):
    do_set_world_vis(context)


class BlacklistedObject(bpy.types.PropertyGroup):
    name = bpy.props.StringProperty(default = "")


class GafferProperties(bpy.types.PropertyGroup):
    Lights = bpy.props.StringProperty(
        name = "Lights",
        default = "",
        description = "The objects to include in the isolation")
    ColTempExpand = bpy.props.BoolProperty(
        name = "Color Temperature Presets",
        default = False,
        description = "Preset color temperatures based on real-world light sources")
    MoreExpand = bpy.props.StringProperty(
        name = "Show more options",
        default = "",
        description = "Show settings such as MIS, falloff, ray visibility...")
    MoreExpandAll = bpy.props.BoolProperty(
        name = "Show more options",
        default = False,
        description = "Show settings such as MIS, falloff, ray visibility...")
    LightUIIndex = bpy.props.IntProperty(
        name = "light index",
        default = 0,
        min = 0,
        description = "light index")
    LightsHiddenRecord = bpy.props.StringProperty(
        name = "hidden record",
        default = "",
        description = "hidden record")
    SoloActive = bpy.props.StringProperty(
        name = "soloactive",
        default = '',
        description = "soloactive")
    VisibleLayersOnly = bpy.props.BoolProperty(
        name = "Visible Layers Only",
        default = True,
        description = "Only show lamps that are on visible layers")
    VisibleLightsOnly = bpy.props.BoolProperty(
        name = "Visible Lights Only",
        default = False,
        description = "Only show lamps that are not hidden")
    WorldVis = bpy.props.BoolProperty(
        name = "Hide World lighting",
        default = True,
        description = "Don't display (or render) the environment lighting",
        update = _update_world_vis)
    WorldReflOnly = bpy.props.BoolProperty(
        name = "Reflection Only",
        default = False,
        description = "Only show the World lighting in reflections",
        update = _update_world_refl_only)
    LightRadiusAlpha = bpy.props.FloatProperty(
        name = "Alpha",
        default = 0.6,
        min = 0,
        max = 1,
        description = "The opacity of the overlaid circles")
    LightRadiusUseColor = bpy.props.BoolProperty(
        name = "Use Color",
        default = True,
        description = "Draw the radius of each light in the same color as the light")
    LabelUseColor = bpy.props.BoolProperty(
        name = "Use Color",
        default = True,
        description = "Draw the label of each light in the same color as the light")
    LightRadiusSelectedOnly = bpy.props.BoolProperty(
        name = "Selected Only",
        default = False,
        description = "Draw the radius for every visible light, or only selected lights")
    LightRadiusXray = bpy.props.BoolProperty(
        name = "X-Ray",
        default = False,
        description = "Draw the circle in front of all objects")
    LightRadiusDrawType = bpy.props.EnumProperty(
        name="Draw Type",
        description="How should the radius display look?",
        default='solid',
        items=(("filled","Filled","Draw a circle filled with a solid color"),
               ("solid","Solid","Draw a solid outline of the circle"),
               ("dotted","Dotted","Draw a dotted outline of the circle")))
    DefaultRadiusColor = bpy.props.FloatVectorProperty(
        name="Default Color",
        description="When 'Use Color' is disaled, or when the color of a light is unknown (such as when using a texture), this color is used instead",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(1.0,1.0,1.0))
    DefaultLabelBGColor = bpy.props.FloatVectorProperty(
        name="Background Color",
        description="When 'Use Color' is disaled, or when the color of a light is unknown (such as when using a texture), this color is used instead",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(0.0,0.0,0.0))
    LabelAlpha = bpy.props.FloatProperty(
        name = "Alpha",
        default = 0.5,
        min = 0,
        max = 1,
        description = "The opacity of the drawn labels")
    LabelFontSize = bpy.props.IntProperty(
        name = "Font Size",
        default = 14,
        min = 1,
        description = "How large the text is drawn")
    LabelDrawType = bpy.props.EnumProperty(
        name="Draw Type",
        description="How should the label look?",
        default='color_bg',
        items=(("color_bg","Colored background, plain text","Show the label name on a colored background"),
               ("plain_bg","Colored text in plain background","Show the label name in color, on a plain background"),
               ("color_text","Text only, no background","Show the text without any background")))
    LabelTextColor = bpy.props.FloatVectorProperty(
        name="Text Color",
        description="The color of the label name text",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(1.0,1.0,1.0))
    LabelAlign = bpy.props.EnumProperty(
        name="Alignment",
        description="The positioning of the label relative to the lamp",
        default='r',
        items=(("c","Centered","Positioned exactly on the light"),
               ("t","Top","Positioned above the light"),
               ("b","Bottom","Positioned below the light"),
               ("l","Left","Positioned to the left of the light"),
               ("r","Right","Positioned to the right of the light"),
               ("bl","Bottom Left","Positioned below and to the left of the light"),
               ("tl","Top Left","Positioned above and to the left of the light"),
               ("tr","Top Right","Positioned below and to the right of the light"),
               ("br","Bottom Right","Positioned above and to the right of the light")))
    LabelMargin = bpy.props.IntProperty(
        name = "Margin",
        default = 90,
        description = "Draw the label this distance away from the light")
    SunObject = bpy.props.StringProperty(
        name="Sun Obj",
        default="",
        description="The lamp object to use to drive the Sky rotation")

    # Internal vars (not shown in UI)
    IsShowingRadius = bpy.props.BoolProperty(default = False, options={'HIDDEN'})
    IsShowingLabel = bpy.props.BoolProperty(default = False, options={'HIDDEN'})
    BlacklistIndex = bpy.props.IntProperty(default = 0, options={'HIDDEN'})
    VarNameCounter = bpy.props.IntProperty(default = 0, options={'HIDDEN'})
    Blacklist = bpy.props.CollectionProperty(type=BlacklistedObject)  # must be registered after classes

def register():
    bpy.types.NODE_PT_active_node_generic.append(ui.gaffer_node_menu_func)
    bpy.utils.register_module(__name__)
    bpy.types.Scene.gaf_props = bpy.props.PointerProperty(type=GafferProperties)
    bpy.app.handlers.load_post.append(operators.load_handler)

def unregister():
    bpy.app.handlers.load_post.remove(operators.load_handler)

    if operators.GafShowLightRadius._handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(operators.GafShowLightRadius._handle, 'WINDOW')
        bpy.context.scene.gaf_props.IsShowingRadius = False
    if operators.GafShowLightLabel._handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(operators.GafShowLightLabel._handle, 'WINDOW')
        bpy.context.scene.gaf_props.IsShowingLabel = False

    del bpy.types.Scene.gaf_props

    bpy.types.NODE_PT_active_node_generic.remove(ui.gaffer_node_menu_func)

    bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
    register()
