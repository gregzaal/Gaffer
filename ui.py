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

import bpy
import os
from . import addon_updater_ops
from collections import OrderedDict

from . import constants as const
from . import functions as fn
from . import operators as ops


def draw_trial(col):
    row = col.row(align=True)
    row.alignment = "RIGHT"
    row.alert = True
    row.label(text="Trial Version")
    row.alert = False
    row.operator(
        "wm.url_open", text="", icon="URL", emboss=False
    ).url = "http://bit.ly/gafpanel-trial"
    col.separator()


def update_category(self, context):
    classes = [GAFFER_PT_lights, GAFFER_PT_tools]
    for panel in classes:
        try:
            bpy.utils.unregister_class(panel)
        except RuntimeError:
            # Not yet registered
            pass
        panel.bl_category = self.panel_category
        bpy.utils.register_class(panel)


# UI stuff that's shown for all renderers
def draw_renderer_independant(gaf_props, row, light, icons, users=[None, 1]):

    if bpy.context.scene.render.engine in const.supported_renderers:
        if "_Light:_(" + light.name + ")_" in gaf_props.MoreExpand and not gaf_props.MoreExpandAll:
            row.operator(
                ops.GAFFER_OT_hide_more.bl_idname,
                icon="DOWNARROW_HLT",
                text="",
                emboss=False,
            ).light = light.name
        elif not gaf_props.MoreExpandAll:
            row.operator(
                ops.GAFFER_OT_show_more.bl_idname,
                icon="RIGHTARROW",
                text="",
                emboss=False,
            ).light = light.name

    data_name = light.name if users[1] == 1 else (users[0][5:] if users[0].startswith("LIGHT") else users[0][3:])
    if gaf_props.SoloActive == "":
        prefs = bpy.context.preferences.addons[__package__].preferences
        if users[1] == 1:
            if prefs.auto_refresh_light_list:
                row.prop(light, "name", text="")
            else:
                row.operator(ops.GAFFER_OT_rename.bl_idname, text=data_name).light = light.name
        else:
            op = row.operator(
                ops.GAFFER_OT_set_light_data_user_names.bl_idname,
                text="",
                icon_value=icons[f"num_{str(min(10, users[1]))}"].icon_id,
            )
            op.data_name = data_name
            op.data_type = "lights" if users[0].startswith("LIGHT") else "materials"
            if prefs.auto_refresh_light_list:
                if light.type == "LIGHT":
                    row.prop(light.data, "name", text="")
                else:
                    row.prop(bpy.data.materials[data_name], "name", text="")
            else:
                op = row.operator(
                    ops.GAFFER_OT_rename.bl_idname,
                    text=data_name,
                )
                op.multiuser = users[0]
                op.light = data_name
    else:
        # Don't allow names to be edited during solo, will break the record of what was originally hidden
        row.label(text=data_name)

    visop = row.operator(
        ops.GAFFER_OT_hide_show_light.bl_idname,
        text="",
        icon="%s" % "HIDE_ON" if light.hide_viewport else "HIDE_OFF",
        emboss=False,
    )
    visop.light = light.name
    visop.dataname = users[0] if users[1] > 1 else "__SINGLE_USER__"
    visop.hide = not light.hide_viewport

    sub = row.column(align=True)
    sub.alert = light.select_get()
    selop = sub.operator(
        ops.GAFFER_OT_select_light.bl_idname,
        text="",
        icon="%s" % "RESTRICT_SELECT_OFF" if light.select_get() else "RESTRICT_SELECT_ON",
        emboss=False,
    )
    selop.light = light.name
    selop.dataname = users[0] if users[1] > 1 else "__SINGLE_USER__"

    if gaf_props.SoloActive == "":
        sub = row.column(align=True)
        solobtn = sub.operator(ops.GAFFER_OT_solo.bl_idname, icon="EVENT_S", text="", emboss=False)
        solobtn.light = light.name
        solobtn.showhide = True
        solobtn.worldsolo = False
        solobtn.dataname = users[0] if users[1] > 1 else "__SINGLE_USER__"
    elif gaf_props.SoloActive == light.name:
        sub = row.column(align=True)
        sub.alert = True
        solobtn = sub.operator(ops.GAFFER_OT_solo.bl_idname, icon="EVENT_S", text="", emboss=False)
        solobtn.light = light.name
        solobtn.showhide = False
        solobtn.worldsolo = False


