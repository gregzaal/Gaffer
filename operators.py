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
import bgl
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from math import pi, cos, sin, log, ceil
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.app.handlers import persistent
from bpy_extras.io_utils import ImportHelper
from time import sleep
from subprocess import run

from .constants import *
from .functions import *


@persistent
def load_handler(dummy):
    '''
        We need to remove the draw handlers when loading a blend file,
        otherwise a crapton of errors about the class being removed is printed
        (If a blend is saved with the draw handler running, then it's loaded
        with it running, but the class called for drawing no longer exists)
    
        Ideally we should recreate the handler when loading the scene if it
        was enabled when it was saved - however this function is called
        before the blender UI finishes loading, and thus no 3D view exists yet.
    '''
    if GAFFER_OT_show_light_radius._handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(GAFFER_OT_show_light_radius._handle, 'WINDOW')
    if GAFFER_OT_show_light_label._handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(GAFFER_OT_show_light_label._handle, 'WINDOW')
    bpy.context.scene.gaf_props.IsShowingRadius = False
    bpy.context.scene.gaf_props.IsShowingLabel = False

    
class GAFFER_OT_rename(bpy.types.Operator):

    'Rename this light'
    bl_idname = 'gaffer.rename'
    bl_label = 'Rename This Light'
    bl_options = {'REGISTER', 'UNDO'}
    light: bpy.props.StringProperty(name="New name")
    multiuser: bpy.props.StringProperty(default="")
    oldname = ""
    users = []

    def draw(self, context):
        self.layout.prop(self, 'light')
        if self.multiuser != "":
            self.layout.label(
                text="You are renaming the " +
                     ("light data" if self.multiuser.startswith("LIGHT") else "material") +
                     ", which has multiple users"
            )

    def invoke(self, context, event):
        self.oldname = self.light
        return context.window_manager.invoke_props_popup(self, event)

    def execute(self, context):
        if self.multiuser.startswith("LIGHT"):
            bpy.data.lights[self.oldname].name = self.light
        elif self.multiuser.startswith("MAT"):
            bpy.data.materials[self.oldname].name = self.light
        else:
            context.scene.objects[self.oldname].name = self.light
        refresh_light_list(context.scene)
        return {'FINISHED'}


class GAFFER_OT_set_temp(bpy.types.Operator):

    'Set the color temperature to a preset'
    bl_idname = 'gaffer.col_temp_preset'
    bl_label = 'Color Temperature Preset'
    temperature: bpy.props.StringProperty()
    light: bpy.props.StringProperty()
    material: bpy.props.StringProperty()
    node: bpy.props.StringProperty()

    def execute(self, context):
        light = context.scene.objects[self.light]
        if light.type == 'LIGHT':
            node = light.data.node_tree.nodes[self.node]
        else:
            node = bpy.data.materials[self.material].node_tree.nodes[self.node]
        node.inputs[0].links[0].from_node.inputs[0].default_value = col_temp[self.temperature]
        return {'FINISHED'}


class GAFFER_OT_show_temp_list(bpy.types.Operator):

    'Set the color temperature to a preset'
    bl_idname = 'gaffer.col_temp_show'
    bl_label = 'Color Temperature Preset'
    l_index: bpy.props.IntProperty()

    def execute(self, context):
        context.scene.gaf_props.ColTempExpand = True
        context.scene.gaf_props.LightUIIndex = self.l_index
        return {'FINISHED'}


class GAFFER_OT_hide_temp_list(bpy.types.Operator):

    'Hide color temperature presets'
    bl_idname = 'gaffer.col_temp_hide'
    bl_label = 'Hide Presets'

    def execute(self, context):
        context.scene.gaf_props.ColTempExpand = False
        return {'FINISHED'}


class GAFFER_OT_show_more(bpy.types.Operator):

    'Show settings such as MIS, falloff, ray visibility...'
    bl_idname = 'gaffer.more_options_show'
    bl_label = 'Show more options'
    light: bpy.props.StringProperty()

    def execute(self, context):
        exp_list = context.scene.gaf_props.MoreExpand
        # prepend+append funny stuff so that the light name is
        # unique (otherwise Fill_03 would also expand Fill_03.001)
        exp_list += ("_Light:_(" + self.light + ")_")
        context.scene.gaf_props.MoreExpand = exp_list
        return {'FINISHED'}


class GAFFER_OT_hide_more(bpy.types.Operator):

    'Hide settings such as MIS, falloff, ray visibility...'
    bl_idname = 'gaffer.more_options_hide'
    bl_label = 'Hide more options'
    light: bpy.props.StringProperty()

    def execute(self, context):
        context.scene.gaf_props.MoreExpand = context.scene.gaf_props.MoreExpand.replace(
            "_Light:_(" + self.light + ")_",
            ""
        )
        return {'FINISHED'}


class GAFFER_OT_hide_show_light(bpy.types.Operator):

    'Hide/Show this light (in viewport and in render)'
    bl_idname = 'gaffer.hide_light'
    bl_label = 'Hide Light'
    light: bpy.props.StringProperty()
    hide: bpy.props.BoolProperty()
    dataname: bpy.props.StringProperty()

    def execute(self, context):
        dataname = self.dataname
        if dataname == "__SINGLE_USER__":
            light = bpy.data.objects[self.light]
            light.hide_viewport = self.hide
            light.hide_render = self.hide
        else:
            if dataname.startswith('LIGHT'):
                data = bpy.data.lights[(dataname[5:])]  # actual data name (minus the prepended 'LIGHT')
                for obj in bpy.data.objects:
                    if obj.data == data:
                        obj.hide_viewport = self.hide
                        obj.hide_render = self.hide
            else:
                mat = bpy.data.materials[(dataname[3:])]  # actual data name (minus the prepended 'MAT')
                for obj in bpy.data.objects:
                    if obj.type == 'MESH':
                        for slot in obj.material_slots:
                            if slot.material == mat:
                                obj.hide_viewport = self.hide
                                obj.hide_render = self.hide
        return {'FINISHED'}


class GAFFER_OT_select_light(bpy.types.Operator):

    'Select this light'
    bl_idname = 'gaffer.select_light'
    bl_label = 'Select'
    light: bpy.props.StringProperty()
    dataname: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        for item in context.scene.objects:
            item.select_set(False)
        dataname = self.dataname
        if dataname == "__SINGLE_USER__":
            obj = bpy.data.objects[self.light]
            obj.select_set(True)
            context.view_layer.objects.active = obj
        else:
            if dataname.startswith('LIGHT'):
                data = bpy.data.lights[(dataname[5:])]  # actual data name (minus the prepended 'LIGHT')
                for obj in bpy.data.objects:
                    if obj.data == data:
                        obj.select_set(True)
            else:
                mat = bpy.data.materials[(dataname[3:])]  # actual data name (minus the prepended 'MAT')
                for obj in bpy.data.objects:
                    if obj.type == 'MESH':
                        for slot in obj.material_slots:
                            if slot.material == mat:
                                obj.select_set(True)
            context.view_layer.objects.active = bpy.data.objects[self.light]

        return {'FINISHED'}


