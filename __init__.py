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
    "description": "Master your lighting workflow with easy access to lamp properties and other tools",
    "author": "Greg Zaal",
    "version": (3, 0, 5),
    "blender": (2, 79, 5),
    "location": "3D View > Tools  &  World Settings > HDRI",
    "warning": "",
    "wiki_url": "https://github.com/gregzaal/Gaffer/wiki",
    "tracker_url": "https://github.com/gregzaal/Gaffer/issues",
    "category": "Lighting"}

if "bpy" in locals():
    import imp
    imp.reload(constants)
    imp.reload(functions)
    imp.reload(operators)
    imp.reload(ui)
    imp.reload(addon_updater)
    imp.reload(addon_updater_ops)
else:
    from . import constants, functions, operators, ui, addon_updater, addon_updater_ops

import bpy
import os
import json
import bgl, blf
from . import addon_updater_ops
from collections import OrderedDict
from math import pi, cos, sin, log
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.app.handlers import persistent


class GafferPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    # addon updater preferences
    auto_check_update = bpy.props.BoolProperty(
        name = "Auto-check for Update",
        description = "If enabled, auto-check for updates using an interval",
        default = True,
        )
    updater_intrval_months = bpy.props.IntProperty(
        name='Months',
        description = "Number of months between checking for updates",
        default=0,
        min=0
        )
    updater_intrval_days = bpy.props.IntProperty(
        name='Days',
        description = "Number of days between checking for updates",
        default=1,
        min=0,
        )
    updater_intrval_hours = bpy.props.IntProperty(
        name='Hours',
        description = "Number of hours between checking for updates",
        default=0,
        min=0,
        max=23
        )
    updater_intrval_minutes = bpy.props.IntProperty(
        name='Minutes',
        description = "Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59
        )
    updater_expand_prefs = bpy.props.BoolProperty(default=False)

    hdri_path = bpy.props.StringProperty(
        name="HDRI Folder",
        subtype='DIR_PATH',
        description='The folder where all your HDRIs are stored',
        default=functions.get_persistent_setting('hdri_path'),
        update=functions.update_hdri_path
        )
    show_hdri_list = bpy.props.BoolProperty(
        name="Show",
        description="List all the detected HDRIs and their variants/resolutions below",
        default=False
        )
    include_8bit = bpy.props.BoolProperty(
        name="Detect 8-bit images as HDRIs",
        description="Include LDR images like JPGs and PNGs when searching for files in the HDRI folder. Sometimes example renders are put next to HDRI files which can confuse the HDRI detection process, so they are ignored by default. Enable this to include them",
        default=False,
        update = functions.update_hdri_path
        )

    show_debug = bpy.props.BoolProperty(
        name="Show Debug Tools",
        description="Expand this box to show various debugging tools",
        default=False
        )

    ForcePreviewsRefresh = bpy.props.BoolProperty(default = True, options={'HIDDEN'})
    RequestThumbGen = bpy.props.BoolProperty(default = False, options={'HIDDEN'})


    def draw(self, context):
        layout = self.layout

        main_col = layout.column()
        main_col.prop(self, 'hdri_path')

        if self.hdri_path:
            if os.path.exists(self.hdri_path):
                hdris = functions.get_hdri_list()
                if hdris:
                    num_files = sum(len(x) for x in hdris.values())
                    hdris = OrderedDict(sorted(hdris.items(), key=lambda x: x[0].lower()))
                    num_hdris = len(hdris)
                    row = main_col.row()
                    row.alignment = 'RIGHT'
                    row.label("Found {} HDRIs ({} files)".format(num_hdris, num_files))
                    if num_hdris > 0:
                        row.prop(self, 'show_hdri_list', toggle=True)
                    row.operator('gaffer.detect_hdris', "Refresh", icon="FILE_REFRESH")

                    if self.show_hdri_list:
                        col = main_col.column(align=True)
                        for name in hdris:
                            col.label(name)
                            variations = hdris[name]
                            if len(variations) >= 10:
                                row = col.row()
                                row.alignment = 'CENTER'
                                row.label('There are quite a few varations of this HDRI, maybe they were wrongly detected?', icon='QUESTION')
                                row = col.row()
                                row.alignment = 'CENTER'
                                op = row.operator('wm.url_open', "Click here to learn how to fix this", icon='WORLD')
                                op.url = "https://github.com/gregzaal/Gaffer/wiki/HDRI-Detection-and-Grouping"
                            for v in variations:
                                col.label('    '+v)
            else:
                row = main_col.row()
                row.alignment = 'RIGHT'
                row.label("Cannot find HDRI folder :(")
        else:
            row = main_col.row()
            row.alignment = 'RIGHT'
            row.label("Select the folder that contains all your HDRIs. Subfolders will be included.")

        
        row = main_col.row()
        row.alignment = 'RIGHT'
        row.prop(self, 'include_8bit')

        addon_updater_ops.update_settings_ui(self,context)

        box = layout.box()
        col = box.column()
        row = col.row(align=True)
        row.alignment = 'LEFT'
        row.prop(self, 'show_debug', text="Debug Tools", emboss=False, icon="TRIA_DOWN" if self.show_debug else "TRIA_RIGHT")
        if self.show_debug:
            col = box.column()
            col.operator('gaffer.dbg_delete_thumbs')
            col.operator('gaffer.dbg_upload_hdri_list')
            col.operator('gaffer.dbg_upload_logs')


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
        update = functions._update_world_vis)
    WorldReflOnly = bpy.props.BoolProperty(
        name = "Reflection Only",
        default = False,
        description = "Only show the World lighting in reflections",
        update = functions._update_world_refl_only)
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

    # HDRI Handler stuffs
    hdri_handler_enabled = bpy.props.BoolProperty(
        name="Enable",
        description="Turn on/off Gaffer's HDRI handler",
        default=False,
        update=functions.hdri_enable)
    hdri = bpy.props.EnumProperty(
        name="HDRIs",
        items=functions.hdri_enum_previews,
        update=functions.switch_hdri
        )
    hdri_variation = bpy.props.EnumProperty(
        name="Resolution / Variation",
        items=functions.variation_enum_previews,
        update=functions.update_variation
        )
    hdri_search = bpy.props.StringProperty(
        name="Search",
        description="Show only HDRIs matching this text - name, subfolder and tags will match",
        default="",
        update=functions.update_search
        )
    hdri_rotation = bpy.props.FloatProperty(
        name="Rotation",
        description='Rotate the HDRI (in degrees) around the Z-axis',
        default=0,
        soft_min=-180,
        soft_max=180,
        update=functions.update_rotation
        )
    hdri_brightness = bpy.props.FloatProperty(
        name="Brightness",
        description='Change the exposure of the HDRI to emit more or less light (measured in EVs)',
        default=0,
        soft_min=-10,
        soft_max=10,
        update=functions.update_brightness
        )
    hdri_contrast = bpy.props.FloatProperty(
        name="Contrast",
        description='Adjust the Gamma, making light sources stonger or weaker compared to darker parts of the HDRI',
        default=1,
        min=0,
        soft_max=2,
        update=functions.update_contrast
        )
    hdri_saturation = bpy.props.FloatProperty(
        name="Saturation",
        description='Control how strong the colours in the HDRI are',
        default=1,
        min=0,
        soft_max=2,
        update=functions.update_saturation
        )
    hdri_warmth = bpy.props.FloatProperty(
        name="Warmth",
        description='Control the relative color temperature of the HDRI (blue/orange)',
        default=1,
        soft_min=0,
        soft_max=2,
        update=functions.update_warmth
        )
    hdri_tint = bpy.props.FloatProperty(
        name="Tint",
        description='Control the purple/green color balance',
        default=1,
        soft_min=0,
        soft_max=2,
        update=functions.update_tint
        )
    hdri_use_jpg_background = bpy.props.BoolProperty(
        name = "High-res JPG background",
        default = False,
        description = "Use a higher-res JPG image for the background, keeping the HDR just for lighting - enable this and set the main resolution to a low option to save memory",
        update=functions.setup_hdri
        )
    hdri_use_darkened_jpg = bpy.props.BoolProperty(
        name = "Pre-darkened",
        default = False,
        description = "Use a darker version of the JPG to avoid clipped highlights (but at the cost of potential banding)",
        update=functions.setup_hdri
        )
    hdri_use_bg_reflections = bpy.props.BoolProperty(
        name = "Use for reflections",
        default = False,
        description = "Use these settings for the appearance of reflections as well",
        update=functions.setup_hdri
        )
    hdri_use_separate_brightness = bpy.props.BoolProperty(
        name = "Brightness",
        default = False,
        description = "Adjust the brightness value for the background separately from the lighting",
        update=functions.setup_hdri
        )
    hdri_background_brightness = bpy.props.FloatProperty(
        name="Value",
        description='Make the background image brighter or darker without affecting the lighting',
        default=0,
        soft_min=-10,
        soft_max=10,
        update=functions.update_background_brightness
        )
    hdri_use_separate_contrast = bpy.props.BoolProperty(
        name = "Contrast",
        default = False,
        description = "Adjust the contrast value for the background separately from the lighting",
        update=functions.setup_hdri
        )
    hdri_background_contrast = bpy.props.FloatProperty(
        name="Value",
        description='Give the background image more or less contrast without affecting the lighting',
        default=1,
        min=0,
        soft_max=2,
        update=functions.update_background_contrast
        )
    hdri_use_separate_saturation = bpy.props.BoolProperty(
        name = "Saturation",
        default = False,
        description = "Adjust the saturation value for the background separately from the lighting",
        update=functions.setup_hdri
        )
    hdri_background_saturation = bpy.props.FloatProperty(
        name="Value",
        description='Change the saturation of the background image without affecting the lighting',
        default=1,
        min=0,
        soft_max=2,
        update=functions.update_background_saturation
        )
    hdri_use_separate_warmth = bpy.props.BoolProperty(
        name = "Warmth",
        default = False,
        description = "Adjust the warmth value for the background separately from the lighting",
        update=functions.setup_hdri
        )
    hdri_background_warmth = bpy.props.FloatProperty(
        name="Value",
        description='Change the warmth of the background image without affecting the lighting',
        default=1,
        soft_min=0,
        soft_max=2,
        update=functions.update_background_warmth
        )
    hdri_use_separate_tint = bpy.props.BoolProperty(
        name = "Tint",
        default = False,
        description = "Adjust the tint value for the background separately from the lighting",
        update=functions.setup_hdri
        )
    hdri_background_tint = bpy.props.FloatProperty(
        name="Value",
        description='Change the tint of the background image without affecting the lighting',
        default=1,
        soft_min=0,
        soft_max=2,
        update=functions.update_background_tint
        )
    hdri_clamp = bpy.props.FloatProperty(
        name="Clamp Brightness",
        description = "Set any values brighter than this value to this value. Disabled when on 0. Use when bright lights (e.g. sun) are too bright",
        default = 0,
        min = 0,
        soft_max = 50000,
        update = functions.update_clamp
        )
    hdri_advanced = bpy.props.BoolProperty(
        name="Advanced",
        description = "Show/hide advanced settings",
        default = False
        )
    hdri_jpg_gen_all = bpy.props.BoolProperty(
        name="Generate for ALL HDRIs",
        description = "Generate the JPG and darkened JPG for all HDRIs that you have. This will probably take a while",
        default = False
        )
    hdri_show_tags_ui = bpy.props.BoolProperty(
        name="Tags",
        description = "Choose some tags for this HDRI to help you search for it later",
        default = False
        )
    hdri_custom_tags = bpy.props.StringProperty(
        name="New Tag(s)",
        description = "Add some of your own tags to this HDRI - separate by commas or semi-colons",
        default = "",
        update = functions.set_custom_tags
        )

    # Internal vars (not shown in UI)
    IsShowingRadius = bpy.props.BoolProperty(default = False, options={'HIDDEN'})
    IsShowingLabel = bpy.props.BoolProperty(default = False, options={'HIDDEN'})
    BlacklistIndex = bpy.props.IntProperty(default = 0, options={'HIDDEN'})
    VarNameCounter = bpy.props.IntProperty(default = 0, options={'HIDDEN'})
    HDRIList = bpy.props.StringProperty(default = "", options={'HIDDEN'})
    RequestJPGGen = bpy.props.BoolProperty(default = False, options={'HIDDEN'})
    ShowProgress = bpy.props.BoolProperty(default = False, options={'HIDDEN'})
    Progress = bpy.props.FloatProperty(default = 0.0, options={'HIDDEN'})
    ProgressText = bpy.props.StringProperty(default = "", options={'HIDDEN'})
    ProgressBarText = bpy.props.StringProperty(default = "", options={'HIDDEN'})
    ShowHDRIHaven = bpy.props.BoolProperty(default = False, options={'HIDDEN'})
    OldWorldSettings = bpy.props.StringProperty(default = "", options={'HIDDEN'})
    ThumbnailsBigHDRIFound = bpy.props.BoolProperty(default = False, options={'HIDDEN'})
    Blacklist = bpy.props.CollectionProperty(type=BlacklistedObject)  # must be registered after classes


def register():
    addon_updater_ops.register(bl_info)

    functions.previews_register()
    functions.cleanup_logs()

    bpy.types.NODE_PT_active_node_generic.append(ui.gaffer_node_menu_func)
    bpy.utils.register_module(__name__)
    bpy.types.Scene.gaf_props = bpy.props.PointerProperty(type=GafferProperties)
    bpy.app.handlers.load_post.append(operators.load_handler)

def unregister():
    bpy.app.handlers.load_post.remove(operators.load_handler)

    functions.previews_unregister()

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