def draw_cycles_eevee_UI(context, layout, lights):
    def draw_strength_cycles(col, light, material, node_strength, socket_strength_type, socket_strength):
        row = col.row(align=True)
        strength_sockets = node_strength.inputs
        if socket_strength_type == "o":
            strength_sockets = node_strength.outputs
        if light.type == "LIGHT":
            row.prop(
                light.data,
                "type",
                text="",
                icon="LIGHT_%s" % light.data.type,
                icon_only=True,
            )
        else:
            row.label(text="", icon="MESH_GRID")

        try:
            if (
                (socket_strength_type == "i" and not strength_sockets[socket_strength].is_linked)
                or (socket_strength_type == "o" and strength_sockets[socket_strength].is_linked)
            ) and hasattr(strength_sockets[socket_strength], "default_value"):
                op = row.operator(ops.GAFFER_OT_set_strength.bl_idname, text="", icon="REMOVE")
                op.light = light.name
                op.node = node_strength.name
                op.material = material.name if material else ""
                op.socket_strength = socket_strength
                op.socket_strength_type = socket_strength_type
                op.increase = False
                row.prop(strength_sockets[socket_strength], "default_value", text="Strength")
                op = row.operator(ops.GAFFER_OT_set_strength.bl_idname, text="", icon="ADD")
                op.light = light.name
                op.node = node_strength.name
                op.material = material.name if material else ""
                op.socket_strength = socket_strength
                op.socket_strength_type = socket_strength_type
                op.increase = True
            else:
                row.label(text="  Node Invalid")
        except (KeyError, IndexError, AttributeError):
            row.label(text="  Node Invalid")

    def draw_strength_eevee(col, light):
        row = col.row(align=True)
        row.prop(
            light.data,
            "type",
            text="",
            icon="LIGHT_%s" % light.data.type,
            icon_only=True,
        )
        op = row.operator(ops.GAFFER_OT_set_strength.bl_idname, text="", icon="REMOVE")
        op.light = light.name
        op.node = ""
        op.material = ""
        op.socket_strength = 0
        op.socket_strength_type = ""
        op.increase = False
        row.prop(light.data, "energy", text="Strength")
        op = row.operator(ops.GAFFER_OT_set_strength.bl_idname, text="", icon="ADD")
        op.light = light.name
        op.node = ""
        op.material = ""
        op.socket_strength = 0
        op.socket_strength_type = ""
        op.increase = True

    def draw_color_cycles(gaf_props, i, icons, col, row, light, material):
        if light.type == "LIGHT":
            nodes = light.data.node_tree.nodes
        else:
            nodes = material.node_tree.nodes
        socket_color = 0
        node_color = None
        emissions = []  # make a list of all linked Emission shaders, use the right-most one
        for node in nodes:
            if node.type == "EMISSION":
                if node.outputs[0].is_linked:
                    emissions.append(node)
        if emissions:
            node_color = sorted(emissions, key=lambda x: x.location.x, reverse=True)[0]

            if not node_color.inputs[socket_color].is_linked:
                subcol = row.column(align=True)
                subrow = subcol.row(align=True)
                subrow.scale_x = 0.3
                subrow.prop(node_color.inputs[socket_color], "default_value", text="")
            else:
                from_node = node_color.inputs[socket_color].links[0].from_node
                if from_node.type == "RGB":
                    subcol = row.column(align=True)
                    subrow = subcol.row(align=True)
                    subrow.scale_x = 0.3
                    subrow.prop(from_node.outputs[0], "default_value", text="")
                elif from_node.type == "TEX_IMAGE" or from_node.type == "TEX_ENVIRONMENT":
                    row.prop(from_node, "image", text="")
                elif from_node.type == "BLACKBODY":
                    row.prop(from_node.inputs[0], "default_value", text="Temperature")
                    if gaf_props.ColTempExpand and gaf_props.LightUIIndex == i:
                        row.operator(
                            ops.GAFFER_OT_hide_temp_list.bl_idname,
                            text="",
                            icon="TRIA_UP",
                        )
                        col = col.column(align=True)
                        col.separator()
                        col.label(text="Color Temp. Presets:")
                        ordered_col_temps = OrderedDict(sorted(const.col_temp.items()))
                        for temp in ordered_col_temps:
                            op = col.operator(
                                ops.GAFFER_OT_set_temp.bl_idname,
                                text=temp[3:],
                                icon_value=icons[str(const.col_temp[temp])].icon_id,
                            )
                            op.temperature = temp
                            op.light = light.name
                            if material:
                                op.material = material.name
                            if node_color:
                                op.node = node_color.name
                        col.separator()
                    else:
                        row.operator(
                            ops.GAFFER_OT_show_temp_list.bl_idname,
                            text="",
                            icon="COLOR",
                        ).l_index = i
                elif from_node.type == "WAVELENGTH":
                    row.prop(from_node.inputs[0], "default_value", text="Wavelength")

    def draw_color_eevee(row, light):
        subcol = row.column(align=True)
        subrow = subcol.row(align=True)
        subrow.scale_x = 0.3
        subrow.prop(light.data, "color", text="")

    def draw_more_options_cycles(box, scene, light, material, node_strength, is_portal):
        col = box.column()
        row = col.row(align=True)

        visibility = [
            ("camera", "Cam"),
            ("diffuse", "Diff"),
            ("glossy", "Spec"),
        ]

        if hasattr(light.data, "shape"):
            row.prop(light.data, "shape", text="")
            row = col.row(align=True)

        if light.type == "LIGHT":
            if light.data.type == "AREA":
                if light.data.shape in ["RECTANGLE", "ELLIPSE"]:
                    row.prop(light.data, "size")
                    row.prop(light.data, "size_y")
                    row = col.row(align=True)
                else:
                    row.prop(light.data, "size")
                if hasattr(light.data, "spread"):
                    row.prop(light.data, "spread")
            elif light.data.type == "SUN":
                row.prop(light.data, "angle")
            else:
                row.prop(light.data, "shadow_soft_size", text="Size")

            if hasattr(scene.cycles, "progressive") and scene.cycles.progressive == "BRANCHED_PATH":
                row.prop(light.data.cycles, "samples")

            if not is_portal:
                row = col.row(align=True)
                row.prop(
                    light.data.cycles,
                    "use_multiple_importance_sampling",
                    text="MIS",
                    toggle=True,
                )
                row.prop(light.data.cycles, "cast_shadow", text="Shadows", toggle=True)
                row.separator()
                for v in visibility[1:]:  # All but camera
                    if bpy.app.version_string >= "3.0":
                        row.prop(light, "visible_" + v[0], text=v[1], toggle=True)
                    else:
                        row.prop(light.cycles_visibility, v[0], text=v[1], toggle=True)

            if light.data.type == "SPOT":
                row = col.row(align=True)
                row.prop(light.data, "spot_size", text="Spot Size")
                row.prop(light.data, "spot_blend", text="Blend", slider=True)
                row.prop(light.data, "show_cone", text="", toggle=True, icon="CONE")

        else:  # MESH light
            if hasattr(material.cycles, "sample_as_light"):
                row.prop(material.cycles, "sample_as_light", text="MIS", toggle=True)
            row.separator()
            for v in visibility:
                if bpy.app.version_string >= "3.0":
                    row.prop(light, "visible_" + v[0], text=v[1], toggle=True)
                else:
                    row.prop(light.cycles_visibility, v[0], text=v[1], toggle=True)

        if hasattr(light, "GafferFalloff") and scene.render.engine == "CYCLES":
            drawfalloff = True
            if light.type == "LIGHT":
                if (
                    light.data.type == "SUN"
                    or light.data.type == "HEMI"
                    or (light.data.type == "AREA" and light.data.cycles.is_portal)
                ):
                    drawfalloff = False
                if not light.data.use_nodes:
                    drawfalloff = False
            if drawfalloff and node_strength is not None:
                col.prop(light, "GafferFalloff", text="Falloff")
                if node_strength.type != "LIGHT_FALLOFF" and light.GafferFalloff != "quadratic":
                    col.label(text="Light Falloff node is missing", icon="ERROR")

        if light.type == "LIGHT":
            if light.data.type == "AREA":
                col.prop(light.data.cycles, "is_portal")

        # Light groups
        if len(context.view_layer.lightgroups) > 0:
            row = col.row(align=True)
            row.use_property_decorate = False

            sub = row.column(align=True)
            sub.prop_search(
                light, "lightgroup", context.view_layer, "lightgroups", text="Group", results_are_suggestions=True
            )

            sub = row.column(align=True)
            if bool(light.lightgroup) and not any(lg.name == light.lightgroup for lg in context.view_layer.lightgroups):
                row.operator("scene.view_layer_add_lightgroup", icon="ADD", text="").name = light.lightgroup

    def draw_more_options_eevee(box, scene, light):
        col = box.column()
        row = col.row(align=True)

        if light.data.type == "AREA":
            if light.data.shape in ["RECTANGLE", "ELLIPSE"]:
                row.prop(light.data, "size")
                row.prop(light.data, "size_y")
                row = col.row(align=True)
            else:
                row.prop(light.data, "size")
        elif light.data.type == "SUN":
            row.prop(light.data, "angle")
        else:
            row.prop(light.data, "shadow_soft_size", text="Size")

        row = col.row(align=True)
        row.prop(light.data, "use_shadow", text="Shadows", toggle=True)
        if light.data.use_shadow:
            row.prop(light.data, "use_contact_shadow", text="Contact", toggle=True)
            if light.data.use_contact_shadow:
                row.prop(light.data, "contact_shadow_thickness")
        row.separator()
        row.prop(light.data, "specular_factor")

        if light.data.type == "SPOT":
            row = col.row(align=True)
            row.prop(light.data, "spot_size", text="Spot Size")
            row.prop(light.data, "spot_blend", text="Blend", slider=True)
            row.prop(light.data, "show_cone", text="", toggle=True, icon="CONE")

    def draw_world(context, layout, gaf_props, gaf_hdri_props, scene, prefs, icons):
        world = context.scene.world
        box = layout.box()
        worldcol = box.column(align=True)
        col = worldcol.column(align=True)

        row = col.row(align=True)

        if "_Light:_(WorldEnviroLight)_" in gaf_props.MoreExpand and not gaf_props.MoreExpandAll:
            row.operator(
                ops.GAFFER_OT_hide_more.bl_idname,
                icon="TRIA_DOWN",
                text="",
                emboss=False,
            ).light = "WorldEnviroLight"
        elif not gaf_props.MoreExpandAll:
            row.operator(
                ops.GAFFER_OT_show_more.bl_idname,
                text="",
                icon="TRIA_RIGHT",
                emboss=False,
            ).light = "WorldEnviroLight"

        row.label(text="World")
        if scene.render.engine == "CYCLES":
            row.prop(
                gaf_props,
                "WorldVis",
                text="",
                icon="%s" % "HIDE_OFF" if gaf_props.WorldVis else "HIDE_ON",
                emboss=False,
            )

        if gaf_props.SoloActive == "":
            sub = row.column(align=True)
            solobtn = sub.operator(ops.GAFFER_OT_solo.bl_idname, icon="EVENT_S", text="", emboss=False)
            solobtn.light = "WorldEnviroLight"
            solobtn.showhide = True
            solobtn.worldsolo = True
        elif gaf_props.SoloActive == "WorldEnviroLight":
            sub = row.column(align=True)
            sub.alert = True
            solobtn = sub.operator(ops.GAFFER_OT_solo.bl_idname, icon="EVENT_S", text="", emboss=False)
            solobtn.light = "WorldEnviroLight"
            solobtn.showhide = False
            solobtn.worldsolo = True

        col = worldcol.column()

        if gaf_hdri_props.hdri_handler_enabled:
            draw_hdri_handler(
                context,
                col,
                gaf_props,
                gaf_hdri_props,
                fn.get_persistent_setting("hdri_paths"),
                prefs,
                icons,
                toolbar=True,
            )
        else:
            row = col.row(align=True)

            row.label(text="", icon="WORLD")
            row.separator()

            color_node = None
            if world.use_nodes:
                backgrounds = []  # make a list of all linked Background shaders, use the right-most one
                background = None
                for node in world.node_tree.nodes:
                    if node.type == "BACKGROUND":
                        if not node.name.startswith("HDRIHandler_"):
                            if node.outputs[0].is_linked:
                                backgrounds.append(node)
                if backgrounds:
                    background = sorted(backgrounds, key=lambda x: x.location.x, reverse=True)[0]
                    # Strength
                    if background.inputs[1].is_linked:
                        strength_node = None
                        current_node = background.inputs[1].links[0].from_node
                        temp_current_node = None
                        # Failsafe in case of infinite loop (which can happen from accidental cyclic links)
                        i = 0
                        while strength_node is None and i < 1000:  # limitted to 100 chained nodes
                            i += 1
                            connected_inputs = False
                            if temp_current_node:
                                current_node = temp_current_node
                            for socket in current_node.inputs:
                                # stop at first node with an unconnected Value socket
                                if socket.type == "VALUE" and not socket.is_linked:
                                    strength_node = current_node
                                else:
                                    if socket.is_linked:
                                        temp_current_node = socket.links[0].from_node

                        if strength_node:
                            for socket in strength_node.inputs:
                                if socket.type == "VALUE" and not socket.is_linked:  # use first color socket
                                    row.prop(socket, "default_value", text="Strength")
                                    break
                    else:
                        row.prop(background.inputs[1], "default_value", text="Strength")

                    # Color
                    if background.inputs[0].is_linked:
                        current_node = background.inputs[0].links[0].from_node
                        # Failsafe in case of infinite loop (which can happen from accidental cyclic links)
                        i = 0
                        while color_node is None and i < 100:  # limitted to 100 chained nodes
                            i += 1
                            connected_inputs = False
                            for socket in current_node.inputs:
                                # stop at node end of chain, or node with only vector inputs:
                                if socket.type != "VECTOR" and socket.is_linked:
                                    connected_inputs = True
                                    current_node = socket.links[0].from_node
                            if not connected_inputs:
                                color_node = current_node

                        if color_node.type == "TEX_IMAGE" or color_node.type == "TEX_ENVIRONMENT":
                            row.prop(color_node, "image", text="")
                        elif color_node.type == "TEX_SKY":
                            row.prop(color_node, "sun_direction", text="")
                        else:
                            if color_node.inputs:
                                for socket in color_node.inputs:
                                    if socket.type == "RGBA":  # use first color socket
                                        row.prop(socket, "default_value", text="")
                                        break
                    else:
                        row.prop(background.inputs[0], "default_value", text="")
                else:
                    row.label(text="No node found!")
            else:
                row.prop(world, "horizon_color", text="")

        # Extra
        if "_Light:_(WorldEnviroLight)_" in gaf_props.MoreExpand or gaf_props.MoreExpandAll:
            worldcol.separator()
            col = worldcol.column()
            if scene.render.engine == "CYCLES":
                row = col.row()
                row.prop(world.cycles, "sampling_method", text="")
                row.prop(gaf_props, "WorldReflOnly", text="Refl Only")
                if world.cycles.sampling_method != "NONE":
                    col = worldcol.column()
                    row = col.row(align=True)
                    if world.cycles.sampling_method == "MANUAL":
                        row.prop(world.cycles, "sample_map_resolution", text="MIS res")
                    if hasattr(scene.cycles, "progressive") and scene.cycles.progressive == "BRANCHED_PATH":
                        row.prop(world.cycles, "samples", text="Samples")
                worldcol.separator()
                col = worldcol.column(align=True)
                if hasattr(scene.cycles, "use_fast_gi"):
                    col.prop(
                        scene.cycles,
                        "use_fast_gi",
                        text="Fast GI",
                    )
                    if scene.cycles.use_fast_gi:
                        row = col.row(align=True)
                        row.prop(scene.cycles, "fast_gi_method", text="")
                        row.prop(world.light_settings, "ao_factor")
                        row.prop(world.light_settings, "distance")
                else:
                    # Legacy Blender support
                    col.prop(
                        world.light_settings,
                        "use_ambient_occlusion",
                        text="Ambient Occlusion",
                    )
                    if world.light_settings.use_ambient_occlusion:
                        row = col.row(align=True)
                        row.prop(world.light_settings, "ao_factor")
                        row.prop(world.light_settings, "distance")

                # Light groups
                if len(context.view_layer.lightgroups) > 0:
                    row = col.row(align=True)
                    row.use_property_decorate = False

                    sub = row.column(align=True)
                    sub.prop_search(
                        world,
                        "lightgroup",
                        context.view_layer,
                        "lightgroups",
                        text="Group",
                        results_are_suggestions=True,
                    )

                    sub = row.column(align=True)
                    if bool(world.lightgroup) and not any(
                        lg.name == world.lightgroup for lg in context.view_layer.lightgroups
                    ):
                        row.operator("scene.view_layer_add_lightgroup", icon="ADD", text="").name = world.lightgroup
            else:
                worldcol.separator()
                col = worldcol.column(align=True)
                col.prop(scene.eevee, "use_gtao", text="Ambient Occlusion")
                if scene.eevee.use_gtao:
                    row = col.row(align=True)
                    row.prop(scene.eevee, "gtao_factor")
                    row.prop(scene.eevee, "gtao_distance")

            if not gaf_hdri_props.hdri_handler_enabled:
                if color_node:
                    if color_node.type == "TEX_SKY":
                        if world.node_tree and world.use_nodes:
                            col = worldcol.column(align=True)
                            row = col.row(align=True)
                            if gaf_props.SunObject:
                                row.operator(
                                    ops.GAFFER_OT_link_sky_to_sun.bl_idname,
                                    icon="LIGHT_SUN",
                                ).node_name = color_node.name
                            else:
                                row.label(text="Link Sky Texture:")
                            row.prop_search(gaf_props, "SunObject", bpy.data, "objects", text="")

    maincol = layout.column(align=False)
    scene = context.scene
    gaf_props = scene.gaf_props
    prefs = context.preferences.addons[__package__].preferences
    icons = fn.get_icons()

    lights_to_show = []
    # Check validity of list and make list of lights to display
    vis_cols = fn.visibleCollections()
    for light in lights:
        try:
            if light[0]:
                # Will cause KeyError exception if obj no longer exists
                a = bpy.data.objects[light[0][1:-1]]
                if (gaf_props.VisibleLightsOnly and not a.hide_viewport) or (not gaf_props.VisibleLightsOnly):
                    if a.type != "LIGHT":
                        b = bpy.data.materials[light[1][1:-1]]
                        if b.use_nodes:
                            b.node_tree.nodes[light[2][1:-1]]
                    else:
                        if a.data.use_nodes:
                            a.data.node_tree.nodes[light[2][1:-1]]
                    if (gaf_props.VisibleCollectionsOnly and fn.isInVisibleCollection(a, vis_cols)) or (
                        not gaf_props.VisibleCollectionsOnly
                    ):
                        if a.name not in [o.name for o in gaf_props.Blacklist]:
                            lights_to_show.append(light)
        except KeyError:
            box = maincol.box()
            row = box.row(align=True)
            row.label(text="Light list out of date")
            fn.tag_refresh_light_list()  # We can't refresh the list here, so we tag it for the next depsgraph update
            row.operator(ops.GAFFER_OT_refresh_light_list.bl_idname, icon="FILE_REFRESH", text="")

    # Don't show lights that share the same data
    duplicates = {}
    """
    duplicates:
        A dict with the key: object type + data name (cannot use only the name in case of conflicts).
        The values are the number of duplicates for that key.
    """
    templist = []
    for item in lights_to_show:
        light = scene.objects[item[0][1:-1]]  # drop the apostrophes
        if light.type == "LIGHT":
            if ("LIGHT" + light.data.name) in duplicates:
                duplicates["LIGHT" + light.data.name] += 1
            else:
                templist.append(item)
                duplicates["LIGHT" + light.data.name] = 1
        else:
            mat = bpy.data.materials[item[1][1:-1]]
            if ("MAT" + mat.name) in duplicates:
                duplicates["MAT" + mat.name] += 1
            else:
                templist.append(item)
                duplicates["MAT" + mat.name] = 1
    lights_to_show = templist

    i = 0
    for item in lights_to_show:
        light = scene.objects[item[0][1:-1]]  # drop the apostrophes
        light_uses_nodes = True
        is_portal = False
        if light.type == "LIGHT":
            material = None
            if light.data.use_nodes:
                node_strength = light.data.node_tree.nodes[item[2][1:-1]]
            else:
                light_uses_nodes = False

            if light.data.type == "AREA" and light.data.cycles.is_portal and scene.render.engine == "CYCLES":
                is_portal = True
        else:
            material = bpy.data.materials[item[1][1:-1]]
            if material.use_nodes:
                node_strength = material.node_tree.nodes[item[2][1:-1]]
            else:
                light_uses_nodes = False

        if light.type == "LIGHT":
            users = ["LIGHT" + light.data.name, duplicates["LIGHT" + light.data.name]]
        else:
            users = ["MAT" + material.name, duplicates["MAT" + material.name]]

        if light_uses_nodes and scene.render.engine == "CYCLES":
            box = maincol.box()
            rowmain = box.row()
            split = rowmain.split()
            col = split.column()
            row = col.row(align=True)

            if item[3].startswith("'"):
                socket_strength_str = str(item[3][1:-1])
            else:
                socket_strength_str = str(item[3])

            if socket_strength_str.startswith("o"):
                socket_strength_type = "o"
                socket_strength = int(socket_strength_str[1:])
            elif socket_strength_str.startswith("i"):
                socket_strength_type = "i"
                socket_strength = int(socket_strength_str[1:])
            else:
                socket_strength_type = "i"
                socket_strength = int(socket_strength_str)

            draw_renderer_independant(gaf_props, row, light, icons, users)

            if not is_portal:
                draw_strength_cycles(col, light, material, node_strength, socket_strength_type, socket_strength)

                draw_color_cycles(gaf_props, i, icons, col, row, light, material)

            if "_Light:_(" + light.name + ")_" in gaf_props.MoreExpand or gaf_props.MoreExpandAll:
                draw_more_options_cycles(box, scene, light, material, node_strength, is_portal)
            i += 1
        elif light.type == "LIGHT":
            box = maincol.box()
            rowmain = box.row()
            split = rowmain.split()
            col = split.column()
            row = col.row(align=True)

            draw_renderer_independant(gaf_props, row, light, icons, users)

            if not is_portal:
                draw_strength_eevee(col, light)

                draw_color_eevee(row, light)

            if "_Light:_(" + light.name + ")_" in gaf_props.MoreExpand or gaf_props.MoreExpandAll:
                if scene.render.engine == "CYCLES":
                    draw_more_options_cycles(box, scene, light, material, None, is_portal)
                else:
                    draw_more_options_eevee(box, scene, light)
            i += 1

    if len(lights_to_show) == 0:
        row = maincol.row()
        row.alignment = "CENTER"
        row.label(text="No lights to show :)")

    if context.scene.world:
        gaf_hdri_props = scene.world.gaf_hdri_props
        draw_world(context, layout, gaf_props, gaf_hdri_props, scene, prefs, icons)