class GAFFER_OT_solo(bpy.types.Operator):

    ("Solo: Hide all other lights but this one.\n"
     "Click again to restore previous light visibility")
    bl_idname = 'gaffer.solo'
    bl_label = 'Solo Light'
    light: bpy.props.StringProperty()
    showhide: bpy.props.BoolProperty()
    worldsolo: bpy.props.BoolProperty(default=False)
    dataname: bpy.props.StringProperty(default="__EXIT_SOLO__")

    def execute(self, context):
        light = self.light
        showhide = self.showhide
        worldsolo = self.worldsolo
        scene = context.scene
        blacklist = context.scene.gaf_props.Blacklist

        # Get object names that share data with the solo'd object:
        dataname = self.dataname
        linked_lights = []

        # Only make list if going into Solo and obj has multiple users
        if dataname not in ["__SINGLE_USER__", "__EXIT_SOLO__"] and showhide:
            if dataname.startswith('LIGHT'):
                data = bpy.data.lights[(dataname[5:])]  # actual data name (minus the prepended 'LIGHT')
                for obj in bpy.data.objects:
                    if obj.data == data:
                        linked_lights.append(obj.name)
            else:
                mat = bpy.data.materials[(dataname[3:])]  # actual data name (minus the prepended 'MAT')
                for obj in bpy.data.objects:
                    if obj.type == 'MESH':
                        for slot in obj.material_slots:
                            if slot.material == mat:
                                linked_lights.append(obj.name)

        statelist = stringToNestedList(scene.gaf_props.LightsHiddenRecord, True)

        if showhide:  # Enter Solo mode
            bpy.ops.gaffer.refresh_lights()
            scene.gaf_props.SoloActive = light
            getHiddenStatus(scene, stringToNestedList(scene.gaf_props.Lights, True))
            for l in statelist:  # first check if lights still exist
                if l[0] != "WorldEnviroLight":
                    try:
                        obj = bpy.data.objects[l[0]]
                    except:
                        # TODO not sure if this ever happens, if it does, doesn't it break?
                        getHiddenStatus(scene, stringToNestedList(scene.gaf_props.Lights, True))
                        bpy.ops.gaffer.solo()
                        # If one of the lights has been deleted/changed, update the list and dont restore visibility
                        return {'FINISHED'}

            for l in statelist:  # then restore visibility
                if l[0] != "WorldEnviroLight":
                    obj = bpy.data.objects[l[0]]
                    if obj.name not in blacklist:
                        if obj.name == light or obj.name in linked_lights:
                            obj.hide_viewport = False
                            obj.hide_render = False
                        else:
                            obj.hide_viewport = True
                            obj.hide_render = True

            if context.scene.render.engine == 'CYCLES':
                if worldsolo:
                    if not scene.gaf_props.WorldVis:
                        scene.gaf_props.WorldVis = True
                else:
                    if scene.gaf_props.WorldVis:
                        scene.gaf_props.WorldVis = False

        else:  # Exit solo
            oldlight = scene.gaf_props.SoloActive
            scene.gaf_props.SoloActive = ''
            for l in statelist:
                if l[0] != "WorldEnviroLight":
                    try:
                        obj = bpy.data.objects[l[0]]
                    except:
                        # TODO not sure if this ever happens, if it does, doesn't it break?
                        bpy.ops.gaffer.refresh_lights()
                        getHiddenStatus(scene, stringToNestedList(scene.gaf_props.Lights, True))
                        scene.gaf_props.SoloActive = oldlight
                        bpy.ops.gaffer.solo()
                        return {'FINISHED'}
                    if obj.name not in blacklist:
                        obj.hide_viewport = castBool(l[1])
                        obj.hide_render = castBool(l[2])
                elif context.scene.render.engine == 'CYCLES':
                    scene.gaf_props.WorldVis = castBool(l[1])
                    scene.gaf_props.WorldReflOnly = castBool(l[2])

        return {'FINISHED'}


class GAFFER_OT_light_use_nodes(bpy.types.Operator):

    'Make this light use nodes'
    bl_idname = 'gaffer.light_use_nodes'
    bl_label = 'Use Nodes'
    light: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects[self.light]
        if obj.type == 'LIGHT':
            obj.data.use_nodes = True
        bpy.ops.gaffer.refresh_lights()
        return {'FINISHED'}


class GAFFER_OT_node_set_strength(bpy.types.Operator):

    "Use this node's first Value input as the Strength slider for this light in the Gaffer panel"
    bl_idname = 'gaffer.node_set_strength'
    bl_label = 'Set as Gaffer Strength'

    @classmethod
    def poll(cls, context):
        if context.space_data.type == 'NODE_EDITOR':
            return not context.space_data.pin
        else:
            return False

    def execute(self, context):
        setGafferNode(context, 'STRENGTH')
        return {'FINISHED'}


class GAFFER_OT_refresh_light_list(bpy.types.Operator):

    'Refresh the list of lights'
    bl_idname = 'gaffer.refresh_lights'
    bl_label = 'Refresh Light List'

    def execute(self, context):
        scene = context.scene

        refresh_light_list(scene)
        
        self.report({'INFO'}, "Light list refreshed")
        if scene.gaf_props.SoloActive == '':
            getHiddenStatus(scene, stringToNestedList(scene.gaf_props.Lights, True))
        refresh_bgl()  # update the radius/label as well
        return {'FINISHED'}


class GAFFER_OT_apply_exposure(bpy.types.Operator):

    'Apply Exposure\nAdjust the brightness of all lights by the exposure amount and set the exposure slider back to 0'
    bl_idname = 'gaffer.apply_exposure'
    bl_label = 'Apply Exposure'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.render.engine in supported_renderers

    def execute(self, context):
        scene = context.scene
        refresh_light_list(scene)
        gaf_props = scene.gaf_props
        lights_str = gaf_props.Lights
        lights = stringToNestedList(lights_str)

        evs = scene.view_settings.exposure  # CM exposure is set in EVs/stops
        exposure = pow(2, evs)  # Linear exposure adjustment

        scene.view_settings.exposure = 0

        # Almost all of this is copy pasted from ui.draw_cycles_UI.
        # TODO make a function for finding the strength property.
        for item in lights:
            if item[0] != "":
                light = scene.objects[item[0][1:-1]]  # drop the apostrophes
                if light.type == 'LIGHT':
                    material = None
                    if light.data.use_nodes:
                        node_strength = light.data.node_tree.nodes[item[2][1:-1]]
                    else:
                        doesnt_use_nodes = True

                    if light.data.type == 'AREA' and light.data.cycles.is_portal:
                        is_portal = True
                else:
                    material = bpy.data.materials[item[1][1:-1]]
                    if material.use_nodes:
                        node_strength = material.node_tree.nodes[item[2][1:-1]]
                    else:
                        doesnt_use_nodes = True

                if light.data.use_nodes:
                    if item[3].startswith("'"):
                        socket_strength_str = str(item[3][1:-1])
                    else:
                        socket_strength_str = str(item[3])

                    if socket_strength_str.startswith('o'):
                        socket_strength_type = 'o'
                        socket_strength = int(socket_strength_str[1:])
                    elif socket_strength_str.startswith('i'):
                        socket_strength_type = 'i'
                        socket_strength = int(socket_strength_str[1:])
                    else:
                        socket_strength_type = 'i'
                        socket_strength = int(socket_strength_str)

                    strength_sockets = node_strength.inputs
                    if socket_strength_type == 'o':
                        strength_sockets = node_strength.outputs
                    try:
                        if (((socket_strength_type == 'i' and not strength_sockets[socket_strength].is_linked) or
                            (socket_strength_type == 'o' and strength_sockets[socket_strength].is_linked)) and
                                hasattr(strength_sockets[socket_strength], "default_value")):
                            strength_sockets[socket_strength].default_value *= exposure
                        else:
                            self.report({'ERROR'},
                                        item[0] + " does not have a valid node. Try refreshing the light list.")
                    except:
                        self.report({'ERROR'}, item[0] + " does not have a valid node. Try refreshing the light list.")
                else:
                    self.report({'WARNING'}, item[0] + " does not use nodes and can't be adjusted.")

        # World
        if gaf_props.hdri_handler_enabled:
            gaf_props.hdri_brightness = gaf_props.hdri_brightness + evs
            if gaf_props.hdri_use_separate_brightness:
                gaf_props.hdri_background_brightness = gaf_props.hdri_background_brightness + evs
        else:
            world = scene.world
            if world.use_nodes:
                backgrounds = []  # make a list of all linked Background shaders, use the right-most one
                background = None
                for node in world.node_tree.nodes:
                    if node.type == 'BACKGROUND':
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
                        i = 0  # Failsafe in case of infinite loop (which can happen from accidental cyclic links)
                        while strength_node is None and i < 1000:  # limitted to 100 chained nodes
                            i += 1
                            connected_inputs = False
                            if temp_current_node:
                                current_node = temp_current_node
                            for socket in current_node.inputs:
                                # stop at first node with an unconnected Value socket
                                if socket.type == 'VALUE' and not socket.is_linked:
                                    strength_node = current_node
                                else:
                                    if socket.is_linked:
                                        temp_current_node = socket.links[0].from_node

                        if strength_node:
                            for socket in strength_node.inputs:
                                if socket.type == 'VALUE' and not socket.is_linked:  # use first color socket
                                    socket.default_value = socket.default_value * exposure
                                    break
                    else:
                        background.inputs[1].default_value = background.inputs[1].default_value * exposure

        return {'FINISHED'}


