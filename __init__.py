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
    if scene.GafferWorldReflOnly and not scene.GafferWorldVis:
        scene.GafferWorldVis = True
        scene.GafferWorldReflOnly = True
    if scene.GafferWorldVis:
        world = scene.world
        world.cycles_visibility.glossy = True
        world.cycles_visibility.camera = not scene.GafferWorldReflOnly
        world.cycles_visibility.diffuse = not scene.GafferWorldReflOnly
        world.cycles_visibility.transmission = not scene.GafferWorldReflOnly
        world.cycles_visibility.scatter = not scene.GafferWorldReflOnly
        world.update_tag()


def _update_world_refl_only(self, context):
    do_set_world_refl_only(context)


def do_set_world_vis(context):
    scene = context.scene
    if scene.GafferWorldVis:
        scene.GafferWorldReflOnly = False
    elif scene.GafferWorldReflOnly:
        scene.GafferWorldReflOnly = False
    world = scene.world
    world.cycles_visibility.glossy = scene.GafferWorldVis
    world.cycles_visibility.camera = scene.GafferWorldVis
    world.cycles_visibility.diffuse = scene.GafferWorldVis
    world.cycles_visibility.transmission = scene.GafferWorldVis
    world.cycles_visibility.scatter = scene.GafferWorldVis
    world.update_tag()


def _update_world_vis(self, context):
    do_set_world_vis(context)


class BlacklistedObject(bpy.types.PropertyGroup):
    name = bpy.props.StringProperty(default = "")