def draw_unsupported_renderer_UI(context, layout, lights):
    maincol = layout.column(align=False)
    scene = context.scene
    gaf_props = scene.gaf_props
    gaf_hdri_props = scene.world.gaf_hdri_props
    prefs = context.preferences.addons[__package__].preferences
    icons = fn.get_icons()

    lights_to_show = []
    # Check validity of list and make list of lights to display
    vis_cols = fn.visibleCollections()
    for light in lights:
        try:
            if light[0]:
                # Will cause KeyError exception if obj no longer exists
                a = bpy.data.objects[light[0][1:-1]]
                if (gaf_props.VisibleLightsOnly and not a.hide_viewport) or (not gaf_props.VisibleLightsOnly):
                    if (gaf_props.VisibleCollectionsOnly and fn.isInVisibleCollection(a, vis_cols)) or (
                        not gaf_props.VisibleCollectionsOnly
                    ):
                        if a.name not in [o.name for o in gaf_props.Blacklist]:
                            lights_to_show.append(light)
        except KeyError:
            box = maincol.box()
            row = box.row(align=True)
            row.label(text="Light list out of date")
            row.operator(ops.GAFFER_OT_refresh_light_list.bl_idname, icon="FILE_REFRESH", text="")

    # Don't show lights that share the same data
    duplicates = {}
    """
    duplicates:
        A dict with the key: object type + data name (cannot use only the name in case of conflicts).
        The values are the number of duplicates for that key.
    """
    templist = []
    for item in lights_to_show:
        light = scene.objects[item[0][1:-1]]  # drop the apostrophes
        if light.type == "LIGHT":
            if ("LIGHT" + light.data.name) in duplicates:
                duplicates["LIGHT" + light.data.name] += 1
            else:
                templist.append(item)
                duplicates["LIGHT" + light.data.name] = 1
    lights_to_show = templist

    i = 0
    for item in lights_to_show:
        light = scene.objects[item[0][1:-1]]  # drop the apostrophes

        box = maincol.box()
        rowmain = box.row()
        split = rowmain.split()
        col = split.column()
        row = col.row(align=True)

        if light.type == "LIGHT":
            users = ["LIGHT" + light.data.name, duplicates["LIGHT" + light.data.name]]
        else:
            users = ["MAT" + light.name, duplicates["MAT" + light.name]]
        draw_renderer_independant(gaf_props, row, light, icons, users)
        i += 1

    if len(lights_to_show) == 0:
        row = maincol.row()
        row.alignment = "CENTER"
        row.label(text="No lights to show :)")

    # World
    if context.scene.world and gaf_hdri_props.hdri_handler_enabled and context.scene.render.engine in ["BLENDER_EEVEE"]:
        box = layout.box()
        worldcol = box.column(align=True)
        col = worldcol.column(align=True)

        row = col.row(align=True)

        if "_Light:_(WorldEnviroLight)_" in gaf_props.MoreExpand and not gaf_props.MoreExpandAll:
            row.operator(
                ops.GAFFER_OT_hide_more.bl_idname,
                icon="TRIA_DOWN",
                text="",
                emboss=False,
            ).light = "WorldEnviroLight"
        elif not gaf_props.MoreExpandAll:
            row.operator(
                ops.GAFFER_OT_show_more.bl_idname,
                text="",
                icon="TRIA_RIGHT",
                emboss=False,
            ).light = "WorldEnviroLight"

        row.label(text="World")
        col = worldcol.column()
        draw_hdri_handler(
            context, col, gaf_props, gaf_hdri_props, fn.get_persistent_setting("hdri_paths"), prefs, icons, toolbar=True
        )