class GAFFER_OT_create_enviro_widget(bpy.types.Operator):

    'Create an Empty which drives the rotation of the background texture'
    bl_idname = 'gaffer.envwidget'
    bl_label = 'Create Enviro Rotation Widget (EXPERIMENTAL)'
    radius: bpy.props.FloatProperty(default=16.0,
                                    description="How big the created empty should be (distance from center to edge)")

    # TODO add op to delete widget and drivers
    # TODO add op to select widget (poll if it exists)
    # TODO poll for supported vector input, uses nodes, widget doesn't already exist
    
    '''
        This is an experimental function.
        It's barely usable at present, but blender lacks a few important things to make it really useful:
            Cannot draw bgl over viewport render (can't see what you're doing or interact with a custom widget)
            Can't draw a texture on a sphere when the rest of the viewport is solid-shaded
            World rotation is pretty weird, doesn't match up to rotation of a 3d sphere
        For those reasons, this won't be included in the UI, but the code might as well stay here for future use.
    '''

    def execute(self, context):
        scene = context.scene
        nodes = scene.world.node_tree.nodes

        # Get mapping nodes
        mapping_nodes = []
        for node in nodes:
            if node.type == 'MAPPING':
                mapping_nodes.append(node)
        if not mapping_nodes:
            pass  # TODO handle when no mapping nodes

        n = mapping_nodes[0]  # use rotation of first mapping node
        map_rotation = [n.rotation[0],
                        n.rotation[1],
                        n.rotation[2]]

        '''
            POINT is the default vector type, but rotates inversely to the widget.
            Setting the vector type to TEXTURE behaves as expected,
            but we must invert the rotation values to keep the same visual rotation.
        '''
        if n.vector_type == 'POINT':
            map_rotation = [i * -1 for i in map_rotation]

        widget_data = bpy.data.objects.new("Environment Rotation Widget", None)
        scene.objects.link(widget_data)
        widget = scene.objects["Environment Rotation Widget"]
        widget.location = scene.cursor.location
        widget.rotation_euler = map_rotation
        widget.empty_draw_type = 'SPHERE'
        widget.empty_draw_size = self.radius
        widget.layers = scene.layers

        # TODO handle if mapping node has drivers or is animated (ask to override or ignore)

        for node in mapping_nodes:
            node.vector_type = 'TEXTURE'
            # TODO check it works when node name includes math (e.g. "mapping*2")
            dr = node.driver_add("rotation")

            # X axis:
            dr[0].driver.type = 'AVERAGE'
            var = dr[0].driver.variables.new()
            var.name = "x-rotation"
            var.type = 'TRANSFORMS'
            target = var.targets[0]
            target.id = widget
            target.transform_type = 'ROT_X'

            # Y axis:
            dr[1].driver.type = 'AVERAGE'
            var = dr[1].driver.variables.new()
            var.name = "y-rotation"
            var.type = 'TRANSFORMS'
            target = var.targets[0]
            target.id = widget
            target.transform_type = 'ROT_Y'

            # Z axis:
            dr[2].driver.type = 'AVERAGE'
            var = dr[2].driver.variables.new()
            var.name = "z-rotation"
            var.type = 'TRANSFORMS'
            target = var.targets[0]
            target.id = widget
            target.transform_type = 'ROT_Z'

        return {'FINISHED'}


class GAFFER_OT_link_sky_to_sun(bpy.types.Operator):
    bl_idname = "gaffer.link_sky_to_sun"
    bl_label = "Link Sky Texture:"
    bl_options = {'REGISTER', 'UNDO'}
    node_name: bpy.props.StringProperty(default="")

    # Thanks to oscurart for the original script off which this is based!
    # http://bit.ly/blsunsky

    def execute(self, context):

        tree = context.scene.world.node_tree
        node = tree.nodes[self.node_name]
        lightob = bpy.data.objects[context.scene.gaf_props.SunObject]

        if tree.animation_data:
            if tree.animation_data.action:
                for fc in tree.animation_data.action.fcurves:
                    if fc.data_path == ("nodes[\"" + node.name + "\"].sun_direction"):
                        self.report({'ERROR'}, "Sun Direction is animated")
                        return {'CANCELLED'}
            elif tree.animation_data.drivers:
                for dr in tree.animation_data.drivers:
                    if dr.data_path == ("nodes[\"" + node.name + "\"].sun_direction"):
                        self.report({'ERROR'}, "Sun Direction has drivers")
                        return {'CANCELLED'}

        dr = node.driver_add("sun_direction")

        nodename = ""
        for ch in node.name:
            if ch.isalpha():  # make sure node name can be used in expression
                nodename += ch
        # Create unique variable name for each node
        varname = nodename + "_" + str(context.scene.gaf_props.VarNameCounter)
        context.scene.gaf_props.VarNameCounter += 1

        dr[0].driver.expression = varname
        var = dr[0].driver.variables.new()
        var.name = varname
        var.type = 'SINGLE_PROP'
        var.targets[0].id = lightob
        var.targets[0].data_path = 'matrix_world[2][0]'
        # Y
        dr[1].driver.expression = varname
        var = dr[1].driver.variables.new()
        var.name = varname
        var.type = 'SINGLE_PROP'
        var.targets[0].id = lightob
        var.targets[0].data_path = 'matrix_world[2][1]'
        # Y
        dr[2].driver.expression = varname
        var = dr[2].driver.variables.new()
        var.name = varname
        var.type = 'SINGLE_PROP'
        var.targets[0].id = lightob
        var.targets[0].data_path = 'matrix_world[2][2]'

        return {'FINISHED'}


class GAFFER_OT_aim_light(bpy.types.Operator):

    "Point the selected lights at a target"
    bl_idname = 'gaffer.aim'
    bl_label = 'Aim'
    target_type: bpy.props.StringProperty()

    def aim(self, context, obj, target=[0, 0, 0]):
        # Thanks to @kilbee for cleaning my crap up here :) See: https://github.com/gregzaal/Gaffer/commit/b920092
        obj_loc = obj.matrix_world.to_translation()
        direction = target - obj_loc
        # point obj '-Z' and use its 'Y' as up
        rot_quat = direction.to_track_quat('-Z', 'Y')
        if obj.rotation_mode == 'QUATERNION':
            obj.rotation_quaternion = rot_quat
        else:
            obj.rotation_euler = rot_quat.to_euler()

    def execute(self, context):
        if self.target_type == 'CURSOR':
            # Aim all selected objects at cursor
            objects = context.selected_editable_objects
            if not objects:
                self.report({'ERROR'}, "No selected objects!")
                return {'CANCELLED'}
            for obj in context.selected_editable_objects:
                self.aim(context, obj, context.scene.cursor.location)

            return {'FINISHED'}

        elif self.target_type == 'SELECTED':
            # Aim the active object at the average location of all other selected objects
            active = context.view_layer.objects.active
            objects = [obj for obj in context.selected_objects if obj != active]
            num_objects = len(objects)

            if not active:
                self.report({'ERROR'}, "You need an active object!")
                return {'CANCELLED'}
            elif num_objects == 0:
                if active.select_get():
                    self.report({'ERROR'}, "Select more than one object!")
                else:
                    self.report({'ERROR'}, "No selected objects!")
                return {'CANCELLED'}

            total_x = 0
            total_y = 0
            total_z = 0

            for obj in objects:
                total_x += obj.location.x
                total_y += obj.location.y
                total_z += obj.location.z

            avg_x = total_x / num_objects
            avg_y = total_y / num_objects
            avg_z = total_z / num_objects

            self.aim(context, active, Vector((avg_x, avg_y, avg_z)))

            return {'FINISHED'}

        elif self.target_type == 'ACTIVE':
            # Aim the selected objects at the active object
            active = context.view_layer.objects.active
            objects = [obj for obj in context.selected_objects if obj != active]
            if not active:
                self.report({'ERROR'}, "No active object!")
                return {'CANCELLED'}
            elif not objects:
                self.report({'ERROR'}, "No selected objects!")
                return {'CANCELLED'}

            for obj in objects:
                self.aim(context, obj, active.location)

            return {'FINISHED'}

        return {'CANCELLED'}