def register():
    bpy.types.Scene.GafferLights = bpy.props.StringProperty(
        name = "Lights",
        default = "",
        description = "The objects to include in the isolation")
    bpy.types.Scene.GafferColTempExpand = bpy.props.BoolProperty(
        name = "Color Temperature Presets",
        default = False,
        description = "Preset color temperatures based on real-world light sources")
    bpy.types.Scene.GafferMoreExpand = bpy.props.StringProperty(
        name = "Show more options",
        default = "",
        description = "Show settings such as MIS, falloff, ray visibility...")
    bpy.types.Scene.GafferMoreExpandAll = bpy.props.BoolProperty(
        name = "Show more options",
        default = False,
        description = "Show settings such as MIS, falloff, ray visibility...")
    bpy.types.Scene.GafferLightUIIndex = bpy.props.IntProperty(
        name = "light index",
        default = 0,
        min = 0,
        description = "light index")
    bpy.types.Scene.GafferLightsHiddenRecord = bpy.props.StringProperty(
        name = "hidden record",
        default = "",
        description = "hidden record")
    bpy.types.Scene.GafferSoloActive = bpy.props.StringProperty(
        name = "soloactive",
        default = '',
        description = "soloactive")
    bpy.types.Scene.GafferVisibleLayersOnly = bpy.props.BoolProperty(
        name = "Visible Layers Only",
        default = True,
        description = "Only show lamps that are on visible layers")
    bpy.types.Scene.GafferVisibleLightsOnly = bpy.props.BoolProperty(
        name = "Visible Lights Only",
        default = False,
        description = "Only show lamps that are not hidden")
    bpy.types.Scene.GafferWorldVis = bpy.props.BoolProperty(
        name = "Hide World lighting",
        default = True,
        description = "Don't display (or render) the environment lighting",
        update = _update_world_vis)
    bpy.types.Scene.GafferWorldReflOnly = bpy.props.BoolProperty(
        name = "Reflection Only",
        default = False,
        description = "Only show the World lighting in reflections",
        update = _update_world_refl_only)
    bpy.types.Scene.GafferLightRadiusAlpha = bpy.props.FloatProperty(
        name = "Alpha",
        default = 0.6,
        min = 0,
        max = 1,
        description = "The opacity of the overlaid circles")
    bpy.types.Scene.GafferLightRadiusUseColor = bpy.props.BoolProperty(
        name = "Use Color",
        default = True,
        description = "Draw the radius of each light in the same color as the light")
    bpy.types.Scene.GafferLabelUseColor = bpy.props.BoolProperty(
        name = "Use Color",
        default = True,
        description = "Draw the label of each light in the same color as the light")
    bpy.types.Scene.GafferLightRadiusSelectedOnly = bpy.props.BoolProperty(
        name = "Selected Only",
        default = False,
        description = "Draw the radius for every visible light, or only selected lights")
    bpy.types.Scene.GafferLightRadiusXray = bpy.props.BoolProperty(
        name = "X-Ray",
        default = False,
        description = "Draw the circle in front of all objects")
    bpy.types.Scene.GafferLightRadiusDrawType = bpy.props.EnumProperty(
        name="Draw Type",
        description="How should the radius display look?",
        default='solid',
        items=(("filled","Filled","Draw a circle filled with a solid color"),
               ("solid","Solid","Draw a solid outline of the circle"),
               ("dotted","Dotted","Draw a dotted outline of the circle")))
    bpy.types.Scene.GafferDefaultRadiusColor = bpy.props.FloatVectorProperty(
        name="Default Color",
        description="When 'Use Color' is disaled, or when the color of a light is unknown (such as when using a texture), this color is used instead",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(1.0,1.0,1.0))
    bpy.types.Scene.GafferDefaultLabelBGColor = bpy.props.FloatVectorProperty(
        name="Background Color",
        description="When 'Use Color' is disaled, or when the color of a light is unknown (such as when using a texture), this color is used instead",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(0.0,0.0,0.0))
    bpy.types.Scene.GafferLabelAlpha = bpy.props.FloatProperty(
        name = "Alpha",
        default = 0.5,
        min = 0,
        max = 1,
        description = "The opacity of the drawn labels")
    bpy.types.Scene.GafferLabelFontSize = bpy.props.IntProperty(
        name = "Font Size",
        default = 14,
        min = 1,
        description = "How large the text is drawn")
    bpy.types.Scene.GafferLabelDrawType = bpy.props.EnumProperty(
        name="Draw Type",
        description="How should the label look?",
        default='color_bg',
        items=(("color_bg","Colored background, plain text","Show the label name on a colored background"),
               ("plain_bg","Colored text in plain background","Show the label name in color, on a plain background"),
               ("color_text","Text only, no background","Show the text without any background")))
    bpy.types.Scene.GafferLabelTextColor = bpy.props.FloatVectorProperty(
        name="Text Color",
        description="The color of the label name text",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(1.0,1.0,1.0))
    bpy.types.Scene.GafferLabelAlign = bpy.props.EnumProperty(
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
    bpy.types.Scene.GafferLabelMargin = bpy.props.IntProperty(
        name = "Margin",
        default = 90,
        description = "Draw the label this distance away from the light")
    bpy.types.Scene.GafferSunObject = bpy.props.StringProperty(
        name="Sun Obj",
        default="",
        description="The lamp object to use to drive the Sky rotation")

    # Internal vars (not shown in UI)
    bpy.types.Scene.GafferIsShowingRadius = bpy.props.BoolProperty(default = False)
    bpy.types.Scene.GafferIsShowingLabel = bpy.props.BoolProperty(default = False)
    bpy.types.Scene.GafferBlacklistIndex = bpy.props.IntProperty(default = 0)
    bpy.types.Scene.GafferVarNameCounter = bpy.props.IntProperty(default = 0)

    bpy.types.NODE_PT_active_node_generic.append(ui.gaffer_node_menu_func)

    bpy.utils.register_module(__name__)

    bpy.types.Scene.GafferBlacklist = bpy.props.CollectionProperty(type=BlacklistedObject)  # must be registered after classes

    bpy.app.handlers.load_post.append(operators.load_handler)

def unregister():
    bpy.app.handlers.load_post.remove(operators.load_handler)

    if GafShowLightRadius._handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(GafShowLightRadius._handle, 'WINDOW')
        bpy.context.scene.GafferIsShowingRadius = False
    if GafShowLightLabel._handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(GafShowLightLabel._handle, 'WINDOW')
        bpy.context.scene.GafferIsShowingLabel = False

    del bpy.types.Scene.GafferLights
    del bpy.types.Scene.GafferColTempExpand
    del bpy.types.Scene.GafferMoreExpand
    del bpy.types.Scene.GafferLightUIIndex
    del bpy.types.Scene.GafferLightsHiddenRecord
    del bpy.types.Scene.GafferSoloActive
    del bpy.types.Scene.GafferVisibleLayersOnly
    del bpy.types.Scene.GafferVisibleLightsOnly
    del bpy.types.Scene.GafferWorldVis
    del bpy.types.Scene.GafferWorldReflOnly
    del bpy.types.Scene.GafferLightRadiusAlpha
    del bpy.types.Scene.GafferLightRadiusUseColor
    del bpy.types.Scene.GafferLabelUseColor
    del bpy.types.Scene.GafferLightRadiusSelectedOnly
    del bpy.types.Scene.GafferLightRadiusXray
    del bpy.types.Scene.GafferLightRadiusDrawType
    del bpy.types.Scene.GafferDefaultRadiusColor
    del bpy.types.Scene.GafferDefaultLabelBGColor
    del bpy.types.Scene.GafferLabelAlpha
    del bpy.types.Scene.GafferLabelFontSize
    del bpy.types.Scene.GafferLabelDrawType
    del bpy.types.Scene.GafferLabelTextColor
    del bpy.types.Scene.GafferLabelAlign
    del bpy.types.Scene.GafferLabelMargin
    del bpy.types.Scene.GafferSunObject

    del bpy.types.Scene.GafferIsShowingRadius
    del bpy.types.Scene.GafferIsShowingLabel
    del bpy.types.Scene.GafferBlacklistIndex
    del bpy.types.Scene.GafferVarNameCounter
    del bpy.types.Scene.GafferBlacklist

    bpy.types.NODE_PT_active_node_generic.remove(ui.gaffer_node_menu_func)

    bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
    register()