class GAFFER_PT_lights(bpy.types.Panel):

    bl_label = "Lights"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Gaffer"

    def draw(self, context):
        addon_updater_ops.check_for_update_background()

        scene = context.scene
        gaf_props = scene.gaf_props
        lights_str = gaf_props.Lights
        lights = fn.stringToNestedList(lights_str)
        layout = self.layout
        col = layout.column(align=True)

        draw_trial(col)

        row = col.row(align=True)
        if gaf_props.SoloActive != "":  # if in solo mode
            sub = row.column(align=True)
            sub.alert = True
            solobtn = sub.operator(ops.GAFFER_OT_solo.bl_idname, icon="EVENT_S", text="")
            solobtn.light = "None"
            solobtn.showhide = False
            solobtn.worldsolo = False

        # may not be needed if drawing errors are cought correctly (eg newly added lights):
        row.operator(
            ops.GAFFER_OT_refresh_light_list.bl_idname,
            text="Refresh",
            icon="FILE_REFRESH",
        )

        row.prop(gaf_props, "VisibleCollectionsOnly", text="", icon="LAYER_ACTIVE")
        row.prop(gaf_props, "VisibleLightsOnly", text="", icon="HIDE_OFF")
        row.prop(gaf_props, "MoreExpandAll", text="", icon="PREFERENCES")

        if gaf_props.SoloActive != "":
            try:
                # Will cause KeyError if object by that name doesn't exist
                bpy.data.objects[gaf_props.SoloActive]
            except KeyError:
                if gaf_props.SoloActive != "WorldEnviroLight":
                    # In case solo'd light changes name, theres no other way to exit solo mode
                    col.separator()
                    row = col.row()
                    row.alert = True
                    solobtn = row.operator(
                        ops.GAFFER_OT_solo.bl_idname,
                        icon="EVENT_S",
                        text="Light not found, reset Solo",
                    )
                    solobtn.showhide = False

        row = col.row(align=True)
        row.prop(
            bpy.context.scene.view_settings,
            "exposure",
            text="Global Exposure",
            slider=False,
        )
        if bpy.context.scene.render.engine in const.supported_renderers:
            row.operator(ops.GAFFER_OT_apply_exposure.bl_idname, text="", icon="CHECKBOX_HLT")

        if scene.render.engine == "CYCLES":
            draw_cycles_eevee_UI(context, layout, lights)
        elif scene.render.engine == "BLENDER_EEVEE":
            draw_cycles_eevee_UI(context, layout, lights)
        else:
            draw_unsupported_renderer_UI(context, layout, lights)
            box = layout.box()
            col = box.column(align=True)
            row = col.row()
            row.alignment = "CENTER"
            row.label(text="Warning", icon="ERROR")
            row = col.row()
            row.alignment = "CENTER"
            row.label(text="Render engine not fully supported.")
            row = col.row()
            row.alignment = "CENTER"
            row.label(text="Gaffer functionality is limitted.")
            row = col.row(align=True)
            row.alignment = "CENTER"
            row.label(text="Click here to add your vote:")
            row.operator("wm.url_open", text="", icon="URL").url = "https://forms.gle/R22DphecWsXmaLAr9"

        addon_updater_ops.update_notice_box_ui(self, context)