class GAFFER_OT_aim_light_with_view(bpy.types.Operator):

    'Aim the active object using the 3D view camera'
    bl_idname = 'gaffer.aim_view'
    bl_label = 'Aim With View'

    old_cam = None
    old_lock = None
    old_transf = None

    @classmethod
    def poll(cls, context):
        return context.space_data.type == 'VIEW_3D' and context.object

    def modal(self, context, event):
        obj = context.object
        if (event.type in ('RET', 'SPACE') or
                (event.type == 'LEFTMOUSE' and event.value != 'CLICK_DRAG')):  # Some weird pie menu bug
            bpy.ops.view3d.view_camera()
            context.scene.camera = self.old_cam
            context.space_data.lock_camera = self.old_lock
            context.area.header_text_set(None)
            return {'FINISHED'}
        elif event.type in ('RIGHTMOUSE', 'ESC'):
            bpy.ops.view3d.view_camera()
            context.scene.camera = self.old_cam
            context.space_data.lock_camera = self.old_lock
            obj.location = self.old_transf[0]
            obj.rotation_quaternion = self.old_transf[1]
            obj.rotation_euler = self.old_transf[2]
            context.area.header_text_set(None)
            return {'CANCELLED'}
        elif event.type in ('MOUSEMOVE',
                            'INBETWEEN_MOUSEMOVE',
                            'MIDDLEMOUSE',
                            'WHEELDOWNMOUSE',
                            'WHEELUPMOUSE',
                            'LEFT_CTRL',
                            'LEFT_SHIFT',
                            'LEFT_ALT'):
            # Only allow navigation keys to prevent user from changing camera or doing anything else unexpected
            return {'PASS_THROUGH'}
        else:
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if not context.object:
            self.report({'ERROR'}, "No active object")
            return {'CANCELLED'}

        if context.space_data.type != 'VIEW_3D':
            self.report({'ERROR'}, "Must be run from the 3D view")
            return {'CANCELLED'}

        obj = context.object
        self.old_cam = context.scene.camera
        self.old_lock = context.space_data.lock_camera
        self.old_transf = [obj.location.copy(), obj.rotation_quaternion.copy(), obj.rotation_euler.copy()]
        context.scene.camera = obj
        context.space_data.lock_camera = True
        bpy.ops.view3d.view_camera()
        context.area.header_text_set("LMB/Enter/Space: Confirm    Esc/RMB: Cancel")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class GAFFER_OT_show_light_radius(bpy.types.Operator):

    'Display a circle around each light showing their radius'
    bl_idname = 'gaffer.show_radius'
    bl_label = 'Show Radius'

    # CoDEmanX wrote a lot of this - thanks sir!

    _handle = None

    @staticmethod
    def handle_add(self, context):
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_radius,
                                                              (context,),
                                                              'WINDOW',
                                                              'POST_VIEW')
        GAFFER_OT_show_light_radius._handle = self._handle

    @staticmethod
    def handle_remove(context):
        if GAFFER_OT_show_light_radius._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(GAFFER_OT_show_light_radius._handle, 'WINDOW')
        GAFFER_OT_show_light_radius._handle = None

    def draw_callback_radius(self, context):
        scene = context.scene
        region = context.region
        shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')

        if not context.space_data.overlay.show_overlays:
            return

        for item in self.objects:
            obj = item[0]
            if not scene.gaf_props.LightRadiusSelectedOnly or obj.select_get():
                if obj:
                    if obj.data:
                        if obj.data.type in ['POINT', 'SUN', 'SPOT']:  # in case user changes the type while running
                            # TODO check if this is still needed for Eevee
                            if not (scene.render.engine != 'CYCLES' and obj.data.shadow_method == 'NOSHADOW'):
                                if (obj in context.visible_objects and
                                        obj.name not in [o.name for o in scene.gaf_props.Blacklist]):
                                    if scene.gaf_props.LightRadiusUseColor:
                                        if item[1][0] == 'BLACKBODY':
                                            color = convert_temp_to_RGB(item[1][1].inputs[0].default_value)
                                        elif item[1][0] == 'WAVELENGTH':
                                            color = convert_wavelength_to_RGB(item[1][1].inputs[0].default_value)
                                        else:
                                            color = item[1]
                                    else:
                                        color = scene.gaf_props.DefaultRadiusColor
                                    
                                    bgl.glEnable(bgl.GL_BLEND)
                                    # Anti-aliasing; Gives bad results in 2.8, leaving here in case of future fix.
                                    # bgl.glEnable(bgl.GL_POLYGON_SMOOTH)
                                    if scene.gaf_props.LightRadiusXray:
                                        bgl.glClear(bgl.GL_DEPTH_BUFFER_BIT)

                                    rv3d = context.region_data
                                    view = rv3d.view_matrix
                                    persp = rv3d.perspective_matrix

                                    radius = obj.data.shadow_soft_size
                                    obj_matrix_world = obj.matrix_world
                                    origin = obj.matrix_world.translation

                                    view_mat = context.space_data.region_3d.view_matrix
                                    view_dir = view_mat.to_3x3()[2]
                                    up = Vector((0, 0, 1))

                                    angle = up.angle(view_dir)
                                    axis = up.cross(view_dir)

                                    mat = Matrix.Translation(origin) @ Matrix.Rotation(angle, 4, axis)

                                    if scene.gaf_props.LightRadiusDrawType == 'dotted':
                                        sides = 24
                                    else:
                                        sides = 64

                                    verts = []
                                    for i in range(sides):
                                        cosine = radius * cos(i * 2 * pi / sides)
                                        sine = radius * sin(i * 2 * pi / sides)
                                        vec = Vector((cosine, sine, 0))
                                        c = (mat@vec)
                                        verts.append((c.x, c.y, c.z))
                                    if scene.gaf_props.LightRadiusDrawType != 'filled':
                                        radius = radius * 0.9  # TODO thickness option
                                        for i in range(sides):
                                            cosine = radius * cos(i * 2 * pi / sides)
                                            sine = radius * sin(i * 2 * pi / sides)
                                            vec = Vector((cosine, sine, 0))
                                            c = (mat@vec)
                                            verts.append((c.x, c.y, c.z))
                                    else:
                                        vec = Vector((0, 0, 0))
                                        c = (mat@vec)
                                        verts.append((c.x, c.y, c.z))

                                    indices = []
                                    if scene.gaf_props.LightRadiusDrawType != 'filled':
                                        for i in range(sides):
                                            if scene.gaf_props.LightRadiusDrawType == 'dotted' and i % 2:
                                                continue
                                            a = i
                                            b = i + 1
                                            c = i + 1 + sides
                                            d = i + sides
                                            indices.append((a, b, c))
                                            indices.append((a, c, d))
                                            if i == sides - 2:
                                                # We'll do the last 2 tris manually, math is a bit over my head :)
                                                break
                                        if scene.gaf_props.LightRadiusDrawType != 'dotted':
                                            indices.append((0,
                                                            sides - 1,
                                                            sides * 2 - 1))
                                            indices.append((0,
                                                            sides,
                                                            sides * 2 - 1))
                                    else:
                                        for i in range(sides):
                                            a = i
                                            b = (i + 1) % sides
                                            indices.append((a, b, sides))
                                    shader.bind()
                                    shader.uniform_float("color", (color[0], color[1], color[2],
                                                                   scene.gaf_props.LightRadiusAlpha))
                                    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)
                                    batch.draw(shader)

                                    bgl.glDisable(bgl.GL_BLEND)
                                    # bgl.glDisable(bgl.GL_POLYGON_SMOOTH)
    
    def modal(self, context, event):
        if context.scene.gaf_props.IsShowingRadius:
            if context.area:
                context.area.tag_redraw()
                return {'PASS_THROUGH'}
            else:
                context.scene.gaf_props.IsShowingRadius = False
                GAFFER_OT_show_light_radius.handle_remove(context)
                return {'FINISHED'}
        else:
            context.scene.gaf_props.IsShowingRadius = False
            GAFFER_OT_show_light_radius.handle_remove(context)
            return {'FINISHED'}

    def invoke(self, context, event):
        scene = context.scene

        if scene.gaf_props.IsShowingRadius:
            scene.gaf_props.IsShowingRadius = False
            GAFFER_OT_show_light_radius.handle_remove(context)
            return {'FINISHED'}
        elif context.area.type == 'VIEW_3D':
            scene.gaf_props.IsShowingRadius = True
            
            context.window_manager.modal_handler_add(self)

            GAFFER_OT_show_light_radius.handle_add(self, context)

            self.objects = []
            for obj in scene.objects:
                # It doesn't make sense to try show the radius for mesh, area or hemi lights.
                if obj.type == 'LIGHT':
                    if obj.data.type in ['POINT', 'SUN', 'SPOT']:
                        color = scene.gaf_props.DefaultRadiusColor
                        if scene.render.engine == 'CYCLES' and obj.data.use_nodes:
                            nodes = obj.data.node_tree.nodes
                            socket_color = 0
                            node_color = None
                            emissions = []  # make a list of all linked Emission shaders, use the right-most one
                            for node in nodes:
                                if node.type == 'EMISSION':
                                    if node.outputs[0].is_linked:
                                        emissions.append(node)
                            if emissions:
                                node_color = sorted(emissions, key=lambda x: x.location.x, reverse=True)[0]

                                if not node_color.inputs[0].is_linked:
                                    color = node_color.inputs[0].default_value
                                else:
                                    from_node = node_color.inputs[0].links[0].from_node
                                    if from_node.type == 'RGB':
                                        color = from_node.outputs[0].default_value
                                    elif from_node.type == 'BLACKBODY':
                                        color = ['BLACKBODY', from_node]
                                    elif from_node.type == 'WAVELENGTH':
                                        color = ['WAVELENGTH', from_node]
                        else:
                            color = obj.data.color

                        self.objects.append([obj, color])

            return {'RUNNING_MODAL'}

        else:
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}


