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
import json
from gpu_extras.batch import batch_for_shader
import os
import math
import time
import datetime
from collections import OrderedDict
from mathutils import Vector, Euler
from bpy.app.handlers import persistent

from . import constants as const

TAG_REFRESH_LIGHT_LIST = False


# Persistent settings functions


def init_persistent_settings(set_name=None, set_value=None):
    """Initialize persistent settings file with option to change a default value"""

    settings = {}

    # Some settings might already exist
    if os.path.exists(const.settings_file):
        with open(const.settings_file) as f:
            try:
                settings = json.load(f)
            except json.JSONDecodeError:
                settings = {}

    # First time use in 2.8, copy path from 2.7
    if "hdri_paths" not in settings and "hdri_path" in settings:
        settings["hdri_paths"] = [settings["hdri_path"]]

    defaults = {"show_hdri_haven": True, "hdri_path": "", "hdri_paths": [""]}  # Legacy
    for d in defaults:
        if d not in settings:
            settings[d] = defaults[d]

    if set_name is not None:
        settings[set_name] = set_value

    with open(const.settings_file, "w") as f:
        f.write(json.dumps(settings, indent=4))

    return settings


def get_persistent_setting(name):
    if os.path.exists(const.settings_file):
        with open(const.settings_file) as f:
            try:
                settings = json.load(f)
            except json.JSONDecodeError:
                settings = {}
        if name in settings:
            return settings[name]

    initial_settings = init_persistent_settings()
    return initial_settings[name] if name in initial_settings else None


def set_persistent_setting(name, value):
    if not os.path.exists(const.settings_file):
        init_persistent_settings(name, value)
    else:
        with open(const.settings_file) as f:
            settings = json.load(f)
        settings[name] = value
        with open(const.settings_file, "w") as f:
            f.write(json.dumps(settings, indent=4))


# Utils


def log(text, timestamp=True, also_print=False):
    ts = datetime.datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S")

    with open(const.log_file, "a") as f:
        if also_print:
            print(text)
        if timestamp:
            f.write(ts + "    " + text + "\n")
        else:
            f.write(" " * len(ts) + "    " + text + "\n")