class GAFFER_PT_tools(bpy.types.Panel):

    bl_label = "Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Gaffer"

    def draw(self, context):
        scene = context.scene
        gaf_props = scene.gaf_props
        layout = self.layout

        maincol = layout.column()

        # Aiming
        maincol.separator()
        box = maincol.box()
        subcol = box.column(align=True)
        row = subcol.row()
        row.alignment = "CENTER"
        row.label(text="Aim:", icon="LIGHT_AREA")
        row = subcol.row()
        col = row.column(align=True)
        col.label(text="Selected:")
        col.operator(ops.GAFFER_OT_aim_light.bl_idname, text="at 3D cursor", icon="PIVOT_CURSOR").target_type = "CURSOR"
        col.operator(ops.GAFFER_OT_aim_light.bl_idname, text="at active", icon="FULLSCREEN_EXIT").target_type = "ACTIVE"
        col = row.column(align=True)
        col.label(text="Active:")
        col.operator(ops.GAFFER_OT_aim_light.bl_idname, text="at selected", icon="PARTICLES").target_type = "SELECTED"
        col.operator(
            ops.GAFFER_OT_aim_light_with_view.bl_idname,
            text="w/ 3D View",
            icon="VIEW_CAMERA",
        )

        maincol.separator()

        # Draw Radius
        if context.scene.render.engine in const.supported_renderers:
            box = maincol.box() if gaf_props.IsShowingRadius else maincol.column()
            sub = box.column(align=True)
            row = sub.row(align=True)
            row.operator(
                ops.GAFFER_OT_show_light_radius.bl_idname,
                text="Show Radius" if not gaf_props.IsShowingRadius else "Hide Radius",
                icon="MESH_CIRCLE",
            )
            if gaf_props.IsShowingRadius:
                row.operator(ops.GAFFER_OT_refresh_bgl.bl_idname, text="", icon="FILE_REFRESH")
                sub.prop(gaf_props, "LightRadiusAlpha", slider=True)
                row = sub.row(align=True)
                row.active = gaf_props.IsShowingRadius
                row.prop(gaf_props, "LightRadiusDrawType", text="")
                row.prop(gaf_props, "LightRadiusUseColor")
                row = sub.row(align=True)
                row.active = gaf_props.IsShowingRadius
                row.prop(gaf_props, "LightRadiusXray")
                row.prop(gaf_props, "LightRadiusSelectedOnly")
                row = sub.row(align=True)
                row.prop(gaf_props, "DefaultRadiusColor")

        # Draw Label
        box = maincol.box() if gaf_props.IsShowingLabel else maincol.column()
        sub = box.column(align=True)
        row = sub.row(align=True)
        row.operator(
            ops.GAFFER_OT_show_light_label.bl_idname,
            text="Show Label" if not gaf_props.IsShowingLabel else "Hide Label",
            icon="ALIGN_LEFT",
        )
        if gaf_props.IsShowingLabel:
            row.operator(ops.GAFFER_OT_refresh_bgl.bl_idname, text="", icon="FILE_REFRESH")
            label_draw_type = gaf_props.LabelDrawType
            sub.prop(gaf_props, "LabelAlpha", slider=True)
            sub.prop(gaf_props, "LabelFontSize")
            row = sub.row(align=True)
            row.prop(gaf_props, "LabelDrawType", text="")
            row.prop(gaf_props, "LabelUseColor")
            if label_draw_type == "color_bg" or not gaf_props.LabelUseColor:
                row = sub.row(align=True)
                row.prop(gaf_props, "LabelTextColor")
            if label_draw_type == "plain_bg" or (not gaf_props.LabelUseColor and label_draw_type != "color_text"):
                row = sub.row(align=True)
                row.prop(gaf_props, "DefaultLabelBGColor")
            row = sub.row(align=True)
            row.prop(gaf_props, "LabelAlign", text="")
            if gaf_props.LabelAlign != "c":
                row.prop(gaf_props, "LabelMargin")

        maincol.separator()

        # Blacklist
        box = maincol.box()
        sub = box.column(align=True)
        sub.label(text="Blacklist:")
        if gaf_props.Blacklist:
            sub.template_list(
                "OBJECT_UL_object_list",
                "",
                gaf_props,
                "Blacklist",
                gaf_props,
                "BlacklistIndex",
                rows=2,
            )
        row = sub.row(align=True)
        row.operator(ops.GAFFER_OT_add_blacklisted.bl_idname, icon="ADD")
        row.operator(ops.GAFFER_OT_remove_blacklisted.bl_idname, icon="REMOVE")