class GAFFER_OT_show_light_label(bpy.types.Operator):

    'Display the name of each light in the viewport'
    bl_idname = 'gaffer.show_label'
    bl_label = 'Show Label'

    _handle = None

    @staticmethod
    def handle_add(self, context):
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_label,
                                                              (context,),
                                                              'WINDOW',
                                                              'POST_PIXEL')
        GAFFER_OT_show_light_label._handle = self._handle

    @staticmethod
    def handle_remove(context):
        if GAFFER_OT_show_light_label._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(GAFFER_OT_show_light_label._handle, 'WINDOW')
        GAFFER_OT_show_light_label._handle = None

    def alignment(self, x, y, width, height, margin):
        align = bpy.context.scene.gaf_props.LabelAlign

        # X:
        if align in ['t', 'c', 'b']:  # middle
            x = x - (width / 2)
        elif align in ['tl', 'l', 'bl']:  # left
            x = x - (width + margin)
        elif align in ['tr', 'r', 'br']:  # right
            x = x + margin

        # Y:
        if align in ['l', 'c', 'r']:  # middle
            y = y - (height / 2)
        elif align in ['tl', 't', 'tr']:  # top
            y = y + margin
        elif align in ['bl', 'b', 'br']:  # bottom
            y = y - (height + margin)

        return x, y + 3

    def draw_callback_label(self, context):
        scene = context.scene

        if not context.space_data.overlay.show_overlays:
            return

        # font_size_factor is used to scale the rectangles based on the font size and DPI,
        # measured against a font size of 62
        font_size_factor = (scene.gaf_props.LabelFontSize / 62) * (context.preferences.system.dpi / 72)
        draw_type = scene.gaf_props.LabelDrawType
        background_color = scene.gaf_props.DefaultLabelBGColor
        text_color = scene.gaf_props.LabelTextColor
        shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')

        for item in self.objects:
            obj = item[0]
            if obj in context.visible_objects and obj.name not in [o.name for o in scene.gaf_props.Blacklist]:
                if item[1][0] == 'BLACKBODY':
                    color = convert_temp_to_RGB(item[1][1].inputs[0].default_value)
                elif item[1][0] == 'WAVELENGTH':
                    color = convert_wavelength_to_RGB(item[1][1].inputs[0].default_value)
                else:
                    color = item[1]

                region = context.region
                rv3d = context.space_data.region_3d
                loc = location_3d_to_region_2d(region, rv3d, obj.matrix_world.translation)
                if loc:  # sometimes this is None if lights are out of view
                    x, y = loc

                    font_id = 1  # Monospace font
                    char_width = 37 * font_size_factor
                    height = 65 * font_size_factor
                    width = len(obj.name) * int(char_width) + 1
                    if item[2]:
                        width_2 = len(item[2]) * int(char_width) + 1
                        width = max(width * 0.8, width_2)

                    x, y = self.alignment(
                        x,
                        y,
                        width,
                        height if not item[2] else height - height * 0.8 - 4,
                        scene.gaf_props.LabelMargin * font_size_factor
                    )
                    y_sub = y - (8 * font_size_factor) - height

                    if draw_type != 'color_text':
                        # Draw background rectangles
                        bgl.glEnable(bgl.GL_BLEND)
                        shader.bind()
                        if draw_type == 'color_bg' and scene.gaf_props.LabelUseColor:
                            shader.uniform_float("color", (color[0], color[1], color[2], scene.gaf_props.LabelAlpha))
                        else:
                            shader.uniform_float("color", (background_color[0],
                                                           background_color[1],
                                                           background_color[2],
                                                           scene.gaf_props.LabelAlpha))

                        x1 = x
                        x2 = x1 + width
                        if not item[2]:
                            y1 = y - (8 * font_size_factor)
                            y2 = y1 + height
                        else:
                            y1 = y - (8 * font_size_factor) - height * 0.8 - 4
                            y2 = y1 + height + height * 0.8 + 4

                        draw_rounded_rect(shader, x1, y1, x2, y2, 20 * font_size_factor)

                        bgl.glDisable(bgl.GL_BLEND)

                    # Draw text
                    if draw_type != 'color_bg' and scene.gaf_props.LabelUseColor:
                        blf.color(font_id,
                                  color[0],
                                  color[1],
                                  color[2],
                                  scene.gaf_props.LabelAlpha if draw_type == 'color_text' else 1.0)
                    else:
                        blf.color(font_id, text_color[0], text_color[1], text_color[2], 1.0)
                    blf.position(font_id, x, y, 0)
                    blf.size(font_id, scene.gaf_props.LabelFontSize, context.preferences.system.dpi)

                    if not item[2]:
                        blf.draw(font_id, obj.name)
                    else:
                        blf.draw(font_id, item[2])
                        blf.position(font_id, x, y_sub, 0)
                        blf.size(font_id, int(scene.gaf_props.LabelFontSize * 0.8), context.preferences.system.dpi)
                        blf.draw(font_id, obj.name)
    
    def modal(self, context, event):
        if context.scene.gaf_props.IsShowingLabel:
            if context.area:
                context.area.tag_redraw()
                return {'PASS_THROUGH'}
            else:
                context.scene.gaf_props.IsShowingLabel = False
                GAFFER_OT_show_light_label.handle_remove(context)
                return {'FINISHED'}
        else:
            context.scene.gaf_props.IsShowingLabel = False
            GAFFER_OT_show_light_label.handle_remove(context)
            return {'FINISHED'}

    def invoke(self, context, event):
        scene = context.scene

        if scene.gaf_props.IsShowingLabel:
            scene.gaf_props.IsShowingLabel = False
            GAFFER_OT_show_light_label.handle_remove(context)
            return {'FINISHED'}
        elif context.area.type == 'VIEW_3D':
            scene.gaf_props.IsShowingLabel = True
            
            context.window_manager.modal_handler_add(self)

            GAFFER_OT_show_light_label.handle_add(self, context)

            self.objects = []
            for obj in scene.objects:
                color = scene.gaf_props.DefaultLabelBGColor
                nodes = None
                data = None
                if obj.type == 'LIGHT':
                    if obj.data.users > 1:
                        data = obj.data.name
                    if scene.render.engine == 'CYCLES' and obj.data.use_nodes:
                        nodes = obj.data.node_tree.nodes
                elif scene.render.engine == 'CYCLES' and obj.type == 'MESH' and len(obj.material_slots) > 0:
                    for slot in obj.material_slots:
                        if slot.material:
                            if slot.material.use_nodes:
                                if [node for node in slot.material.node_tree.nodes if node.type == 'EMISSION']:
                                    nodes = slot.material.node_tree.nodes
                                    if slot.material.users > 1:
                                        data = slot.material.name
                                    break  # only use first emission material in slots

                if nodes:
                    node_color = None
                    emissions = []  # make a list of all linked Emission shaders, use the right-most one
                    for node in nodes:
                        if node.type == 'EMISSION' and node.name != "Emission Viewer":
                            if node.outputs[0].is_linked:
                                emissions.append(node)
                    if emissions:
                        node_color = sorted(emissions, key=lambda x: x.location.x, reverse=True)[0]

                        if not node_color.inputs[0].is_linked:
                            color = node_color.inputs[0].default_value
                        else:
                            from_node = node_color.inputs[0].links[0].from_node
                            if from_node.type == 'RGB':
                                color = from_node.outputs[0].default_value
                            elif from_node.type == 'BLACKBODY':
                                color = ['BLACKBODY', from_node]
                            elif from_node.type == 'WAVELENGTH':
                                color = ['WAVELENGTH', from_node]

                        self.objects.append([obj, color, data])

                if obj.type == 'LIGHT' and not nodes:  # is a light but doesnt use_nodes
                    color = obj.data.color
                    self.objects.append([obj, color, data])

            return {'RUNNING_MODAL'}

        else:
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}