def cleanup_logs():
    """Delete log lines that are older than 1 week to keep the file size down"""
    if os.path.exists(const.log_file):
        with open(const.log_file, "r") as f:
            lines = f.readlines()

        i = 0  # Where the most recent line is that's older than 7 days
        for ln_no, l in enumerate(lines):
            try:
                d = datetime.datetime.strptime(l[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
            else:
                age = time.time() - time.mktime(d.timetuple())
                if age / 60 / 60 / 24 > 7:
                    i = ln_no
                else:
                    break
        if i > 0:
            new_lines = lines[i + 1 :]
            with open(const.log_file, "w") as f:
                f.writelines(new_lines)


def hastebin_file(filepath, extra_string=""):
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            lines = f.read()
        from requests import post as requests_post

        r = requests_post("https://hastebin.com/documents", lines + "\n" * 4 + extra_string)
        url = "https://hastebin.com/" + json.loads(r.content.decode())["key"]
        bpy.ops.wm.url_open(url=url)


def dpifac():
    prefs = bpy.context.preferences.system
    # python access to this was only added recently, assume non-retina display is used if using older blender
    if hasattr(prefs, "pixel_size"):
        retinafac = bpy.context.preferences.system.pixel_size
    else:
        retinafac = 1
    return bpy.context.preferences.system.dpi / (72 / retinafac)


def time_execution(func):
    """Decorator to log execution time of a function if it takes longer than 100 ms"""

    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_time = (end_time - start_time) * 1000  # in milliseconds
        if execution_time > 100:
            log(f"Function '{func.__name__}' took {execution_time:.2f} ms")
        return result

    return wrapper


# Light list functions


@time_execution
def refresh_light_list(scene):
    def get_next_available_value_socket(node):
        current_node = node
        found_node = node.name
        found_socket = -1
        i = 0
        max_iterations = 1000  # Prevent infinite loop
        while found_socket == -1:
            i += 1
            if i == max_iterations:
                print("Gaffer Warning: Max iterations hit in get_next_available_value_socket for " + node.name)
                break
            if len(current_node.inputs) == 0:
                # End of the line.
                break

            for si, s in enumerate(current_node.inputs):
                if s.type == "VALUE":
                    if not s.is_linked:
                        found_node = current_node.name
                        found_socket = si
                        break
                    else:
                        current_node = s.links[0].from_node
        return found_node, found_socket

    global TAG_REFRESH_LIGHT_LIST
    TAG_REFRESH_LIGHT_LIST = False

    detected_lights = []

    if not hasattr(bpy.types.Object, "GafferFalloff"):
        bpy.types.Object.GafferFalloff = bpy.props.EnumProperty(
            name="Light Falloff",
            items=(
                ("constant", "Constant", "No light falloff", "IPO_CONSTANT", 1),
                (
                    "linear",
                    "Linear",
                    "Fade light strength linearly over the distance it travels",
                    "IPO_LINEAR",
                    2,
                ),
                (
                    "quadratic",
                    "Quadratic",
                    "(Realisic) Light strength is inversely proportional to the square of the distance it travels",
                    "IPO_QUAD",
                    3,
                ),
            ),
            default="quadratic",
            description="The rate at which the light loses intensity over distance",
            update=_update_falloff,
        )

    light_dict = dictOfLights()

    objects = sorted(scene.objects, key=lambda x: x.name)

    if scene.render.engine in ["CYCLES", "BLENDER_EEVEE"]:
        for obj in objects:
            light_mats = []
            if obj.type == "LIGHT":
                if obj.data.use_nodes:
                    invalid_node = False
                    if obj.name in light_dict:
                        if light_dict[obj.name] == "None":  # Previously did not use nodes (like default light)
                            invalid_node = True
                        elif light_dict[obj.name] not in obj.data.node_tree.nodes:
                            invalid_node = True
                    if obj.name not in light_dict or invalid_node:
                        for node in obj.data.node_tree.nodes:
                            if node.name != "Emission Viewer":
                                if node.type == "EMISSION":
                                    if node.outputs[0].is_linked:
                                        (
                                            node_name,
                                            socket_index,
                                        ) = get_next_available_value_socket(node)
                                        detected_lights.append(
                                            [
                                                obj.name,
                                                None,
                                                node_name,
                                                "i" + str(socket_index),
                                            ]
                                        )
                                        break
                    else:
                        node = obj.data.node_tree.nodes[light_dict[obj.name]]
                        if node.inputs:
                            node_name, socket_index = get_next_available_value_socket(node)
                            detected_lights.append([obj.name, None, node_name, "i" + str(socket_index)])
                        elif node.outputs:
                            socket_index = 0
                            for oupt in node.outputs:
                                if oupt.type == "VALUE":  # use first Value socket as strength
                                    detected_lights.append(
                                        [
                                            obj.name,
                                            None,
                                            node.name,
                                            "o" + str(socket_index),
                                        ]
                                    )
                                    break
                                socket_index += 1
                else:
                    detected_lights.append([obj.name, None, None])
            elif obj.type == "MESH" and len(obj.material_slots) > 0 and scene.render.engine == "CYCLES":
                slot_break = False
                for slot in obj.material_slots:
                    if slot_break:
                        break  # only use first emission material in slots
                    if slot.material:
                        if slot.material not in light_mats:
                            if slot.material.use_nodes:
                                invalid_node = False
                                if obj.name in light_dict:
                                    if light_dict[obj.name] == "None":  # Previously did not use nodes
                                        invalid_node = True
                                    elif light_dict[obj.name] not in slot.material.node_tree.nodes:
                                        invalid_node = True
                                if obj.name not in light_dict or invalid_node:
                                    for node in slot.material.node_tree.nodes:
                                        if node.name != "Emission Viewer":
                                            if node.type == "EMISSION":
                                                if node.outputs[0].is_linked:
                                                    (
                                                        node_name,
                                                        socket_index,
                                                    ) = get_next_available_value_socket(node)
                                                    detected_lights.append(
                                                        [
                                                            obj.name,
                                                            slot.material.name,
                                                            node_name,
                                                            "i" + str(socket_index),
                                                        ]
                                                    )
                                                    light_mats.append(slot.material)  # Skip this material next time
                                                    slot_break = True
                                                    break
                                else:
                                    node = slot.material.node_tree.nodes[light_dict[obj.name]]
                                    if node.inputs:
                                        (
                                            node_name,
                                            socket_index,
                                        ) = get_next_available_value_socket(node)
                                        detected_lights.append(
                                            [
                                                obj.name,
                                                slot.material.name,
                                                node_name,
                                                "i" + str(socket_index),
                                            ]
                                        )
                                    elif node.outputs:
                                        socket_index = 0
                                        for oupt in node.outputs:
                                            if oupt.type == "VALUE":  # use first Value socket as strength
                                                detected_lights.append(
                                                    [
                                                        obj.name,
                                                        slot.material.name,
                                                        node.name,
                                                        "o" + str(socket_index),
                                                    ]
                                                )
                                                break
                                            socket_index += 1
    else:  # Unsupported engines
        for obj in objects:
            if obj.type == "LIGHT":
                detected_lights.append([obj.name, None, None])

    for light in detected_lights:
        obj = bpy.data.objects[light[0]]
        nodes = None
        if obj.type == "LIGHT":
            if obj.data.use_nodes:
                nodes = obj.data.node_tree.nodes
        else:
            if bpy.data.materials[light[1]].use_nodes:
                nodes = bpy.data.materials[light[1]].node_tree.nodes
        if nodes:
            if light[2]:
                if nodes[light[2]].type != "LIGHT_FALLOFF" and bpy.data.objects[light[0]].GafferFalloff != "quadratic":
                    bpy.data.objects[light[0]].GafferFalloff = "quadratic"
    scene.gaf_props.Lights = str(detected_lights)

    if scene.gaf_props.SoloActive == "":
        getHiddenStatus(scene, stringToNestedList(scene.gaf_props.Lights, True))
    if bpy.context.area:
        refresh_bgl()  # update the radius/label as well


def force_update(context, obj=None):
    if not obj:
        context.space_data.node_tree.update_tag()
    else:
        obj.data.node_tree.update_tag()


def stringToList(str="", stripquotes=False):
    raw = str.split(", ")
    raw[0] = (raw[0])[1:]
    raw[-1] = (raw[-1])[:-1]
    if stripquotes:
        tmplist = []
        for item in raw:
            tmpvar = item
            if tmpvar.startswith("'"):
                item = tmpvar[1:-1]
            tmplist.append(item)
        raw = tmplist
    return raw


def stringToNestedList(str="", stripquotes=False):
    raw = str.split("], ")
    raw[0] = (raw[0])[1:]
    raw[-1] = (raw[-1])[:-2]
    i = 0
    for item in raw:
        raw[i] += "]"
        i += 1
    newraw = []
    for item in raw:
        newraw.append(stringToList(item, stripquotes))
    return newraw


def castBool(str):
    if str == "True":
        return True
    else:
        return False


# Color functions


def setColTemp(node, temp):
    node.inputs[0].default_value = temp


def convert_temp_to_RGB(colour_temperature):
    """
    Converts from K to RGB, algorithm courtesy of
    http://www.tannerhelland.com/4435/convert-temperature-rgb-algorithm-code/
    Python implementation by petrklus: https://gist.github.com/petrklus/b1f427accdf7438606a6
    """

    # limits: 0 -> 12000
    if colour_temperature < 1:
        colour_temperature = 1
    elif colour_temperature > 12000:
        colour_temperature = 12000

    tmp_internal = colour_temperature / 100.0

    # red
    if tmp_internal <= 66:
        red = 255
    else:
        tmp_red = 329.698727446 * pow(tmp_internal - 60, -0.1332047592)
        if tmp_red < 0:
            red = 0
        elif tmp_red > 255:
            red = 255
        else:
            red = tmp_red

    # green
    if tmp_internal <= 66:
        tmp_green = 99.4708025861 * math.log(tmp_internal) - 161.1195681661
        if tmp_green < 0:
            green = 0
        elif tmp_green > 255:
            green = 255
        else:
            green = tmp_green
    else:
        tmp_green = 288.1221695283 * pow(tmp_internal - 60, -0.0755148492)
        if tmp_green < 0:
            green = 0
        elif tmp_green > 255:
            green = 255
        else:
            green = tmp_green

    # blue
    if tmp_internal >= 66:
        blue = 255
    elif tmp_internal <= 19:
        blue = 0
    else:
        tmp_blue = 138.5177312231 * math.log(tmp_internal - 10) - 305.0447927307
        if tmp_blue < 0:
            blue = 0
        elif tmp_blue > 255:
            blue = 255
        else:
            blue = tmp_blue

    return [red / 255, green / 255, blue / 255]  # return RGB in a 0-1 range


def convert_wavelength_to_RGB(wavelength):
    # normalize wavelength into a number between 0 and 80 and use it as the index for the list
    return const.wavelength_list[min(80, max(0, int((wavelength - 380) * 0.2)))]


# Visibility functions


def getHiddenStatus(scene, lights):
    statelist = []
    temparr = []
    for light in lights:
        if light[0]:
            temparr = [
                light[0],
                bpy.data.objects[light[0]].hide_viewport,
                bpy.data.objects[light[0]].hide_render,
            ]
            statelist.append(temparr)

    temparr = [
        "WorldEnviroLight",
        scene.gaf_props.WorldVis,
        scene.gaf_props.WorldReflOnly,
    ]
    statelist.append(temparr)

    scene.gaf_props.LightsHiddenRecord = str(statelist)


def visibleCollections():
    def check_child(c, vis_cols):
        if c.is_visible:
            vis_cols.append(c.collection)
            for sc in c.children:
                vis_cols = check_child(sc, vis_cols)
        return vis_cols

    vis_cols = [bpy.context.scene.collection]

    for c in bpy.context.window.view_layer.layer_collection.children:
        check_child(c, vis_cols)

    return vis_cols


def isInVisibleCollection(obj, vis_cols):
    for oc in obj.users_collection:
        if oc in vis_cols:
            return True
    return False


# Misc functions


def dictOfLights():
    # Create dict of light name as key with node name as value
    lights = stringToNestedList(bpy.context.scene.gaf_props.Lights, stripquotes=True)
    lights_with_nodes = []
    light_dict = {}
    if lights:
        for light in lights:  # TODO check if node still exists
            if len(light) > 1:
                lights_with_nodes.append(light[0])
                lights_with_nodes.append(light[2])
        light_dict = dict(lights_with_nodes[i : i + 2] for i in range(0, len(lights_with_nodes), 2))
    return light_dict


def setGafferNode(context, nodetype, tree=None, obj=None):
    if nodetype == "STRENGTH":
        list_nodeindex = 2
        list_socketindex = 3
    elif nodetype == "COLOR":
        list_nodeindex = 4
        list_socketindex = 5

    if tree:
        nodetree = tree
    else:
        nodetree = context.space_data.node_tree
    node = nodetree.nodes.active
    lights = stringToNestedList(context.scene.gaf_props.Lights, stripquotes=True)

    if obj is None:
        obj = context.object
    for light in lights:
        # TODO poll for pinned nodetree (active object is not necessarily the one that this tree belongs to)
        if light[0] == obj.name:
            light[list_nodeindex] = node.name
            socket_index = 0

            if node.inputs:
                for socket in node.inputs:
                    if socket.type == "VALUE" and not socket.is_linked:  # use first Value socket as strength
                        light[list_socketindex] = "i" + str(socket_index)
                        break
                    socket_index += 1
                break
            elif node.outputs:
                for socket in node.outputs:
                    if socket.type == "VALUE":  # use first Value socket as strength
                        light[list_socketindex] = "o" + str(socket_index)
                        break
                    socket_index += 1
                break
    # TODO catch if there is no available socket to use
    context.scene.gaf_props.Lights = str(lights)


def do_update_falloff(self):
    light = self
    scene = bpy.context.scene
    lights = stringToNestedList(scene.gaf_props.Lights, stripquotes=True)
    lightitems = []
    for l in lights:
        if l[0] == light.name:
            lightitems = l
            break

    socket_no = 2
    falloff = light.GafferFalloff
    if falloff == "linear":
        socket_no = 1
    elif falloff == "quadratic":
        socket_no = 0

    connections = []
    if light.type == "LIGHT":
        tree = light.data.node_tree
    else:
        tree = bpy.data.materials[lightitems[1]].node_tree

    try:
        node = tree.nodes[lightitems[2]]
        if node.type == "LIGHT_FALLOFF":
            for outpt in node.outputs:
                if outpt.is_linked:
                    for link in outpt.links:
                        connections.append(link.to_socket)
            for link in connections:
                tree.links.new(node.outputs[socket_no], link)
        else:
            if light.GafferFalloff != "quadratic":
                fnode = tree.nodes.new("ShaderNodeLightFalloff")
                fnode.inputs[0].default_value = node.inputs[int(str(lightitems[3])[-1])].default_value
                fnode.location.x = node.location.x - 250
                fnode.location.y = node.location.y
                tree.links.new(fnode.outputs[socket_no], node.inputs[int(str(lightitems[3])[-1])])
                tree.nodes.active = fnode
                setGafferNode(bpy.context, "STRENGTH", tree, light)
        force_update(bpy.context, light)
    except (KeyError, IndexError, AttributeError):
        print("Warning: do_update_falloff failed, node may not exist anymore")


def _update_falloff(self, context):
    do_update_falloff(self)


def tag_refresh_light_list():
    global TAG_REFRESH_LIGHT_LIST
    TAG_REFRESH_LIGHT_LIST = True


def depsgraph_update_includes_all(depsgraph, types):
    for id_type in types:
        if not depsgraph.id_type_updated(id_type):
            return False
    return True


@persistent
def depsgraph_update_post_handler(scene, depsgraph):

    # Debug mode to see what depsgraph updates are happening
    if bpy.app.debug_value == 666:
        types_updated = [id_type for id_type in const.depsgraph_id_types if depsgraph.id_type_updated(id_type)]
        print("Updated types:", types_updated)
        for update in depsgraph.updates:
            print(
                "  Update:",
                update.id,
                update.is_updated_geometry,
                update.is_updated_transform,
                update.is_updated_shading,
            )

    prefs = bpy.context.preferences.addons[__package__].preferences
    if prefs.auto_refresh_light_list:
        # A light has been added
        if depsgraph_update_includes_all(depsgraph, ["COLLECTION", "LIGHT", "OBJECT", "SCENE"]):
            log("Gaffer light list auto-refresh triggered by depsgraph update", also_print=True)
            refresh_light_list(scene)
            return

        # A UI draw function has requested a refresh, usually when a light is deleted
        global TAG_REFRESH_LIGHT_LIST
        if TAG_REFRESH_LIGHT_LIST:
            TAG_REFRESH_LIGHT_LIST = False
            log("Gaffer light list auto-refresh triggered by TAG_REFRESH_LIGHT_LIST", also_print=True)
            refresh_light_list(scene)

        # Light has been renamed
        if (
            depsgraph.id_type_updated("OBJECT")
            and len(depsgraph.updates) == 1
            and not depsgraph.updates[0].is_updated_transform
            and not depsgraph.id_type_updated("SCENE")
        ):
            lights_str = scene.gaf_props.Lights
            lights = stringToNestedList(lights_str)
            all_objects = {obj.name for obj in bpy.data.objects}
            if any(light[0][1:-1] not in all_objects for light in lights):
                log("Gaffer light list auto-refresh triggered by light rename", also_print=True)
                refresh_light_list(scene)
                return

    # Keep background mix node blend mode in sync when it should be.
    if depsgraph_update_includes_all(depsgraph, ["WORLD", "NODETREE"]):
        gaf_hdri_props = scene.world.gaf_hdri_props
        context = bpy.context
        extra_nodes = any(
            [
                gaf_hdri_props.hdri_use_jpg_background,
                gaf_hdri_props.hdri_use_separate_brightness,
                gaf_hdri_props.hdri_use_separate_contrast,
                gaf_hdri_props.hdri_use_separate_saturation,
                gaf_hdri_props.hdri_use_separate_warmth,
                gaf_hdri_props.hdri_use_separate_tint,
                gaf_hdri_props.hdri_use_separate_color,
            ]
        )
        if not gaf_hdri_props.hdri_use_separate_color and extra_nodes:
            n = handler_node(context, "ShaderNodeMix", fetch_only=True)
            bn = handler_node(context, "ShaderNodeMix", background=True, fetch_only=True)
            if n and bn and n.blend_type != bn.blend_type:
                bn.blend_type = n.blend_type


# World vis functions


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
    world = scene.world
    if scene.gaf_props.WorldVis:
        # Show
        try:
            previous_state = json.loads(scene.gaf_props.WorldHiddenRecord)
        except json.JSONDecodeError:
            pass  # No previous state
        else:
            world.cycles_visibility.glossy = previous_state[0]
            world.cycles_visibility.camera = previous_state[1]
            world.cycles_visibility.diffuse = previous_state[2]
            world.cycles_visibility.transmission = previous_state[3]
            world.cycles_visibility.scatter = previous_state[4]
    else:
        # Hide
        current_state = json.dumps(
            [
                world.cycles_visibility.glossy,
                world.cycles_visibility.camera,
                world.cycles_visibility.diffuse,
                world.cycles_visibility.transmission,
                world.cycles_visibility.scatter,
            ]
        )
        scene.gaf_props.WorldHiddenRecord = current_state
        world.cycles_visibility.glossy = False
        world.cycles_visibility.camera = False
        world.cycles_visibility.diffuse = False
        world.cycles_visibility.transmission = False
        world.cycles_visibility.scatter = False
    world.update_tag()


def _update_world_vis(self, context):
    do_set_world_vis(context)


# Drawing functions


def refresh_bgl():
    if bpy.context.scene.gaf_props.IsShowingRadius:
        bpy.ops.gaffer.show_radius("INVOKE_DEFAULT")
        bpy.ops.gaffer.show_radius("INVOKE_DEFAULT")
    if bpy.context.scene.gaf_props.IsShowingLabel:
        bpy.ops.gaffer.show_label("INVOKE_DEFAULT")
        bpy.ops.gaffer.show_label("INVOKE_DEFAULT")


def draw_rect(shader, x1, y1, x2, y2):
    verts = ((x1, y1), (x1, y2), (x2, y1), (x2, y2))
    indices = ((0, 1, 2), (1, 2, 3))
    batch = batch_for_shader(shader, "TRIS", {"pos": verts}, indices=indices)
    batch.draw(shader)


def draw_corner(shader, x, y, r, corner):
    sides = 16
    if corner == "BL":
        r1 = 8
        r2 = 12
    elif corner == "TL":
        r1 = 4
        r2 = 8
    elif corner == "BR":
        r1 = 12
        r2 = 16
    elif corner == "TR":
        r1 = 0
        r2 = 4

    verts = [(x, y)]
    for i in range(r1, r2 + 1):
        cosine = r * math.cos(i * 2 * math.pi / sides) + x
        sine = r * math.sin(i * 2 * math.pi / sides) + y
        verts.append((cosine, sine))

    indices = []
    for i in range(r2 - r1):
        indices.append((0, i + 1, i + 2))

    batch = batch_for_shader(shader, "TRIS", {"pos": verts}, indices=indices)
    batch.draw(shader)


def draw_rounded_rect(shader, x1, y1, x2, y2, r):
    draw_rect(shader, x1, y1, x2, y2)  # Main quad
    draw_rect(shader, x1 - r, y1, x1, y2)  # Left edge
    draw_rect(shader, x2, y1, x2 + r, y2)  # Right edge
    draw_rect(shader, x1, y2, x2, y2 + r)  # Top edge
    draw_rect(shader, x1, y1 - r, x2, y1)  # Bottom edge

    draw_corner(shader, x1, y1, r, "BL")  # Bottom left
    draw_corner(shader, x1, y2, r, "TL")  # Top left
    draw_corner(shader, x2, y2, r, "TR")  # Top right
    draw_corner(shader, x2, y1, r, "BR")  # Bottom right


# HDRI functions


def update_hdri_path(self, context):
    hdri_paths = get_persistent_setting("hdri_paths")
    for i, hp in enumerate(hdri_paths):
        if hp.startswith("//"):
            hdri_paths[i] = os.path.abspath(bpy.path.abspath(hp))
            # For some reason bpy.path.abspath often still includes some
            # relativeness, such as "C:/path/../real_path/to/file.jpg"
            # So running os.path.abspath(bpy.path.abspath) should resolve
            # to "C:/real_path/to/file.jpg"

    detect_hdris(self, context)
    get_hdri_haven_list(force_update=True)


def get_hdri_basename(f):
    separators = ["_", "-", ".", " "]
    fn, ext = os.path.splitext(f)
    sep = ""
    for c in fn[::-1][:-1]:  # Reversed filename to see which separator is last
        if c in separators:
            sep = c
            break
    if sep != "":
        # Remove all character after the separator - what's left is the hdri name without resolution etc.
        hdri_name = sep.join(fn.split(sep)[:-1])
    else:
        hdri_name = fn
    return hdri_name


def polyhaven_asset_lib(context):
    """Get the Poly Haven asset library path if it exists"""

    for l in context.preferences.filepaths.asset_libraries:
        if l.name.lower() == "poly haven":
            return l.path

    return None


def paths_are_equal(p1, p2):
    """Check if two paths are equal, regardless of case or slashes"""
    if p1 is None or p2 is None:
        return False
    return os.path.normcase(os.path.normpath(p1)) == os.path.normcase(os.path.normpath(p2))


def path_contains(parent, child):
    """Check if parent contains child, regardless of case or slashes"""
    return os.path.normcase(os.path.normpath(child)).startswith(os.path.normcase(os.path.normpath(parent)))


def detect_hdris(self, context):

    log("FN: Detect HDRIs")

    show_hdrihaven()

    hdris = {}

    def check_folder_for_HDRIs(path, is_polyhaven_asset_lib=False):
        prefs = bpy.context.preferences.addons[__package__].preferences

        l_allowed_file_types = const.allowed_file_types
        if not prefs.include_8bit:
            l_allowed_file_types = const.hdr_file_types

        if os.path.exists(path):
            files = []
            for f in os.listdir(path):
                if os.path.isfile(os.path.join(path, f)):
                    fn, ext = os.path.splitext(f)
                    if not any([fn.lower().endswith(b) for b in const.thumb_endings]):
                        if ext.lower() in l_allowed_file_types and not fn.startswith("."):
                            files.append(f)
                else:
                    if is_polyhaven_asset_lib and f == "textures":
                        continue  # Don't detect exr textures as HDRIs in Poly Haven asset library
                    if f != "_MACOSX":
                        check_folder_for_HDRIs(os.path.join(path, f), is_polyhaven_asset_lib)

            hdri_file_pairs = []
            for f in files:
                hdri_name = get_hdri_basename(f)
                hdri_file_pairs.append([hdri_name, os.path.join(path, f)])

            for h in hdri_file_pairs:
                if h[0] in hdris:
                    hdris[h[0]].append(h[1])
                else:
                    hdris[h[0]] = [h[1]]

    hdri_paths = get_persistent_setting("hdri_paths")
    if hdri_paths[0] != "":
        for hp in hdri_paths:
            if not os.path.exists(hp):
                continue
            check_folder_for_HDRIs(hp, paths_are_equal(polyhaven_asset_lib(context), hp))

        # Sort variations by filesize
        for h in hdris:
            hdris[h] = sorted(hdris[h], key=lambda x: os.path.getsize(x))

        # Sort HDRI list alphabetically
        hdris = OrderedDict(sorted(hdris.items(), key=lambda x: x[0].lower()))

        with open(const.hdri_list_path, "w") as f:
            f.write(json.dumps(hdris, indent=4))

        const.hdri_list = hdris
        if "hdri" in context.scene.world.gaf_hdri_props:
            if context.scene.world.gaf_hdri_props["hdri"] >= len(const.hdri_list):
                context.scene.world.gaf_hdri_props["hdri"] = 0
        refresh_previews()
        prefs = bpy.context.preferences.addons[__package__].preferences
        prefs.ForcePreviewsRefresh = True
        switch_hdri(self, context)


def get_hdri_list(use_search=False):
    if os.path.exists(const.hdri_list_path):
        with open(const.hdri_list_path) as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
        if data:
            data = OrderedDict(sorted(data.items(), key=lambda x: x[0].lower()))

            if use_search:
                gaf_hdri_props = bpy.context.scene.world.gaf_hdri_props
                if gaf_hdri_props.hdri_favorite:
                    new_data = {name: value for name, value in data.items() if name in get_favorites()}
                    data = new_data
                if gaf_hdri_props.hdri_folder_filter:
                    new_data = {
                        name: value
                        for name, value in data.items()
                        if path_contains(gaf_hdri_props.hdri_folder_filter, value[0])
                    }
                    data = new_data
                search_string = gaf_hdri_props.hdri_search
                if search_string:
                    search_string = search_string.replace(",", " ").replace(";", " ")
                    search_terms = search_string.split(" ")
                    tags = get_tags()

                    matched_data = {}

                    for name in data:
                        matchables = [name]
                        sub_folder = data[name][0].split(name)[0]
                        matchables += sub_folder.split("\\" if "\\" in sub_folder else "/")
                        if name in tags:
                            matchables += tags[name]

                        num_matched = 0
                        for s in search_terms:
                            for m in matchables:
                                if s.lower().strip() in m.lower():
                                    num_matched += 1
                                    break

                        if num_matched == len(search_terms) or not search_terms:
                            matched_data[name] = data[name]

                    return OrderedDict(sorted(matched_data.items(), key=lambda x: x[0].lower()))
                else:
                    return data
            else:
                return data
        else:
            return {}
    else:
        return {}


if len(const.hdri_list) < 1:
    const.hdri_list = get_hdri_list()


def get_variation(hdri, mode=None, var=None):
    if hdri == "":
        return

    variations = const.hdri_list[hdri]
    if mode == "smallest":
        return variations[0]
    elif mode == "biggest":
        return variations[-1]
    elif var:
        return var
    else:
        return "ERROR: Unsupported mode!"


def handler_node(context, t, background=False, fetch_only=False):
    def warmth_node(context):
        group_name = "Warmth (Gaffer)"
        n = context.scene.world.node_tree.nodes.new("ShaderNodeGroup")
        if group_name not in bpy.data.node_groups:

            group = bpy.data.node_groups.new(group_name, "ShaderNodeTree")

            group_inputs = group.nodes.new("NodeGroupInput")
            group_inputs.location = (-70.08822631835938, -477.9051513671875)

            if bpy.app.version >= (4, 0, 0):
                group.interface.new_socket("Image", socket_type="NodeSocketColor", in_out="INPUT")
                temp = group.interface.new_socket("Temp", socket_type="NodeSocketFloat", in_out="INPUT")
                tint = group.interface.new_socket("Tint", socket_type="NodeSocketFloat", in_out="INPUT")
                group.interface.new_socket(socket_type="NodeSocketColor", name="Image", in_out="OUTPUT")

                temp.min_value = -100
                temp.max_value = 100
                tint.min_value = -100
                tint.max_value = 100

            else:
                group.inputs.new("NodeSocketColor", "Image")
                group.inputs.new("NodeSocketFloat", "Temp")
                group.inputs.new("NodeSocketFloat", "Tint")
                group.inputs[1].min_value = -100
                group.inputs[1].max_value = 100
                group.inputs[2].min_value = -100
                group.inputs[2].max_value = 100
                group.outputs.new("NodeSocketColor", "Image")

            group_outputs = group.nodes.new("NodeGroupOutput")
            group_outputs.location = (1032.72119140625, -158.30892944335938)

            n1 = group.nodes.new("ShaderNodeMath")
            n1.operation = "DIVIDE"
            n1.inputs[1].default_value = 150
            n1.location = (214.2261199951172, -338.8708190917969)

            n2 = group.nodes.new("ShaderNodeMath")
            n2.operation = "ADD"
            n2.inputs[1].default_value = 1.0
            n2.location = (407.1993713378906, -335.6588134765625)

            n3 = group.nodes.new("ShaderNodeSeparateXYZ")
            n3.location = (408.24310302734375, -167.7357940673828)

            n4 = group.nodes.new("ShaderNodeMath")
            n4.operation = "MULTIPLY"
            n4.location = (626.5187377929688, 85.08377838134766)

            n5 = group.nodes.new("ShaderNodeMath")
            n5.operation = "MULTIPLY"
            n5.location = (626.5187377929688, -90.68150329589844)

            n6 = group.nodes.new("ShaderNodeMath")
            n6.operation = "DIVIDE"
            n6.location = (626.5187377929688, -239.59378051757812)

            n7 = group.nodes.new("ShaderNodeMath")
            n7.operation = "DIVIDE"
            n7.inputs[1].default_value = 150
            n7.location = (214.2261199951172, -547.5130615234375)

            n8 = group.nodes.new("ShaderNodeMath")
            n8.operation = "ADD"
            n8.inputs[1].default_value = 1.0
            n8.location = (407.1993713378906, -529.1270751953125)

            n9 = group.nodes.new("ShaderNodeCombineXYZ")
            n9.location = (807.5265502929688, -162.73184204101562)

            group.links.new(group_inputs.outputs[1], n1.inputs[0])
            group.links.new(n1.outputs[0], n2.inputs[0])
            group.links.new(n2.outputs[0], n4.inputs[1])
            group.links.new(n2.outputs[0], n6.inputs[1])
            group.links.new(group_inputs.outputs[2], n7.inputs[0])
            group.links.new(n7.outputs[0], n8.inputs[0])
            group.links.new(n8.outputs[0], n5.inputs[1])
            group.links.new(group_inputs.outputs[0], n3.inputs[0])
            group.links.new(n3.outputs[0], n4.inputs[0])
            group.links.new(n3.outputs[1], n5.inputs[0])
            group.links.new(n3.outputs[2], n6.inputs[0])
            group.links.new(n4.outputs[0], n9.inputs[0])
            group.links.new(n5.outputs[0], n9.inputs[1])
            group.links.new(n6.outputs[0], n9.inputs[2])
            group.links.new(n9.outputs[0], group_outputs.inputs[0])

        n.node_tree = bpy.data.node_groups[group_name]
        return n

    """ Return requested node, or create it """
    nodes = context.scene.world.node_tree.nodes

    if t == "ShaderNodeOutputWorld":
        for n in nodes:
            if hasattr(n, "is_active_output"):
                if n.is_active_output:
                    return n

    name = "HDRIHandler_" + t + ("_B" if background else "")
    for n in nodes:
        if n.name == name:
            return n

    if fetch_only:
        # Sometimes we only want to fetch existing nodes, not create new ones,
        # for example when the context does not allow creating new nodes.
        return None

    if t == "Warmth":
        n = warmth_node(context)
    else:
        actual_t = t.split("__")[0]
        n = nodes.new(actual_t)
    n.name = name
    n.select = False

    y_offset = 250 if background else 0
    positions = {
        "ShaderNodeTexCoord": (-1760, 100),
        "ShaderNodeMapping": (-1570, 140 - y_offset * 1.5),
        "ShaderNodeMix__rot": (-1310, 75),
        "ShaderNodeTexEnvironment": (-1078, 91 - y_offset),
        "ShaderNodeGamma": (-581, 59 - y_offset),
        "ShaderNodeHueSaturation": (-391, 81 - y_offset),
        "ShaderNodeMix": (-193, 101 - y_offset),
        "Warmth": (-772, 72 - y_offset),
        "ShaderNodeBackground": (10, 48 - y_offset),
        "ShaderNodeMixShader": (220, 59),
        "ShaderNodeLightPath": (-1760, 426),
        "ShaderNodeMath": (-1570, 309) if background else (-392, -501),
        "ShaderNodeSeparateHSV": (-605, -404),
        "ShaderNodeValue": (-604, -540),
        "ShaderNodeMixRGB": (-194, -492),
        "ShaderNodeCombineHSV": (19, -404),
        "ShaderNodeOutputWorld": (430, 34),
    }
    n.location = positions[t]

    if t == "ShaderNodeMath" and not background:
        n.operation = "GREATER_THAN"

    if t == "ShaderNodeMix":
        n.data_type = "RGBA"
    elif t == "ShaderNodeMix__rot":
        n.data_type = "VECTOR"

    return n


def set_image(context, path, node):
    if os.path.exists(path):
        img = bpy.data.images.load(path, check_existing=True)
        node.image = img
        return True
    else:
        return False


def uses_default_values(node, node_type):
    # Return if the node is using all it's default values (and can therefore be muted to save render time)
    defaults_dict = {
        "ShaderNodeMapping": {
            "vector_type": "POINT",
            "translation": Vector((0, 0, 0)),
            "rotation": Euler((0, 0, 0)),
            "scale": Vector((1, 1, 1)),
            "use_min": False,
            "use_max": False,
        },
        "ShaderNodeGamma": {
            "_socket_1": 1,
        },
        "ShaderNodeHueSaturation": {
            "_socket_0": 0.5,
            "_socket_1": 1,
            "_socket_2": 1,
            "_socket_3": 1,
        },
        "Warmth": {
            "_socket_1": 0,
            "_socket_2": 0,
        },
    }
    defaults_dict["ShaderNodeMapping"]["_socket_1"] = defaults_dict["ShaderNodeMapping"]["translation"]
    defaults_dict["ShaderNodeMapping"]["_socket_2"] = defaults_dict["ShaderNodeMapping"]["rotation"]
    defaults_dict["ShaderNodeMapping"]["_socket_3"] = defaults_dict["ShaderNodeMapping"]["scale"]

    defaults = defaults_dict[node_type]
    for d in defaults:
        if d.startswith("_"):
            node_value = node.inputs[int(d[-1])].default_value
        else:
            try:
                node_value = getattr(node, d)
            except AttributeError:
                continue  # API changed, attribute no longer exists, can be ignored
        if defaults[d] != node_value:
            return False

    return True


def new_link(links, from_socket, to_socket, force=False):
    if not to_socket.is_linked or force:
        links.new(from_socket, to_socket)


def switch_hdri(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if gaf_hdri_props.hdri != "":
        default_var = get_variation(gaf_hdri_props.hdri, mode="smallest")  # Default to smallest

        # But prefer 1k if there is one
        for v in const.hdri_list[gaf_hdri_props.hdri]:
            if "1k" in v:
                default_var = get_variation(gaf_hdri_props.hdri, var=v)
                break

        gaf_hdri_props.hdri_variation = default_var
        setup_hdri(self, context)
    show_hdrihaven()


def setup_hdri(self, context):
    gaf_props = context.scene.gaf_props
    gaf_hdri_props = context.scene.world.gaf_hdri_props

    if not gaf_hdri_props.hdri_handler_enabled:
        return None  # Don't do anything if handler is disabled

    extra_nodes = any(
        [
            gaf_hdri_props.hdri_use_jpg_background,
            gaf_hdri_props.hdri_use_separate_brightness,
            gaf_hdri_props.hdri_use_separate_contrast,
            gaf_hdri_props.hdri_use_separate_saturation,
            gaf_hdri_props.hdri_use_separate_warmth,
            gaf_hdri_props.hdri_use_separate_tint,
            gaf_hdri_props.hdri_use_separate_color,
        ]
    )

    w = context.scene.world
    w.use_nodes = True

    # Create Nodes
    n_coord = handler_node(context, "ShaderNodeTexCoord")
    n_mapping = handler_node(context, "ShaderNodeMapping")
    n_img = handler_node(context, "ShaderNodeTexEnvironment")
    n_warm = handler_node(context, "Warmth")
    n_cont = handler_node(context, "ShaderNodeGamma")
    n_sat = handler_node(context, "ShaderNodeHueSaturation")
    n_col = handler_node(context, "ShaderNodeMix")
    n_shader = handler_node(context, "ShaderNodeBackground")
    n_out = handler_node(context, "ShaderNodeOutputWorld")

    if gaf_hdri_props.hdri_use_separate_rotation:
        n_mapping_b = handler_node(context, "ShaderNodeMapping", background=True)
        n_mixrot = handler_node(context, "ShaderNodeMix__rot")

    if extra_nodes:
        n_img_b = handler_node(
            context,
            "ShaderNodeTexEnvironment",
            background=gaf_hdri_props.hdri_use_jpg_background,
        )
        n_cont_b = handler_node(context, "ShaderNodeGamma", background=True)
        n_sat_b = handler_node(context, "ShaderNodeHueSaturation", background=True)
        n_col_b = handler_node(context, "ShaderNodeMix", background=True)
        n_warm_b = handler_node(context, "Warmth", background=True)
        n_shader_b = handler_node(context, "ShaderNodeBackground", background=True)
        n_mix = handler_node(context, "ShaderNodeMixShader")

    if extra_nodes or gaf_hdri_props.hdri_use_separate_rotation:
        n_lp = handler_node(context, "ShaderNodeLightPath")
        if gaf_hdri_props.hdri_use_bg_reflections:
            n_math = handler_node(context, "ShaderNodeMath", background=True)

    if gaf_hdri_props.hdri_clamp:
        n_shsv = handler_node(context, "ShaderNodeSeparateHSV")
        n_clamp_val = handler_node(context, "ShaderNodeValue")
        n_greater = handler_node(context, "ShaderNodeMath")
        n_mix_clamp = handler_node(context, "ShaderNodeMixRGB")
        n_chsv = handler_node(context, "ShaderNodeCombineHSV")

    # Links
    links = w.node_tree.links
    new_link(links, n_coord.outputs[0], n_mapping.inputs[0])
    new_link(links, n_img.outputs[0], n_warm.inputs[0])
    new_link(links, n_warm.outputs[0], n_cont.inputs[0])
    new_link(links, n_cont.outputs[0], n_sat.inputs[4])
    new_link(links, n_sat.outputs[0], n_col.inputs[6])
    new_link(links, n_col.outputs[2], n_shader.inputs[0], force=True)

    if gaf_hdri_props.hdri_use_separate_rotation:
        new_link(links, n_coord.outputs[0], n_mapping_b.inputs[0], force=True)
        new_link(links, n_mapping.outputs[0], n_mixrot.inputs[4], force=True)
        new_link(links, n_mapping_b.outputs[0], n_mixrot.inputs[5], force=True)
        new_link(links, n_mixrot.outputs[1], n_img.inputs[0], force=True)
        coords_socket = n_mixrot.outputs[1]
        if gaf_hdri_props.hdri_use_bg_reflections:
            new_link(links, n_math.outputs[0], n_mixrot.inputs[0], force=True)
        else:
            new_link(links, n_lp.outputs[0], n_mixrot.inputs[0], force=True)
    else:
        new_link(links, n_mapping.outputs[0], n_img.inputs[0], force=True)
        coords_socket = n_mapping.outputs[0]

    if extra_nodes:
        new_link(links, coords_socket, n_img_b.inputs[0], force=True)
        new_link(links, n_img_b.outputs[0], n_warm_b.inputs[0], force=True)
        new_link(links, n_warm_b.outputs[0], n_cont_b.inputs[0], force=True)
        new_link(links, n_cont_b.outputs[0], n_sat_b.inputs[4], force=True)
        new_link(links, n_sat_b.outputs[0], n_col_b.inputs[6], force=True)
        new_link(links, n_col_b.outputs[2], n_shader_b.inputs[0], force=True)
        new_link(links, n_shader.outputs[0], n_mix.inputs[1], force=True)
        new_link(links, n_shader_b.outputs[0], n_mix.inputs[2], force=True)
        if gaf_hdri_props.hdri_use_bg_reflections:
            new_link(links, n_math.outputs[0], n_mix.inputs[0], force=True)
        else:
            new_link(links, n_lp.outputs[0], n_mix.inputs[0], force=True)
        new_link(links, n_mix.outputs[0], n_out.inputs[0], force=True)
    else:
        new_link(links, n_shader.outputs[0], n_out.inputs[0], force=True)

    if extra_nodes or gaf_hdri_props.hdri_use_separate_rotation:
        if gaf_hdri_props.hdri_use_bg_reflections:
            new_link(links, n_lp.outputs[0], n_math.inputs[0], force=True)  # Camera Ray
            new_link(links, n_lp.outputs[3], n_math.inputs[1], force=True)  # Glossy Ray

    if gaf_hdri_props.hdri_clamp:
        new_link(links, n_col.outputs[2], n_shsv.inputs[0])
        new_link(links, n_shsv.outputs[0], n_chsv.inputs[0])
        new_link(links, n_shsv.outputs[1], n_chsv.inputs[1])
        new_link(links, n_shsv.outputs[2], n_greater.inputs[0])
        new_link(links, n_shsv.outputs[2], n_mix_clamp.inputs[1])
        new_link(links, n_clamp_val.outputs[0], n_greater.inputs[1])
        new_link(links, n_clamp_val.outputs[0], n_mix_clamp.inputs[2])
        new_link(links, n_greater.outputs[0], n_mix_clamp.inputs[0])
        new_link(links, n_mix_clamp.outputs[0], n_chsv.inputs[2])
        new_link(links, n_chsv.outputs[0], n_shader.inputs[0], force=True)

    # Set Env images
    gaf_props.FileNotFoundError = not os.path.exists(gaf_hdri_props.hdri_variation)
    set_image(context, gaf_hdri_props.hdri_variation, n_img)
    if extra_nodes:
        if gaf_hdri_props.hdri_use_jpg_background:
            jpg_path = os.path.join(const.jpg_dir, gaf_hdri_props.hdri + ".jpg")
            djpg_path = os.path.join(const.jpg_dir, gaf_hdri_props.hdri + "_dark.jpg")
            if os.path.exists(jpg_path) and os.path.exists(djpg_path):
                if gaf_hdri_props.hdri_use_darkened_jpg:
                    set_image(context, djpg_path, n_img_b)
                else:
                    set_image(context, jpg_path, n_img_b)
            else:
                gaf_props.RequestJPGGen = True

    # Run Updates
    update_rotation(self, context)
    update_brightness(self, context)
    update_contrast(self, context)
    update_saturation(self, context)
    update_warmth(self, context)
    update_tint(self, context)
    update_color(self, context)
    update_background_rotation(self, context)
    update_background_brightness(self, context)
    update_background_contrast(self, context)
    update_background_saturation(self, context)
    update_background_warmth(self, context)
    update_background_tint(self, context)
    update_background_color(self, context)

    return None


def hdri_enable(self, context):
    def store_old_world_settings(context):
        gaf_hdri_props = context.scene.world.gaf_hdri_props
        w = context.scene.world
        if w.use_nodes:
            for n in w.node_tree.nodes:
                if hasattr(n, "is_active_output"):
                    if n.is_active_output:
                        gaf_hdri_props.OldWorldSettings = n.name
                        break
            else:
                # No active world output node found
                gaf_hdri_props.OldWorldSettings = "__not use_nodes__"
        else:
            gaf_hdri_props.OldWorldSettings = "__not use_nodes__"

    def restore_old_world_settings(context):
        ow = context.scene.world.gaf_hdri_props.OldWorldSettings
        w = context.scene.world
        if ow == "__not use_nodes__":
            w.use_nodes = False
        else:
            try:
                w.node_tree.nodes[ow].is_active_output = True
                for n in w.node_tree.nodes:
                    if n.name != ow:
                        if hasattr(n, "is_active_output"):
                            n.is_active_output = False
            except (KeyError, IndexError, AttributeError):
                print("Failed to reset active world output (node may not exist anymore?)")

    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if gaf_hdri_props.hdri_handler_enabled:
        store_old_world_settings(context)
        prefs = context.preferences.addons[__package__].preferences
        hdri_paths = get_persistent_setting("hdri_paths")
        if hdri_paths[0] != "" and os.path.exists(hdri_paths[0]):
            detect_hdris(self, context)
            setup_hdri(self, context)
            prefs.ForcePreviewsRefresh = True
            if gaf_hdri_props.hdri:
                if not os.path.exists(os.path.join(const.thumbnail_dir, gaf_hdri_props.hdri + "__thumb_preview.jpg")):
                    prefs.RequestThumbGen = True
        else:
            gaf_hdri_props.hdri_handler_enabled = False
    else:
        restore_old_world_settings(context)


def update_search(self, context):
    bpy.context.preferences.addons[__package__].preferences.ForcePreviewsRefresh = True
    if context.scene.world.gaf_hdri_props.hdri:
        # Force update of currently shown thumbnail
        context.scene.world.gaf_hdri_props.hdri = context.scene.world.gaf_hdri_props.hdri
    else:
        hdri_list = get_hdri_list(use_search=True)
        if hdri_list:
            # Default to first HDRI in list if the previous one isn't there.
            context.scene.world.gaf_hdri_props.hdri = tuple(hdri_list)[0]


def update_variation(self, context):
    gaf_props = context.scene.gaf_props
    gaf_hdri_props = context.scene.world.gaf_hdri_props

    if not gaf_hdri_props.hdri_handler_enabled:
        return None  # Don't do anything if handler is disabled

    n = handler_node(context, "ShaderNodeTexEnvironment")
    gaf_props.FileNotFoundError = not os.path.exists(gaf_hdri_props.hdri_variation)
    set_image(context, gaf_hdri_props.hdri_variation, n)

    return None


def update_rotation(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled:
        return None  # Don't do anything if handler is disabled

    n = handler_node(context, "ShaderNodeMapping")

    e = 2
    rot = math.radians(gaf_hdri_props.hdri_rotation)
    loc = pow(gaf_hdri_props.hdri_horz_shift, e) * 2
    sca = pow(1 - ((gaf_hdri_props.hdri_horz_exp * 2 - 1) * pow(gaf_hdri_props.hdri_horz_shift, e)), e)

    n.inputs["Location"].default_value.z = loc
    n.inputs["Rotation"].default_value.z = rot
    n.inputs["Scale"].default_value.z = sca

    n.mute = uses_default_values(n, "ShaderNodeMapping")

    return None


def update_horizon(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    update_rotation(self, context)
    if gaf_hdri_props.hdri_use_separate_rotation:
        update_background_rotation(self, context)


def update_brightness(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled:
        return None  # Don't do anything if handler is disabled

    value = pow(2, gaf_hdri_props.hdri_brightness)
    n = handler_node(context, "ShaderNodeBackground")
    n.inputs[1].default_value = value

    extra_nodes = any(
        [
            gaf_hdri_props.hdri_use_jpg_background,
            gaf_hdri_props.hdri_use_separate_brightness,
            gaf_hdri_props.hdri_use_separate_contrast,
            gaf_hdri_props.hdri_use_separate_saturation,
            gaf_hdri_props.hdri_use_separate_warmth,
            gaf_hdri_props.hdri_use_separate_tint,
            gaf_hdri_props.hdri_use_separate_color,
        ]
    )
    if not gaf_hdri_props.hdri_use_separate_brightness and extra_nodes:
        if gaf_hdri_props.hdri_use_darkened_jpg:
            value *= 20  # Increase exposure by ~4 EVs
        n = handler_node(context, "ShaderNodeBackground", background=True)
        n.inputs[1].default_value = value

    return None


def update_contrast(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled:
        return None  # Don't do anything if handler is disabled

    value = gaf_hdri_props.hdri_contrast
    n = handler_node(context, "ShaderNodeGamma")
    n.inputs[1].default_value = value
    n.mute = uses_default_values(n, "ShaderNodeGamma")

    extra_nodes = any(
        [
            gaf_hdri_props.hdri_use_jpg_background,
            gaf_hdri_props.hdri_use_separate_brightness,
            gaf_hdri_props.hdri_use_separate_contrast,
            gaf_hdri_props.hdri_use_separate_saturation,
            gaf_hdri_props.hdri_use_separate_warmth,
            gaf_hdri_props.hdri_use_separate_tint,
            gaf_hdri_props.hdri_use_separate_color,
        ]
    )
    if not gaf_hdri_props.hdri_use_separate_contrast and extra_nodes:
        n = handler_node(context, "ShaderNodeGamma", background=True)
        n.inputs[1].default_value = value
        n.mute = uses_default_values(n, "ShaderNodeGamma")

    return None


def update_saturation(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled:
        return None  # Don't do anything if handler is disabled

    value = gaf_hdri_props.hdri_saturation
    n = handler_node(context, "ShaderNodeHueSaturation")
    n.inputs[1].default_value = value
    n.mute = uses_default_values(n, "ShaderNodeHueSaturation")

    extra_nodes = any(
        [
            gaf_hdri_props.hdri_use_jpg_background,
            gaf_hdri_props.hdri_use_separate_brightness,
            gaf_hdri_props.hdri_use_separate_contrast,
            gaf_hdri_props.hdri_use_separate_saturation,
            gaf_hdri_props.hdri_use_separate_warmth,
            gaf_hdri_props.hdri_use_separate_tint,
            gaf_hdri_props.hdri_use_separate_color,
        ]
    )
    if not gaf_hdri_props.hdri_use_separate_saturation and extra_nodes:
        n = handler_node(context, "ShaderNodeHueSaturation", background=True)
        n.inputs[1].default_value = value
        n.mute = uses_default_values(n, "ShaderNodeHueSaturation")

    return None


def update_warmth(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled:
        return None  # Don't do anything if handler is disabled

    value = (gaf_hdri_props.hdri_warmth - 1) * 100
    n = handler_node(context, "Warmth")
    n.inputs[1].default_value = value
    n.mute = uses_default_values(n, "Warmth")

    extra_nodes = any(
        [
            gaf_hdri_props.hdri_use_jpg_background,
            gaf_hdri_props.hdri_use_separate_brightness,
            gaf_hdri_props.hdri_use_separate_contrast,
            gaf_hdri_props.hdri_use_separate_saturation,
            gaf_hdri_props.hdri_use_separate_warmth,
            gaf_hdri_props.hdri_use_separate_tint,
            gaf_hdri_props.hdri_use_separate_color,
        ]
    )
    if not gaf_hdri_props.hdri_use_separate_warmth and extra_nodes:
        n = handler_node(context, "Warmth", background=True)
        n.inputs[1].default_value = value
        n.mute = uses_default_values(n, "Warmth")

    return None


def update_tint(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled:
        return None  # Don't do anything if handler is disabled

    value = (gaf_hdri_props.hdri_tint - 1) * 100
    n = handler_node(context, "Warmth")
    n.inputs[2].default_value = value
    n.mute = uses_default_values(n, "Warmth")

    extra_nodes = any(
        [
            gaf_hdri_props.hdri_use_jpg_background,
            gaf_hdri_props.hdri_use_separate_brightness,
            gaf_hdri_props.hdri_use_separate_contrast,
            gaf_hdri_props.hdri_use_separate_saturation,
            gaf_hdri_props.hdri_use_separate_warmth,
            gaf_hdri_props.hdri_use_separate_tint,
            gaf_hdri_props.hdri_use_separate_color,
        ]
    )
    if not gaf_hdri_props.hdri_use_separate_tint and extra_nodes:
        n = handler_node(context, "Warmth", background=True)
        n.inputs[2].default_value = value
        n.mute = uses_default_values(n, "Warmth")

    return None


def update_color(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled:
        return None  # Don't do anything if handler is disabled

    value = gaf_hdri_props.hdri_color
    n = handler_node(context, "ShaderNodeMix")
    n.inputs[0].default_value = value[3]
    n.inputs[7].default_value = value[:-1] + (1,)
    n.mute = value[3] == 0

    extra_nodes = any(
        [
            gaf_hdri_props.hdri_use_jpg_background,
            gaf_hdri_props.hdri_use_separate_brightness,
            gaf_hdri_props.hdri_use_separate_contrast,
            gaf_hdri_props.hdri_use_separate_saturation,
            gaf_hdri_props.hdri_use_separate_warmth,
            gaf_hdri_props.hdri_use_separate_tint,
            gaf_hdri_props.hdri_use_separate_color,
        ]
    )
    if not gaf_hdri_props.hdri_use_separate_color and extra_nodes:
        bn = handler_node(context, "ShaderNodeMix", background=True)
        bn.blend_type = n.blend_type
        bn.inputs[0].default_value = value[3]
        bn.inputs[7].default_value = value[:-1] + (1,)
        bn.mute = value[3] == 0

    return None


def update_clamp(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled:
        return None  # Don't do anything if handler is disabled

    value = gaf_hdri_props.hdri_clamp
    n = handler_node(context, "ShaderNodeValue")
    n.outputs[0].default_value = value

    setup_hdri(self, context)

    return None


def update_background_rotation(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled or not gaf_hdri_props.hdri_use_separate_rotation:
        update_rotation(self, context)
        return None

    n = handler_node(context, "ShaderNodeMapping", background=True)

    e = 2
    rot = math.radians(gaf_hdri_props.hdri_background_rotation)
    loc = pow(gaf_hdri_props.hdri_horz_shift, e) * 2
    sca = pow(1 - ((gaf_hdri_props.hdri_horz_exp * 2 - 1) * pow(gaf_hdri_props.hdri_horz_shift, e)), e)

    n.inputs["Location"].default_value.z = loc
    n.inputs["Rotation"].default_value.z = rot
    n.inputs["Scale"].default_value.z = sca

    n.mute = uses_default_values(n, "ShaderNodeMapping")

    return None


def update_background_brightness(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled or not gaf_hdri_props.hdri_use_separate_brightness:
        update_brightness(self, context)
        return None

    value = pow(2, gaf_hdri_props.hdri_background_brightness)
    if gaf_hdri_props.hdri_use_darkened_jpg:
        value *= 20  # Increase exposure by ~4 EVs
    n = handler_node(context, "ShaderNodeBackground", background=True)
    n.inputs[1].default_value = value

    return None


def update_background_contrast(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled or not gaf_hdri_props.hdri_use_separate_contrast:
        update_contrast(self, context)
        return None

    value = gaf_hdri_props.hdri_background_contrast
    n = handler_node(context, "ShaderNodeGamma", background=True)
    n.inputs[1].default_value = value
    n.mute = uses_default_values(n, "ShaderNodeGamma")

    return None


def update_background_saturation(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled or not gaf_hdri_props.hdri_use_separate_saturation:
        update_saturation(self, context)
        return None

    value = gaf_hdri_props.hdri_background_saturation
    n = handler_node(context, "ShaderNodeHueSaturation", background=True)
    n.inputs[1].default_value = value
    n.mute = uses_default_values(n, "ShaderNodeHueSaturation")

    return None


def update_background_warmth(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled or not gaf_hdri_props.hdri_use_separate_warmth:
        update_warmth(self, context)
        return None

    value = (gaf_hdri_props.hdri_background_warmth - 1) * 100
    n = handler_node(context, "Warmth", background=True)
    n.inputs[1].default_value = value
    n.mute = uses_default_values(n, "Warmth")

    return None


def update_background_tint(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled or not gaf_hdri_props.hdri_use_separate_tint:
        update_warmth(self, context)
        return None

    value = (gaf_hdri_props.hdri_background_tint - 1) * 100
    n = handler_node(context, "Warmth", background=True)
    n.inputs[2].default_value = value
    n.mute = uses_default_values(n, "Warmth")

    return None


def update_background_color(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if not gaf_hdri_props.hdri_handler_enabled or not gaf_hdri_props.hdri_use_separate_color:
        update_color(self, context)
        return None

    value = gaf_hdri_props.hdri_background_color
    n = handler_node(context, "ShaderNodeMix", background=True)
    n.inputs[0].default_value = value[3]
    n.inputs[7].default_value = value[:-1] + (1,)
    n.mute = value[3] == 0

    return None


def missing_thumb():
    return os.path.join(const.icon_dir, "special", "missing_thumb.png")


def save_image(context, img, filepath, fileformat, exposure=0):
    # Saving using 'img.save_render' will apply all render color management
    # stuffs to it, which is probably not desired.
    # So first remember user's settings, then reset to default before saving
    vs = context.scene.view_settings
    old_vs = {}
    for a in dir(vs):
        if (not a.startswith("__")) and ("rna" not in a) and (a != "curve_mapping"):
            old_vs[a] = getattr(vs, a)
    vs.exposure = exposure
    vs.gamma = 1
    vs.look = "None"
    vs.use_curve_mapping = False
    try:
        # Filmic Blender doesn't have a "Default"
        vs.view_transform = "Default"
    except TypeError:
        try:
            vs.view_transform = "sRGB EOTF"  # Default for Filmic
        except TypeError:
            print("WARNING: Unable to set default for view transform.")

    settings = context.scene.render.image_settings
    old_quality = settings.quality
    old_format = settings.file_format

    settings.quality = 95
    settings.file_format = fileformat

    img.save_render(filepath=filepath, scene=context.scene)

    settings.quality = old_quality
    settings.file_format = old_format
    for a in old_vs:
        setattr(vs, a, old_vs[a])


def nice_hdri_name(name):
    dont_capitalize = [
        "a",
        "an",
        "the",
        "for",
        "and",
        "by",
        "at",
        "of",
        " from",
        "on",
        "with",
    ]
    name = name[0] + name[1:].replace("_", " ").replace("-", " ").replace(".", " ")
    #      ^^  name = name[0] + name[1:] to ignore separator if first char
    name = " ".join(name.split())  # Merge multple spaces into one
    name = " ".join([w[0].upper() + w[1:] for w in name.split(" ")])  # Title case but only for first character
    for w in dont_capitalize:
        name.replace(" " + w.title(), " " + w)
    return name


def previews_register():
    import bpy.utils.previews

    pcoll = bpy.utils.previews.new()
    pcoll.previews = ()
    const.preview_collections["main"] = pcoll

    import bpy.utils.previews

    const.custom_icons = bpy.utils.previews.new()
    for f in os.listdir(const.icon_dir):
        if f.endswith(".png"):
            const.custom_icons.load(
                os.path.splitext(os.path.basename(f))[0],
                os.path.join(const.icon_dir, f),
                "IMAGE",
            )


def previews_unregister():
    for pcoll in const.preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    const.preview_collections.clear()

    bpy.utils.previews.remove(const.custom_icons)


def get_icons():
    return const.custom_icons


def refresh_previews():
    previews_unregister()
    previews_register()
    bpy.context.preferences.addons[__package__].preferences.ForcePreviewsRefresh = True


def hdri_enum_previews(self, context):
    enum_items = []

    if context is None:
        return enum_items

    # Get the preview collection (defined in register func).
    pcoll = const.preview_collections["main"]

    prefs = bpy.context.preferences.addons[__package__].preferences
    if not prefs.ForcePreviewsRefresh:
        return pcoll.previews
    else:
        prefs.ForcePreviewsRefresh = False

    # Make indexes for all HDRIs
    indexes = {}
    all_hdris = get_hdri_list()
    for i, name in enumerate(all_hdris):
        indexes[name] = i

    all_thumbs_exist = True
    for i, name in enumerate(get_hdri_list(use_search=True)):

        thumb_file = os.path.join(const.thumbnail_dir, name + "__thumb_preview.jpg")
        if not os.path.exists(thumb_file):
            print("Missing thumb", name)
            all_thumbs_exist = False
            thumb_file = missing_thumb()

        if name in pcoll:
            thumb = pcoll[name]
        else:
            thumb = pcoll.load(name, thumb_file, "IMAGE")
        enum_items.append((name, name, "", thumb.icon_id, indexes[name]))

    prefs.RequestThumbGen = not all_thumbs_exist

    pcoll.previews = enum_items
    return pcoll.previews


def variation_enum_previews(self, context):
    enum_items = []
    gaf_hdri_props = context.scene.world.gaf_hdri_props

    if context is None:
        return enum_items

    variations = const.hdri_list[gaf_hdri_props.hdri]
    for v in variations:
        enum_items.append((v, os.path.basename(v), v))

    return enum_items


def get_favorites_dict(force_update=False):
    if force_update or not const.favorites:
        if os.path.exists(const.favorites_path):
            with open(const.favorites_path) as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = {}
            const.favorites = data
            return data
        else:
            return {}
    else:
        return const.favorites


def get_favorites(force_update=False):
    d = get_favorites_dict(force_update)
    return {k: v for k, v in d.items() if v}


def set_favorite(name, favorite=True):
    favorites_list = get_favorites_dict()
    favorites_list[name] = favorite
    const.favorites[name] = favorite

    with open(const.favorites_path, "w") as f:
        f.write(json.dumps(favorites_list, indent=4))


def get_tags():
    if os.path.exists(const.tags_path):
        with open(const.tags_path) as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
        return data
    else:
        return {}


def set_tag(name, tag, toggle=True):
    tag = tag.strip().lower()
    tag_list = get_tags()
    if name in tag_list:
        current_tags = tag_list[name]
        if tag not in current_tags:
            tag_list[name].append(tag)
        elif toggle:
            i = tag_list[name].index(tag)
            del tag_list[name][i]
    else:
        tag_list[name] = [tag]

    with open(const.tags_path, "w") as f:
        f.write(json.dumps(tag_list, indent=4))


def set_custom_tags(self, context):
    gaf_hdri_props = context.scene.world.gaf_hdri_props
    if gaf_hdri_props.hdri_custom_tags != "":
        tags = gaf_hdri_props.hdri_custom_tags.replace(";", ",").split(",")

        for t in tags:
            t = t.strip().lower()
            set_tag(gaf_hdri_props.hdri, t, toggle=False)
            if t not in const.possible_tags:
                const.possible_tags.append(t)

        gaf_hdri_props.hdri_custom_tags = ""


def get_possible_tags_list():
    tags_list = get_tags()
    possible_tags = const.default_tags
    actual_tags = []
    for h in tags_list:
        for t in tags_list[h]:
            if t not in possible_tags and t not in actual_tags:
                actual_tags.append(t)
    possible_tags += sorted(actual_tags)
    return possible_tags


if len(const.possible_tags) < 1:
    const.possible_tags = get_possible_tags_list()


def get_defaults(hdri_name):
    if os.path.exists(const.defaults_path):
        with open(const.defaults_path) as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
        if hdri_name in data:
            return data[hdri_name]
    return {}


def set_defaults(context, hdri_name):
    defaults = {}
    if os.path.exists(const.defaults_path):
        with open(const.defaults_path) as f:
            defaults = json.load(f)
    for d in const.defaults_stored:
        if hdri_name not in defaults:
            defaults[hdri_name] = {}
        defaults[hdri_name][d] = getattr(context.scene.world.gaf_hdri_props, "hdri_" + d)
    with open(const.defaults_path, "w") as f:
        f.write(json.dumps(defaults, indent=4))


def update_offline_mode(self, context):
    prefs = context.preferences.addons[__package__].preferences
    set_persistent_setting("offline_mode", prefs.offline_mode)


def get_hdri_haven_list(force_update=False):
    """Get Poly Haven list from web once per week, otherwise fetch from file"""

    offline_data = {}
    if os.path.exists(const.hdri_haven_list_path):
        with open(const.hdri_haven_list_path) as f:
            try:
                offline_data = json.load(f)
            except json.JSONDecodeError:
                offline_data = {}

    prefs = bpy.context.preferences.addons[__package__].preferences

    if (prefs and prefs.offline_mode) or get_persistent_setting("offline_mode"):
        print("Gaffer not fetching HDRIs from Poly Haven, offline mode enabled, using local data if available")
        return offline_data

    if not force_update:
        if offline_data:
            import time

            age = time.time() - os.stat(const.hdri_haven_list_path).st_mtime  # seconds since last modified
            if age / 60 / 60 / 24 < 7:
                return offline_data

    from requests import get as requests_get
    from requests.exceptions import RequestException, Timeout, HTTPError

    print("Getting HDRI list from Poly Haven...")
    try:
        hdrihaven_hdris = requests_get("https://hdrihaven.com/php/json_list.php", timeout=10).json()
    except (RequestException, Timeout, HTTPError):
        if force_update:
            print("    Can't fetch list from Poly Haven")
            return {}
        else:
            print("    Can't fetch list from Poly Haven, using old data")
            if offline_data:
                return offline_data
            else:
                print("    No old data either!")
                return {}
    else:
        for h in hdrihaven_hdris:
            # Convert comma separated list into actual list
            hdrihaven_hdris[h] = hdrihaven_hdris[h].replace(";", ",").split(",")
        with open(const.hdri_haven_list_path, "w") as f:
            f.write(json.dumps(hdrihaven_hdris, indent=4))

        # Add Poly Haven tags to tag list
        standard_colors = [
            "red",
            "green",
            "blue",
            "yellow",
            "orange",
            "purple",
            "pink",
            "brown",
            "black",
            "gray",
            "white",
        ]
        tag_list = get_tags()
        for h in hdrihaven_hdris:
            if h in const.hdri_list:
                if h in tag_list:
                    for t in hdrihaven_hdris[h]:
                        if t not in tag_list[h]:
                            if t not in standard_colors:
                                tag_list[h].append(t)
                else:
                    tag_list[h] = [t for t in hdrihaven_hdris[h] if t not in standard_colors]
        with open(const.tags_path, "w") as f:
            f.write(json.dumps(tag_list, indent=4))

        return hdrihaven_hdris


if len(const.hdri_haven_list) < 1:
    const.hdri_haven_list = get_hdri_haven_list()


def show_hdrihaven():
    hdri_paths = get_persistent_setting("hdri_paths")
    if not os.path.exists(os.path.join(hdri_paths[0], "HDRI Haven")):
        if get_persistent_setting("show_hdri_haven"):
            bpy.context.scene.gaf_props.ShowHDRIHaven = True


# Progress bar functions


def _force_redraw_hack():  # Taken from Campbell's Cell Fracture addon
    return  # TODO this function crashes in 2.8, better use something like asyncio or a modal operator instead.
    _force_redraw_hack.opr(**_force_redraw_hack.arg)


_force_redraw_hack.opr = bpy.ops.wm.redraw_timer
_force_redraw_hack.arg = dict(type="DRAW_WIN_SWAP", iterations=1)


def progress_begin(context):
    context.scene.gaf_props.ShowProgress = True
    _force_redraw_hack()


def progress_update(context, value, text):
    context.scene.gaf_props.Progress = value
    context.scene.gaf_props.ProgressText = text
    context.scene.gaf_props.ProgressBarText = str(round(value * 100)) + "%"
    _force_redraw_hack()


def progress_end(context):
    context.scene.gaf_props.Progress = 0
    context.scene.gaf_props.ShowProgress = False