def draw_progress_bar(gaf_props, layout):
    if gaf_props.ShowProgress:
        layout.separator()
        b = layout.box()
        col = b.column(align=True)
        col.label(text=gaf_props.ProgressText)
        split = col.split(factor=max(0.01, gaf_props.Progress), align=True)
        r = split.row()
        r.alert = True
        r.prop(gaf_props, "ProgressBarText", text="")
        r = split.row()
        r.label(text="")
        c = b.column(align=True)
        c.label(text="Large HDRI files may take a while")
        c.label(text="You can stop this any time by closing Blender")
        layout.separator()


def draw_hdri_handler(context, layout, gaf_props, gaf_hdri_props, hdri_paths, prefs, icons, toolbar=False):

    def draw_filter_row(col, no_matches=False):
        row = col.row(align=True)
        row.operator(
            ops.GAFFER_OT_hdri_set_favorite.bl_idname,
            text="",
            icon="FUND" if gaf_hdri_props.hdri in fn.get_favorites() else "HEART",
        ).name = gaf_hdri_props.hdri
        row.prop(gaf_hdri_props, "hdri_favorite", text="", icon="FILTER")
        row.separator()
        if len(hdri_paths) > 1:
            row.menu(
                "GAFFER_MT_folder_filter", text="", icon="X" if gaf_hdri_props.hdri_folder_filter else "FILE_FOLDER"
            )
            row.separator()
        row.prop(gaf_hdri_props, "hdri_search", text="", expand=True, icon="VIEWZOOM")
        if gaf_hdri_props.hdri_search or no_matches:
            row.operator(ops.GAFFER_OT_hdri_clear_search.bl_idname, text="", icon="X")
            subrow = row.row(align=True)
            subrow.alignment = "RIGHT"
            subrow.label(text=str(len(fn.hdri_enum_previews(gaf_props, context))) + " matches")

    if gaf_hdri_props.hdri:
        col = layout.column(align=True)

        if not toolbar or "_Light:_(WorldEnviroLight)_" in gaf_props.MoreExpand or gaf_props.MoreExpandAll:
            draw_filter_row(col)

            col = layout.column(align=True)

            row = col.row(align=True)

            tmpc = row.column(align=True)
            tmpr = tmpc.column(align=True)
            tmpr.scale_y = 1
            tmpr.operator(ops.GAFFER_OT_hdri_save.bl_idname, text="", icon="FILE_TICK").hdri = gaf_hdri_props.hdri
            tmpcc = tmpc.column(align=True)
            tmpcc.scale_y = 9 if not toolbar else 3.5
            tmpcc.operator(ops.GAFFER_OT_hdri_paddles.bl_idname, text="", icon="TRIA_LEFT").do_next = False
            tmpr = tmpc.column(align=True)
            tmpr.scale_y = 1
            tmpr.operator(ops.GAFFER_OT_hdri_reset.bl_idname, text="", icon="FILE_REFRESH").hdri = gaf_hdri_props.hdri

            tmpc = row.column()
            tmpc.scale_y = 1 / (2 if toolbar else 1)
            tmpc.template_icon_view(gaf_hdri_props, "hdri", show_labels=True, scale=11)

            tmpc = row.column(align=True)
            tmpr = tmpc.column(align=True)
            tmpr.scale_y = 1
            tmpr.prop(
                gaf_hdri_props,
                "hdri_show_tags_ui",
                text="",
                toggle=True,
                icon_value=icons["tag"].icon_id,
            )
            tmpcc = tmpc.column(align=True)
            tmpcc.scale_y = 9 if not toolbar else 3.5
            tmpcc.operator(ops.GAFFER_OT_hdri_paddles.bl_idname, text="", icon="TRIA_RIGHT").do_next = True
            tmpr = tmpc.column(align=True)
            tmpr.scale_y = 1
            tmpr.operator(
                ops.GAFFER_OT_hdri_random.bl_idname,
                text="",
                icon_value=icons["random"].icon_id,
            )

            if gaf_hdri_props.hdri_show_tags_ui:
                col.separator()
                box = col.box()
                tags_col = box.column(align=True)
                tags_col.label(text="Choose some tags:")
                tags_col.separator()

                current_tags = fn.get_tags()
                if gaf_hdri_props.hdri in current_tags:
                    current_tags = current_tags[gaf_hdri_props.hdri]
                else:
                    current_tags = []

                i = 0
                for t in const.possible_tags:
                    if i % 4 == 0 or t == "##split##":  # Split tags into columns
                        row = tags_col.row(align=True)
                    if t != "##split##":

                        op = row.operator(
                            ops.GAFFER_OT_hdri_add_tag.bl_idname,
                            text=t.title(),
                            icon="CHECKBOX_HLT" if t in current_tags else "NONE",
                        )
                        op.hdri = gaf_hdri_props.hdri
                        op.tag = t
                        i += 1
                    else:
                        i = 0
                tags_col.prop(
                    gaf_hdri_props,
                    "hdri_custom_tags",
                    icon_value=icons["text-cursor"].icon_id,
                )
                tags_col.separator()
                tags_col.prop(gaf_hdri_props, "hdri_show_tags_ui", text="Done", toggle=True)
                col.separator()

            col = layout.column(align=True)

            if prefs.RequestThumbGen:
                row = col.row(align=True)
                row.alignment = "CENTER"
                row.operator(ops.GAFFER_OT_hdri_thumb_gen.bl_idname, icon="IMAGE")
                col.separator()

            row = col.row(align=True)
            vp_icon = "TRIA_LEFT" if gaf_hdri_props["hdri_variation"] != 0 else "TRIA_LEFT_BAR"
            row.operator(ops.GAFFER_OT_hdri_variation_paddles.bl_idname, text="", icon=vp_icon).do_next = False
            row.prop(gaf_hdri_props, "hdri_variation", text="")
            if const.hdri_haven_list and const.hdri_list:
                if gaf_hdri_props.hdri in const.hdri_haven_list and gaf_hdri_props.hdri in const.hdri_list:
                    if not any(("_16k" in h or "_8k" in h) for h in const.hdri_list[gaf_hdri_props.hdri]):
                        row.operator(ops.GAFFER_OT_open_hdrihaven.bl_idname, text="", icon="ADD").url = (
                            "https://polyhaven.com/a/" + gaf_hdri_props.hdri
                        )

            if gaf_hdri_props.hdri in const.hdri_list:  # Rare case of hdri_list not being initialized
                vp_icon = (
                    "TRIA_RIGHT"
                    if gaf_hdri_props["hdri_variation"] < len(const.hdri_list[gaf_hdri_props.hdri]) - 1
                    else "TRIA_RIGHT_BAR"
                )
            else:
                vp_icon = "TRIA_RIGHT"
            row.operator(ops.GAFFER_OT_hdri_variation_paddles.bl_idname, text="", icon=vp_icon).do_next = True
            col.separator()

            if gaf_props.FileNotFoundError:
                row = col.row(align=True)
                row.scale_y = 1.5
                row.alert = True
                row.alignment = "CENTER"
                row.label(text="File not found. Try refreshing your HDRI list:", icon="ERROR")
                row.operator(
                    ops.GAFFER_OT_detect_hdris.bl_idname,
                    text="Refresh",
                    icon="FILE_REFRESH",
                )

            col.separator()
        col.prop(gaf_hdri_props, "hdri_rotation", slider=True)
        col.separator()
        row = col.row(align=True)
        row.prop(gaf_hdri_props, "hdri_brightness", slider=True)
        if not toolbar or "_Light:_(WorldEnviroLight)_" in gaf_props.MoreExpand or gaf_props.MoreExpandAll:
            row.prop(gaf_hdri_props, "hdri_saturation", slider=True)
            row = col.row(align=True)
            row.prop(gaf_hdri_props, "hdri_contrast", slider=True)
            row.prop(gaf_hdri_props, "hdri_warmth", slider=True)

        wc = context.scene.world.cycles
        if context.scene.render.engine == "CYCLES" and (
            wc.sampling_method == "NONE" or (wc.sampling_method == "MANUAL" and wc.sample_map_resolution < 1000)
        ):
            col.separator()
            col.separator()
            if wc.sampling_method == "NONE":
                col.label(text="Importance sampling is disabled", icon="ERROR")
            else:
                col.label(text="Sampling resolution is low", icon="ERROR")
            row = col.row()
            row.alignment = "LEFT"
            row.label(text="Your renders may be noisy")
            row.operator(ops.GAFFER_OT_fix_mis.bl_idname)
            col.separator()

        if not toolbar:
            col.separator()
            col.separator()

            layout_panels_supported = bpy.app.version >= (4, 1, 0)
            if layout_panels_supported:
                header, panel = layout.panel("gaffer_advanced", default_closed=True)
                header.label(text="Advanced")
                if panel:
                    box = panel.column(align=True)
            else:
                box = col.box()
                col = box.column(align=True)
                row = col.row(align=True)
                row.alignment = "LEFT"
                row.prop(
                    gaf_hdri_props,
                    "hdri_advanced",
                    icon="TRIA_DOWN" if gaf_hdri_props.hdri_advanced else "TRIA_RIGHT",
                    emboss=False,
                    toggle=True,
                )
            if (gaf_hdri_props.hdri_advanced and not layout_panels_supported) or (layout_panels_supported and panel):
                col = box.column(align=True)
                split = col.split(factor=0.5)
                r = split.row()
                r.prop(gaf_hdri_props, "hdri_tint", slider=True)
                r = split.row(align=True)
                mix_node = fn.handler_node(context, "ShaderNodeMix", fetch_only=True)
                if mix_node:
                    r.prop(mix_node, "blend_type", text="")
                r.prop(gaf_hdri_props, "hdri_color", text="")
                col.separator()

                col.prop(gaf_hdri_props, "hdri_clamp", slider=True)
                split = col.split(factor=0.75, align=True)
                r = split.row(align=True)
                r.prop(gaf_hdri_props, "hdri_horz_shift", slider=True)
                r = split.row(align=True)
                r.prop(gaf_hdri_props, "hdri_horz_exp", slider=False)
                col.separator()

                col.label(text="Control background separately:")
                row = col.row(align=True)
                row.prop(gaf_hdri_props, "hdri_use_separate_rotation", toggle=True)
                sub = row.row(align=True)
                sub.active = gaf_hdri_props.hdri_use_separate_rotation
                sub.prop(gaf_hdri_props, "hdri_background_rotation", slider=True)
                row = col.row(align=True)
                row.prop(gaf_hdri_props, "hdri_use_separate_brightness", toggle=True)
                sub = row.row(align=True)
                sub.active = gaf_hdri_props.hdri_use_separate_brightness
                sub.prop(gaf_hdri_props, "hdri_background_brightness", slider=True)
                row = col.row(align=True)
                row.prop(gaf_hdri_props, "hdri_use_separate_contrast", toggle=True)
                sub = row.row(align=True)
                sub.active = gaf_hdri_props.hdri_use_separate_contrast
                sub.prop(gaf_hdri_props, "hdri_background_contrast", slider=True)
                row = col.row(align=True)
                row.prop(gaf_hdri_props, "hdri_use_separate_saturation", toggle=True)
                sub = row.row(align=True)
                sub.active = gaf_hdri_props.hdri_use_separate_saturation
                sub.prop(gaf_hdri_props, "hdri_background_saturation", slider=True)
                row = col.row(align=True)
                row.prop(gaf_hdri_props, "hdri_use_separate_warmth", toggle=True)
                sub = row.row(align=True)
                sub.active = gaf_hdri_props.hdri_use_separate_warmth
                sub.prop(gaf_hdri_props, "hdri_background_warmth", slider=True)
                row = col.row(align=True)
                row.prop(gaf_hdri_props, "hdri_use_separate_tint", toggle=True)
                sub = row.row(align=True)
                sub.active = gaf_hdri_props.hdri_use_separate_tint
                sub.prop(gaf_hdri_props, "hdri_background_tint", slider=True)
                split = col.split(factor=0.5, align=True)
                r = split.row(align=True)
                r.prop(gaf_hdri_props, "hdri_use_separate_color", toggle=True)
                r = split.row(align=True)
                r.active = gaf_hdri_props.hdri_use_separate_color
                mix_node_bg = fn.handler_node(context, "ShaderNodeMix", background=True, fetch_only=True)
                if mix_node_bg:
                    r.prop(mix_node_bg, "blend_type", text="")
                elif mix_node:
                    r.prop(mix_node, "blend_type", text="")
                r.prop(gaf_hdri_props, "hdri_background_color", text="")

                col.separator()
                sub = col.row(align=True)
                sub.active = any(
                    [
                        gaf_hdri_props.hdri_use_jpg_background,
                        gaf_hdri_props.hdri_use_separate_rotation,
                        gaf_hdri_props.hdri_use_separate_brightness,
                        gaf_hdri_props.hdri_use_separate_contrast,
                        gaf_hdri_props.hdri_use_separate_saturation,
                        gaf_hdri_props.hdri_use_separate_warmth,
                        gaf_hdri_props.hdri_use_separate_tint,
                        gaf_hdri_props.hdri_use_separate_color,
                    ]
                )
                sub.prop(gaf_hdri_props, "hdri_use_bg_reflections")

                col.separator()
                row = col.row(align=True)
                row.prop(gaf_hdri_props, "hdri_use_jpg_background")
                sub = row.row(align=True)
                sub.active = gaf_hdri_props.hdri_use_jpg_background
                sub.prop(gaf_hdri_props, "hdri_use_darkened_jpg")
                if (
                    gaf_hdri_props.hdri_use_jpg_background and gaf_hdri_props.hdri_use_bg_reflections
                ) and not gaf_hdri_props.hdri_use_darkened_jpg:
                    col.label(text="Enabling 'Pre-Darkened' is recommended to")
                    col.label(text="get more accurate reflections.")
                if gaf_props.RequestJPGGen and gaf_hdri_props.hdri_use_jpg_background:
                    col.separator()
                    col.separator()
                    col.label(text="No JPGs have been created yet,", icon="ERROR")
                    col.label(text="please click 'Generate JPGs' below.")
                    col.label(text="Note: This may take a while for high-res images")
                    col.operator(ops.GAFFER_OT_hdri_jpg_gen.bl_idname)
                    col.prop(gaf_hdri_props, "hdri_jpg_gen_all")
                    if gaf_hdri_props.hdri_jpg_gen_all:
                        col.label(text="This is REALLY going to take a while.")
                        col.label(text="See the console for progress.")
                    col.separator()
    elif gaf_hdri_props.hdri_search or gaf_hdri_props.hdri_favorite or gaf_hdri_props.hdri_folder_filter:
        prefs.ForcePreviewsRefresh = True
        draw_filter_row(layout, no_matches=True)
    else:
        prefs.ForcePreviewsRefresh = True
        row = layout.row()
        row.alignment = "CENTER"
        row.label(text="No HDRIs found")
        row = layout.row()
        row.alignment = "CENTER"
        row.label(text="Please put some in the HDRI folder:")