class GAFFER_OT_refresh_bgl(bpy.types.Operator):

    "Update the radius and label display to account for undetected changes"
    bl_idname = 'gaffer.refresh_bgl'
    bl_label = 'Refresh Radius/Label'

    @classmethod
    def poll(cls, context):
        return context.scene.gaf_props.IsShowingRadius or context.scene.gaf_props.IsShowingLabel

    def execute(self, context):
        refresh_bgl()
        return {'FINISHED'}


class GAFFER_OT_add_blacklisted(bpy.types.Operator):

    "Add the selected objects to the blacklist"
    bl_idname = 'gaffer.blacklist_add'
    bl_label = 'Add'

    @classmethod
    def poll(cls, context):
        return context.selected_objects

    def execute(self, context):
        blacklist = context.scene.gaf_props.Blacklist
        existing = [obj.name for obj in blacklist]
        for obj in context.selected_objects:
            if obj.name not in existing:
                item = blacklist.add()
                item.name = obj.name

        context.scene.gaf_props.BlacklistIndex = len(context.scene.gaf_props.Blacklist) - 1
        return {'FINISHED'}


class GAFFER_OT_remove_blacklisted(bpy.types.Operator):

    "Remove the active list item from the blacklist"
    bl_idname = 'gaffer.blacklist_remove'
    bl_label = 'Remove'

    @classmethod
    def poll(cls, context):
        return context.scene.gaf_props.Blacklist

    def execute(self, context):
        blist = context.scene.gaf_props.Blacklist
        index = context.scene.gaf_props.BlacklistIndex

        blist.remove(index)

        if index >= len(blist):
            context.scene.gaf_props.BlacklistIndex = len(blist) - 1

        return {'FINISHED'}


'''HDRI Operators'''


class GAFFER_OT_detect_hdris(bpy.types.Operator):

    "Look for HDRIs in the chosen folder, matching different resolutions and variants together based on filename"
    bl_idname = 'gaffer.detect_hdris'
    bl_label = 'Detect HDRIs'

    def execute(self, context):
        detect_hdris(self, context)
        return {'FINISHED'}


class GAFFER_OT_hdri_path_edit(bpy.types.Operator, ImportHelper):

    "Select a folder to scan for HDRIs"
    bl_idname = 'gaffer.hdri_path_edit'
    bl_label = 'Select Folder'
    bl_options = {'INTERNAL'}

    directory: bpy.props.StringProperty(
        name='Directory',
        subtype='DIR_PATH',
        default='',
        description='Folder to search in for image files')

    folder_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        hdri_paths = get_persistent_setting('hdri_paths')

        if self.directory in hdri_paths:
            self.report({'ERROR'}, "You've already added this folder")
            return {'CANCELLED'}

        for i, hp in enumerate(hdri_paths):
            if self.directory.startswith(hp) and i != self.folder_index:
                self.report(
                    {'ERROR'},
                    "The folder you selected is a subfolder of another HDRI folder, so it will be scanned already."
                )
                return {'CANCELLED'}

        hdri_paths[self.folder_index] = self.directory
        set_persistent_setting('hdri_paths', hdri_paths)
        update_hdri_path(self, context)
        return {'FINISHED'}


class GAFFER_OT_hdri_path_add(bpy.types.Operator, ImportHelper):

    "Add multiple HDRI folders to detect HDRIs in multiple locations or on different drives"
    bl_idname = 'gaffer.hdri_path_add'
    bl_label = 'Select Folder'
    bl_options = {'INTERNAL'}

    directory: bpy.props.StringProperty(
        name='Directory',
        subtype='DIR_PATH',
        default='',
        description='Folder to search in for image files')

    def execute(self, context):
        hdri_paths = get_persistent_setting('hdri_paths')

        if self.directory in hdri_paths:
            self.report({'ERROR'}, "You've already added this folder")
            return {'CANCELLED'}

        for hp in hdri_paths:
            if self.directory.startswith(hp):
                self.report(
                    {'ERROR'},
                    "The folder you selected is a subfolder of another HDRI folder, so it will be scanned already."
                )
                return {'CANCELLED'}
        
        hdri_paths.append(self.directory)
        set_persistent_setting('hdri_paths', hdri_paths)
        update_hdri_path(self, context)
        return {'FINISHED'}


class GAFFER_OT_hdri_path_remove(bpy.types.Operator):

    "Remove this HDRI folder, don't detect HDRIs from it"
    bl_idname = 'gaffer.hdri_path_remove'
    bl_label = 'Remove HDRI folder'
    bl_options = {'INTERNAL'}

    folder_index: bpy.props.IntProperty(default=0)

    def draw(self, context):
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label(text="Are you sure you want to delete this path?", icon="ERROR")

    def execute(self, context):
        hdri_paths = get_persistent_setting('hdri_paths')
        del(hdri_paths[self.folder_index])
        set_persistent_setting('hdri_paths', hdri_paths)
        update_hdri_path(self, context)
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=250 * dpifac())


class GAFFER_OT_hdri_thumb_gen(bpy.types.Operator):

    "Generate missing thumbnail images for all HDRIs"
    bl_idname = 'gaffer.generate_hdri_thumbs'
    bl_label = 'Generate Thumbnails'
    bl_options = {'INTERNAL'}

    size_limit = 100

    skip_huge_files: bpy.props.BoolProperty(
        name="Skip files larger than " + str(size_limit) + " MB to save time (recommended).",
        description=("If you have big HDRIs (>" + str(size_limit) + " MB) with no smaller resolution available, "
                     "these will be skipped to save time. Disabling this will mean it may take an unreasonable "
                     "amount of time to generate thumbnails. Instead, it would be better if you manually create "
                     "the lower resolution version first in Photoshop/Krita, then click 'Refresh' in Gaffer's "
                     "User Preferences"),
        default=True
    )

    # TODO render diffuse/gloss/plastic spheres instead of just the normal preview
    # option to try to download sphere renders instead of rendering locally,
    # as well as a separate option to upload local renders to help others skip rendering locally again

    def draw(self, context):
        layout = self.layout

        col = layout.column()
        col.label(text="This may take a few minutes, but only has to be done once.")
        col.label(text="The only way to stop this process once you start it is to forcibly close Blender.")
        col.label(text="Due to a bug in Blender 2.8, no progress bar will be shown.")

        col.separator()
        col = layout.column(align=True)
        col.prop(self, 'skip_huge_files')

        if context.scene.gaf_props.ThumbnailsBigHDRIFound:
            col.label(text="Large HDRI files were skipped last time.", icon='ERROR')
            col.label(text="You may wish to disable 'Skip big files', but first read its tooltip.")

    def generate_thumb(self, name, files):
        context = bpy.context
        prefs = context.preferences.addons[__package__].preferences

        chosen_file = ''

        # Check if thumb file came with HDRI
        d = os.path.dirname(files[0])
        for f in os.listdir(d):
            if any(os.path.splitext(f)[0].lower().endswith(e) and name == get_hdri_basename(f) for e in thumb_endings):
                chosen_file = os.path.join(d, f)
                break

        if not chosen_file:
            if len(files) == 1:
                chosen_file = files[0]
            else:
                # First check if there are really small versions
                small_sizes = ['256p', '512p']
                for f in files:
                    for s in small_sizes:
                        if s in f:
                            chosen_file = f
                            break
                    if chosen_file:
                        break

                # Otherwise pick smallest file
                if not chosen_file:
                    file_sizes = {}
                    for f in files:
                        if os.path.splitext(f)[1].lower() in allowed_file_types:
                            if not os.path.splitext(f)[0].lower().endswith('env'):
                                file_sizes[f] = os.path.getsize(f)
                    chosen_file = min(file_sizes, key=file_sizes.get)
        if not chosen_file:
            chosen_file = files[0]  # Safety fallback

        # Create thumbnail
        thumb_file = os.path.join(thumbnail_dir, name + "__thumb_preview.jpg")
        if not os.path.exists(thumb_file):
            filesize = os.path.getsize(chosen_file) / 1024 / 1024
            log('    ' + name + ": " + chosen_file + "  " + str(ceil(filesize)) + " MB", also_print=True)
            
            if filesize < self.size_limit or not self.skip_huge_files:
                cmd = [bpy.app.binary_path]
                cmd.append("--background")
                cmd.append("--factory-startup")
                cmd.append("--python")
                cmd.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "resize.py"))
                cmd.append('--')
                cmd.append(chosen_file)
                cmd.append('200')
                cmd.append(thumb_file)
                run(cmd)
            else:
                log("    Too big", timestamp=False, also_print=True)
                bpy.context.scene.gaf_props.ThumbnailsBigHDRIFound = True

    def execute(self, context):
        log("OP: Generate Thumbnails")
        if not self.skip_huge_files:
            log("Large files included", timestamp=False)

        context.preferences.addons[__package__].preferences.RequestThumbGen = False
        hdris = get_hdri_list()

        progress_begin(context)

        num_hdris = len(hdris)
        threaded = True  # Set to False for debugging

        errors = []
        if threaded:
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=8 if self.skip_huge_files else 4)
            threads = []
            for i, h in enumerate(hdris):
                t = executor.submit(self.generate_thumb, h, hdris[h])
                threads.append(t)

            while (any(t._state != "FINISHED" for t in threads)):
                num_finished = 0
                for tt in threads:
                    if tt._state == "FINISHED":
                        num_finished += 1
                        if tt.result() is not None:
                            errors.append(tt.result())
                progress_update(context,
                                num_finished / num_hdris,
                                "Generating thumbnail: " + str(num_finished + 1) + '/' + str(num_hdris))
                sleep(2)
        else:
            for num_finished, h in enumerate(hdris):
                self.generate_thumb(h, hdris[h])
                progress_update(context,
                                num_finished / num_hdris,
                                "Generating thumbnail: " + str(num_finished + 1) + '/' + str(num_hdris))

        if errors:
            for e in errors:
                print(e)
        else:
            success = True

        progress_end(context)

        log("Successfully finished generating thumbnails")

        refresh_previews()

        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420 * dpifac())