class GAFFER_PT_hdris(bpy.types.Panel):

    bl_label = " "
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "world"

    @classmethod
    def poll(cls, context):
        return context.scene.render.engine in ["CYCLES", "BLENDER_EEVEE"] and context.scene.world

    def draw_header(self, context):
        gaf_hdri_props = context.scene.world.gaf_hdri_props

        layout = self.layout
        row = layout.row(align=True)
        row.prop(gaf_hdri_props, "hdri_handler_enabled", text="")
        if gaf_hdri_props.hdri and gaf_hdri_props.hdri_handler_enabled:
            row.label(text="HDRI: " + fn.nice_hdri_name(gaf_hdri_props.hdri))
        else:
            row.label(text="HDRI")

    def draw(self, context):
        gaf_props = context.scene.gaf_props
        gaf_hdri_props = context.scene.world.gaf_hdri_props
        prefs = context.preferences.addons[__package__].preferences
        icons = fn.get_icons()

        layout = self.layout

        draw_progress_bar(gaf_props, layout)

        col = layout.column()
        draw_trial(col)
        hdri_paths = fn.get_persistent_setting("hdri_paths")
        if not os.path.exists(hdri_paths[0]):
            row = col.row()
            row.alignment = "CENTER"
            row.label(text="Select a folder in the Add-on User Preferences")
            row = col.row()
            row.alignment = "CENTER"
            row.label(text="Preferences > Add-ons > Gaffer > HDRI Folder")
        else:
            if gaf_hdri_props.hdri_handler_enabled:
                draw_hdri_handler(context, col, gaf_props, gaf_hdri_props, hdri_paths, prefs, icons)

                if gaf_props.ShowHDRIHaven:
                    layout.separator()
                    row = layout.row(align=True)
                    row.alignment = "CENTER"
                    row.scale_y = 1.5
                    row.scale_x = 1.5
                    row.operator(
                        ops.GAFFER_OT_get_hdrihaven.bl_idname,
                        icon_value=icons["hdri_haven"].icon_id,
                    )
                    row.operator(ops.GAFFER_OT_hide_hdrihaven.bl_idname, text="", icon="X")
            else:
                col = layout.column()
                row = col.row()
                row.alignment = "CENTER"
                row.label(text="Gaffer's HDRI handler is disabled.")
                row = col.row()
                row.alignment = "CENTER"
                row.label(text="Enable it with the checkbox in this panel's header")


class OBJECT_UL_object_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        obj = item
        layout.prop(obj, "name", text="", emboss=False)


class GAFFER_MT_folder_filter(bpy.types.Menu):
    bl_label = "Folder Filter"
    bl_description = "Show only HDRIs from this subfolder"

    def draw(self, context):
        gaf_hdri_props = context.scene.world.gaf_hdri_props
        col = self.layout.column()

        if gaf_hdri_props.hdri_folder_filter:
            col.operator(
                ops.GAFFER_OT_hdri_set_folder_filter.bl_idname,
                text="Remove Filter",
                icon="X",
            ).folder = ""

        hdri_paths = fn.get_persistent_setting("hdri_paths")
        for path in hdri_paths:
            col.operator(ops.GAFFER_OT_hdri_set_folder_filter.bl_idname, text=path, icon="FILE_FOLDER").folder = path
            # Subfolders
            for subfolder in os.listdir(path):
                if os.path.isdir(os.path.join(path, subfolder)):
                    col.operator(
                        ops.GAFFER_OT_hdri_set_folder_filter.bl_idname,
                        text=subfolder,
                        icon="DOT",
                    ).folder = os.path.join(path, subfolder)


def gaffer_node_menu_func(self, context):
    if context.space_data.node_tree.type == "SHADER" and context.space_data.shader_type == "OBJECT":
        light_dict = fn.dictOfLights()
        if context.object.name in light_dict:
            layout = self.layout
            layout.operator(ops.GAFFER_OT_node_set_strength.bl_idname)