class GAFFER_OT_hdri_jpg_gen(bpy.types.Operator):

    "Generate regular JPG and darkened JPG from HDRI"
    bl_idname = 'gaffer.generate_jpgs'
    bl_label = 'Generate JPGs'
    bl_options = {'INTERNAL'}

    def generate_jpgs(self, context, name):
        gaf_props = context.scene.gaf_props

        fp = get_variation(name, mode="biggest")

        img_exists = False
        for m in ['', '_dark']:  # Run twice, once for normal JPG and once for darkened JPG
            jpg_path = os.path.join(jpg_dir, name + m + ".jpg")
            if not os.path.exists(jpg_path):
                if not img_exists:
                    img = bpy.data.images.load(fp, check_existing=False)
                    img_exists = True
                darkened = m == '_dark'
                save_image(context, img, jpg_path, 'JPEG', -4 if darkened else 0)
        if img_exists:
            bpy.data.images.remove(img)

    def execute(self, context):
        gaf_props = context.scene.gaf_props
        gaf_props.RequestJPGGen = False
        gen_all = gaf_props.hdri_jpg_gen_all

        if gen_all:
            hdris = get_hdri_list()
            num_hdris = len(hdris)
            progress_begin(context)
            for i, hdri in enumerate(hdris):
                progress_update(context, i / num_hdris, "Generating JPG: " + str(i + 1) + '/' + str(num_hdris))
                print('(' + str(i + 1) + '/' + str(num_hdris) + ') Generating JPG for ' + hdri + ' ...')
                self.generate_jpgs(context, hdri)
            print("Done!")
            progress_end(context)
        else:
            self.generate_jpgs(context, gaf_props.hdri)

        setup_hdri(self, context)

        return {'FINISHED'}


class GAFFER_OT_hdri_clear_search(bpy.types.Operator):

    "Clear the search, show all HDRIs"
    bl_idname = 'gaffer.clear_search'
    bl_label = 'Clear'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.scene.gaf_props.hdri_search = ""
        
        return {'FINISHED'}


class GAFFER_OT_hdri_paddles(bpy.types.Operator):

    "Switch to the next/previous HDRI"
    bl_idname = 'gaffer.hdri_paddles'
    bl_label = 'Next/Previous'
    bl_options = {'INTERNAL'}
    do_next: bpy.props.BoolProperty()

    def execute(self, context):
        gaf_props = context.scene.gaf_props
        hdris = get_hdri_list(use_search=True)
        current_hdri = gaf_props.hdri
        current_index = -1
        list_hdris = list(hdris)
        first_hdri = list_hdris[0]
        last_hdri = list_hdris[-1]

        if current_hdri == last_hdri and self.do_next:
            gaf_props.hdri = first_hdri
            return {'FINISHED'}
        elif current_hdri == first_hdri and not self.do_next:
            gaf_props.hdri = last_hdri
            return {'FINISHED'}
        else:
            current_index = list_hdris.index(current_hdri)
            gaf_props.hdri = list_hdris[current_index + 1] if self.do_next else list_hdris[current_index - 1]
            return {'FINISHED'}


class GAFFER_OT_hdri_variation_paddles(bpy.types.Operator):

    "Switch to the next/previous HDRI variation"
    bl_idname = 'gaffer.hdri_variation_paddles'
    bl_label = 'Next/Previous'
    bl_options = {'INTERNAL'}
    do_next: bpy.props.BoolProperty()

    def execute(self, context):
        gaf_props = context.scene.gaf_props
        variations = get_hdri_list()[gaf_props.hdri]
        last_var = len(variations) - 1
        adj = 1 if self.do_next else -1

        gaf_props['hdri_variation'] = min(last_var, max(0, gaf_props['hdri_variation'] + adj))
        update_variation(self, context)
        return {'FINISHED'}


class GAFFER_OT_hdri_add_tag(bpy.types.Operator):

    "Add this tag to the current HDRI"
    bl_idname = 'gaffer.add_tag'
    bl_label = 'Add Tag'
    bl_options = {'INTERNAL'}
    hdri: bpy.props.StringProperty()
    tag: bpy.props.StringProperty()

    def execute(self, context):
        set_tag(self.hdri, self.tag)
        
        return {'FINISHED'}


class GAFFER_OT_hdri_random(bpy.types.Operator):

    "Switch to a random HDRI"
    bl_idname = 'gaffer.hdri_random'
    bl_label = 'Random'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        gaf_props = context.scene.gaf_props
        hdris = get_hdri_list(use_search=True)

        if len(hdris) <= 1:
            self.report({'WARNING'}, "No more HDRIs found")
            return {'FINISHED'}

        from random import choice
        random_hdri = gaf_props.hdri
        while random_hdri == gaf_props.hdri:  # ensure the same HDRI is not chosen twice in a row
            random_hdri = choice(list(hdris))

        gaf_props.hdri = random_hdri
        
        return {'FINISHED'}


class GAFFER_OT_hdri_reset(bpy.types.Operator):

    ("Reset all HDRI adjustments (rotation, brightness, etc.) to their default values.\n"
     "Hold shift to load factory default values instead of your saved defaults")
    bl_idname = 'gaffer.hdri_reset'
    bl_label = 'Reset'
    bl_options = {'INTERNAL'}

    hdri: bpy.props.StringProperty()
    factory: bpy.props.BoolProperty()

    def execute(self, context):
        defaults = get_defaults(self.hdri)
        rna_props = context.scene.gaf_props.bl_rna.properties
        
        for d in defaults_stored:
            v = 0
            if d in defaults and not self.factory:
                v = defaults[d]
            else:
                if "hdri_" + d in rna_props.keys():
                    v = rna_props["hdri_" + d].default

            if "hdri_" + d in rna_props.keys():
                setattr(context.scene.gaf_props, 'hdri_' + d, v)
        
        return {'FINISHED'}

    def invoke(self, context, event):
        self.factory = event.shift
        return self.execute(context)


class GAFFER_OT_hdri_save(bpy.types.Operator):

    "Save the current adjustments (rotation, brightness, etc.) as the default for this HDRI"
    bl_idname = 'gaffer.hdri_save'
    bl_label = 'Save Adjustments'
    bl_options = {'INTERNAL'}

    hdri: bpy.props.StringProperty()

    def execute(self, context):
        set_defaults(context, self.hdri)
        self.report({'INFO'},
                    "Saved defaults for " + nice_hdri_name(context.scene.gaf_props.hdri))
        return {'FINISHED'}


class GAFFER_OT_fix_mis(bpy.types.Operator):

    "Set the Multiple Importance Map resolution to 1024"
    bl_idname = 'gaffer.fix_mis'
    bl_label = 'Fix'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.scene.world.cycles.sampling_method = 'AUTOMATIC'
        return {'FINISHED'}


class GAFFER_OT_get_hdrihaven(bpy.types.Operator):

    "Instantly download free HDRIs from hdrihaven.com"
    bl_idname = 'gaffer.get_hdri_haven'
    bl_label = 'Get Free HDRIs'
    bl_options = {'INTERNAL'}

    def draw(self, context):
        num_hdris = 50  # Assume 50, but check the actual number if possible
        if hdri_haven_list:
            num_hdris = len(hdri_haven_list)
        download_size = 1.6 * num_hdris

        layout = self.layout
        col = layout.column(align=True)
        row = col.row()
        row.alignment = 'CENTER'
        row.label(text="This will download ~" + str(num_hdris) + " HDRIs from hdrihaven.com")
        row = col.row()
        row.alignment = 'CENTER'
        row.label(text="(~" + str(download_size) + " MB)")

        col.separator()
        row = col.row()
        row.alignment = 'CENTER'
        row.label(text="The HDRIs are licenced as CC0, so you can do whatever you want with them.")
        row = col.row()
        row.alignment = 'CENTER'
        row.label(text="More info at hdrihaven.com")

        col.separator()
        row = col.row()
        row.alignment = 'CENTER'
        row.label(text="If you already have some of them, those will be skipped")

    def download_file(self, context, req, i, hh, h_list, out_folder, num_hdris):
        filename = hh + '_1k.hdr'
        if hh not in h_list:
            filepath = os.path.join(out_folder, filename)
            print(str(i + 1) + '/' + str(num_hdris), "Downloading:", filename)
            try:
                url = 'https://hdrihaven.com/files/hdris/' + filename
                req.urlretrieve(url, filepath)
                success = True
            except:
                import sys
                print("    Failed to download " + filename + " (" + str(sys.exc_info()[0]) + ")")
        else:
            print("Skipping " + filename + ", you already have it")
                    
    def execute(self, context):
        hdrihaven_hdris = get_hdri_haven_list(force_update=True)
        num_hdris = len(hdrihaven_hdris)
        success = False
        if hdrihaven_hdris:
            hdri_list = get_hdri_list()

            progress_begin(context)

            hdri_paths = get_persistent_setting('hdri_paths')
            out_folder = os.path.join(hdri_paths[0], 'HDRI Haven')
            if not os.path.exists(out_folder):
                os.makedirs(out_folder)

            import urllib.request as req
            # Spoof User-agent so server firewall doesn't block downloads
            opener = req.build_opener()
            opener.addheaders = [
                ('User-agent',
                 'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:55.0) Gecko/20100101 Firefox/55.0')
            ]
            req.install_opener(opener)

            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=12)
            threads = []
            for i, hh in enumerate(hdrihaven_hdris):
                t = executor.submit(self.download_file, context, req, i, hh, hdri_list, out_folder, num_hdris)
                threads.append(t)
            # Debug (single threaded)
            # for i, hh in enumerate(hdrihaven_hdris):
            #     self.download_file(context, req, i, hh, hdri_list, out_folder, num_hdris)

            errors = []
            while (any(t._state != "FINISHED" for t in threads)):
                num_finished = 0
                for tt in threads:
                    if tt._state == "FINISHED":
                        num_finished += 1
                        if tt.result() is not None:
                            errors.append(tt.result())
                progress_update(context,
                                num_finished / num_hdris,
                                "Downloading: " + str(num_finished + 1) + '/' + str(num_hdris))
                sleep(2)

            if errors:
                for e in errors:
                    print(e)
            else:
                success = True

            progress_end(context)
        else:
            self.report({'ERROR'},
                        ("Cannot connect to HDRI Haven website, check your internet connection or try again later. "
                         "If this error persists, contact info@hdrihaven.com"))
            return {'CANCELLED'}

        if success:
            context.scene.gaf_props.ShowHDRIHaven = False

        detect_hdris(self, context)
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=500 * dpifac())


class GAFFER_OT_hide_hdrihaven(bpy.types.Operator):

    "Hide this button for good."
    bl_idname = 'gaffer.hide_hdri_haven'
    bl_label = 'Hide'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        set_persistent_setting('show_hdri_haven', False)
        context.scene.gaf_props.ShowHDRIHaven = False
        return {'FINISHED'}


class GAFFER_OT_open_hdrihaven(bpy.types.Operator):

    ("Higher resolution versions of this HDRI are available for free (CC0) on HDRI Haven, "
     "click to open a web browser and download them")
    bl_idname = 'gaffer.go_hdri_haven'
    bl_label = 'Download higher resolutions of this HDRI (also free)'
    url: bpy.props.StringProperty()

    def execute(self, context):
        bpy.ops.wm.url_open(url=self.url)
        return {'FINISHED'}


class GAFFER_OT_hdri_open_data_folder(bpy.types.Operator):

    "Open Gaffer's data folder in your system file explorer"
    bl_idname = 'gaffer.open_data_folder'
    bl_label = 'Open Gaffer\'s Data Folder'

    def execute(self, context):
        import subprocess
        import sys

        try:
            if sys.platform == 'darwin':
                subprocess.check_call(['open', '--', data_dir])
            elif sys.platform == 'linux2':
                subprocess.check_call(['xdg-open', '--', data_dir])
            elif sys.platform == 'win32':
                subprocess.check_call(['explorer', data_dir])
        except:
            self.report({'WARNING'}, "This might not have worked :( Navigate to the path manually: " + data_dir)
        
        return {'FINISHED'}


class GAFFER_OT_debug_delete_thumbs(bpy.types.Operator):

    "Delete all thumbnail images"
    bl_idname = 'gaffer.dbg_delete_thumbs'
    bl_label = 'Delete thumbnails'

    def draw(self, context):
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label(text="This will delete all thumbnail files that Gaffer has made.", icon="ERROR")
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label(text="You will need to generate them again.")

    def execute(self, context):
        if os.path.exists(thumbnail_dir):
            files = os.listdir(thumbnail_dir)
            for f in files:
                p = os.path.join(thumbnail_dir, f)
                os.remove(p)
            self.report({'INFO'}, "Deleted %s files" % len(files))
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Folder does not exist")
            return {'CANCELLED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=340 * dpifac())


class GAFFER_OT_debug_upload_hdri_list(bpy.types.Operator):

    "Upload your list of HDRIs to the internet"
    bl_idname = 'gaffer.dbg_upload_hdri_list'
    bl_label = 'Upload HDRI List'

    def draw(self, context):
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label(text="This will upload Gaffer's HDRI list to the internet,", icon="ERROR")
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label(text="and then open the public URL in your browser.")

    def execute(self, context):

        file_list = []
        
        def get_file_list(p):
            for f in os.listdir(p):
                if os.path.isfile(os.path.join(p, f)):
                    if os.path.splitext(f)[1].lower() in allowed_file_types:
                        file_list.append(f)
                else:
                    get_file_list(os.path.join(p, f))

        if os.path.exists(hdri_list_path):
            hdri_paths = get_persistent_setting('hdri_paths')
            for hp in hdri_paths:
                get_file_list(hp)
            file_list = sorted(file_list, key=lambda x: x.lower())
            hastebin_file(hdri_list_path, extra_string="    Actual files:\n" + '\n'.join(file_list))
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "File does not exist")
            return {'CANCELLED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300 * dpifac())


class GAFFER_OT_debug_upload_logs(bpy.types.Operator):

    "Upload Gaffer's debugging logs to the internet"
    bl_idname = 'gaffer.dbg_upload_logs'
    bl_label = 'Upload Logs'

    def draw(self, context):
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label(text="This will upload Gaffer's logs to the internet,", icon="ERROR")
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label(text="and then open the public URL in your browser.")

    def execute(self, context):
        if os.path.exists(log_file):
            hastebin_file(log_file)
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "File does not exist")
            return {'CANCELLED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300 * dpifac())
