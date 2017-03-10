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
import bgl, blf
from math import pi, cos, sin, log, ceil
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.app.handlers import persistent
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
    if GafShowLightRadius._handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(GafShowLightRadius._handle, 'WINDOW')
    if GafShowLightLabel._handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(GafShowLightLabel._handle, 'WINDOW')
    bpy.context.scene.gaf_props.IsShowingRadius = False
    bpy.context.scene.gaf_props.IsShowingLabel = False

    
class GafRename(bpy.types.Operator):

    'Rename this light'
    bl_idname = 'gaffer.rename'
    bl_label = 'Rename This Light'
    bl_options = {'REGISTER', 'UNDO'}
    light = bpy.props.StringProperty(name="New name")
    multiuser = bpy.props.StringProperty(default="")
    oldname = ""
    users = []

    def draw(self, context):
        self.layout.prop(self, 'light')
        if self.multiuser:
            self.layout.label("You are renaming the " + ("lamp data" if self.multiuser.startswith("LAMP") else "material") + ", which has multiple users")

    def invoke(self, context, event):
        self.oldname = self.light
        return context.window_manager.invoke_props_popup(self, event)

    def execute(self, context):
        if self.multiuser.startswith("LAMP"):
            bpy.data.lamps[self.oldname].name = self.light
        elif self.multiuser.startswith("MAT"):
            bpy.data.materials[self.oldname].name = self.light
        else:
            context.scene.objects[self.oldname].name = self.light
        refresh_light_list(context.scene)
        return {'FINISHED'}

class GafSetTemp(bpy.types.Operator):

    'Set the color temperature to a preset'
    bl_idname = 'gaffer.col_temp_preset'
    bl_label = 'Color Temperature Preset'
    temperature = bpy.props.StringProperty()
    light = bpy.props.StringProperty()
    material = bpy.props.StringProperty()
    node = bpy.props.StringProperty()

    def execute(self, context):
        light = context.scene.objects[self.light]
        if light.type == 'LAMP':
            node = light.data.node_tree.nodes[self.node]
        else:
            node = bpy.data.materials[self.material].node_tree.nodes[self.node]
        node.inputs[0].links[0].from_node.inputs[0].default_value = col_temp[self.temperature]
        return {'FINISHED'}

class GafTempShowList(bpy.types.Operator):

    'Set the color temperature to a preset'
    bl_idname = 'gaffer.col_temp_show'
    bl_label = 'Color Temperature Preset'
    l_index = bpy.props.IntProperty()

    def execute(self, context):
        context.scene.gaf_props.ColTempExpand = True
        context.scene.gaf_props.LightUIIndex = self.l_index
        return {'FINISHED'}

class GafTempHideList(bpy.types.Operator):

    'Hide color temperature presets'
    bl_idname = 'gaffer.col_temp_hide'
    bl_label = 'Hide Presets'

    def execute(self, context):
        context.scene.gaf_props.ColTempExpand = False
        return {'FINISHED'}

class GafShowMore(bpy.types.Operator):

    'Show settings such as MIS, falloff, ray visibility...'
    bl_idname = 'gaffer.more_options_show'
    bl_label = 'Show more options'
    light = bpy.props.StringProperty()

    def execute(self, context):
        exp_list = context.scene.gaf_props.MoreExpand
        # prepend+append funny stuff so that the light name is
        # unique (otherwise Fill_03 would also expand Fill_03.001)
        exp_list += ("_Light:_(" + self.light + ")_")
        context.scene.gaf_props.MoreExpand = exp_list
        return {'FINISHED'}

class GafHideMore(bpy.types.Operator):

    'Hide settings such as MIS, falloff, ray visibility...'
    bl_idname = 'gaffer.more_options_hide'
    bl_label = 'Hide more options'
    light = bpy.props.StringProperty()

    def execute(self, context):
        context.scene.gaf_props.MoreExpand = context.scene.gaf_props.MoreExpand.replace("_Light:_(" + self.light + ")_", "")
        return {'FINISHED'}

class GafHideShowLight(bpy.types.Operator):

    'Hide/Show this light (in viewport and in render)'
    bl_idname = 'gaffer.hide_light'
    bl_label = 'Hide Light'
    light = bpy.props.StringProperty()
    hide = bpy.props.BoolProperty()
    dataname = bpy.props.StringProperty()

    def execute(self, context):
        dataname = self.dataname
        if dataname == "__SINGLE_USER__":
            light = bpy.data.objects[self.light]
            light.hide = self.hide
            light.hide_render = self.hide
        else:
            if dataname.startswith('LAMP'):
                data = bpy.data.lamps[(dataname[4:])]  # actual data name (minus the prepended 'LAMP')
                for obj in bpy.data.objects:
                    if obj.data == data:
                        obj.hide = self.hide
                        obj.hide_render = self.hide
            else:
                mat = bpy.data.materials[(dataname[3:])]  # actual data name (minus the prepended 'MAT')
                for obj in bpy.data.objects:
                    if obj.type == 'MESH':
                        for slot in obj.material_slots:
                            if slot.material == mat:
                                obj.hide = self.hide
                                obj.hide_render = self.hide
        return {'FINISHED'}

class GafSelectLight(bpy.types.Operator):

    'Select this light'
    bl_idname = 'gaffer.select_light'
    bl_label = 'Select'
    light = bpy.props.StringProperty()
    dataname = bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        for item in bpy.data.objects:
            item.select = False
        dataname = self.dataname
        if dataname == "__SINGLE_USER__":
            obj = bpy.data.objects[self.light]
            obj.select = True
            context.scene.objects.active = obj
        else:
            if dataname.startswith('LAMP'):
                data = bpy.data.lamps[(dataname[4:])]  # actual data name (minus the prepended 'LAMP')
                for obj in bpy.data.objects:
                    if obj.data == data:
                        obj.select = True
            else:
                mat = bpy.data.materials[(dataname[3:])]  # actual data name (minus the prepended 'MAT')
                for obj in bpy.data.objects:
                    if obj.type == 'MESH':
                        for slot in obj.material_slots:
                            if slot.material == mat:
                                obj.select = True
            context.scene.objects.active = bpy.data.objects[self.light]

        return {'FINISHED'}

class GafSolo(bpy.types.Operator):

    'Hide all other lights but this one'
    bl_idname = 'gaffer.solo'
    bl_label = 'Solo Light'
    light = bpy.props.StringProperty()
    showhide = bpy.props.BoolProperty()
    worldsolo = bpy.props.BoolProperty(default=False)
    dataname = bpy.props.StringProperty(default="__EXIT_SOLO__")

    def execute(self, context):
        light = self.light
        showhide = self.showhide
        worldsolo = self.worldsolo
        scene = context.scene
        blacklist = context.scene.gaf_props.Blacklist

        # Get object names that share data with the solo'd object:
        dataname = self.dataname
        linked_lights = []
        if dataname not in ["__SINGLE_USER__", "__EXIT_SOLO__"] and showhide:  # only make list if going into Solo and obj has multiple users
            if dataname.startswith('LAMP'):
                data = bpy.data.lamps[(dataname[4:])]  # actual data name (minus the prepended 'LAMP')
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
                        return {'FINISHED'}  # if one of the lights has been deleted/changed, update the list and dont restore visibility

            for l in statelist:  # then restore visibility
                if l[0] != "WorldEnviroLight":
                    obj = bpy.data.objects[l[0]]
                    if obj.name not in blacklist:
                        if obj.name == light or obj.name in linked_lights:
                            obj.hide = False
                            obj.hide_render = False
                        else:
                            obj.hide = True
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
                        obj.hide = castBool(l[1])
                        obj.hide_render = castBool(l[2])
                elif context.scene.render.engine == 'CYCLES':
                    scene.gaf_props.WorldVis = castBool(l[1])
                    scene.gaf_props.WorldReflOnly = castBool(l[2])

        return {'FINISHED'}

class GafLampUseNodes(bpy.types.Operator):

    'Make this lamp use nodes'
    bl_idname = 'gaffer.lamp_use_nodes'
    bl_label = 'Use Nodes'
    light = bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects[self.light]
        if obj.type == 'LAMP':
            obj.data.use_nodes = True
        bpy.ops.gaffer.refresh_lights()
        return {'FINISHED'}

class GafNodeSetStrength(bpy.types.Operator):

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

class GafRefreshLightList(bpy.types.Operator):

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

class GafCreateEnviroWidget(bpy.types.Operator):

    'Create an Empty which drives the rotation of the background texture'
    bl_idname = 'gaffer.envwidget'
    bl_label = 'Create Enviro Rotation Widget (EXPERIMENTAL)'
    radius = bpy.props.FloatProperty(default = 16.0,
                                     description = "How big the created empty should be (distance from center to edge)")

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
            map_rotation = [i*-1 for i in map_rotation]

        widget_data = bpy.data.objects.new("Environment Rotation Widget", None)
        scene.objects.link(widget_data)
        widget = scene.objects["Environment Rotation Widget"]
        widget.location = scene.cursor_location
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

class GafLinkSkyToSun(bpy.types.Operator):
    bl_idname = "gaffer.link_sky_to_sun"
    bl_label = "Link Sky Texture:"
    bl_options = {'REGISTER', 'UNDO'}
    node_name = bpy.props.StringProperty(default = "")

    # Thanks to oscurart for the original script off which this is based!
    # http://bit.ly/blsunsky

    def execute(self, context):

        tree = context.scene.world.node_tree
        node = tree.nodes[self.node_name]
        lampob = bpy.data.objects[context.scene.gaf_props.SunObject]

        if tree.animation_data:
            if tree.animation_data.action:
                for fc in tree.animation_data.action.fcurves:
                    if fc.data_path == ("nodes[\""+node.name+"\"].sun_direction"):
                        self.report({'ERROR'}, "Sun Direction is animated")
                        return {'CANCELLED'}
            elif tree.animation_data.drivers:
                for dr in tree.animation_data.drivers:
                    if dr.data_path == ("nodes[\""+node.name+"\"].sun_direction"):
                        self.report({'ERROR'}, "Sun Direction has drivers")
                        return {'CANCELLED'}

        dr = node.driver_add("sun_direction")

        nodename = ""
        for ch in node.name:
            if ch.isalpha():  # make sure node name can be used in expression
                nodename += ch
        varname = nodename + "_" + str(context.scene.gaf_props.VarNameCounter)  # create unique variable name for each node
        context.scene.gaf_props.VarNameCounter += 1

        dr[0].driver.expression = varname
        var = dr[0].driver.variables.new()
        var.name = varname
        var.type = 'SINGLE_PROP'
        var.targets[0].id = lampob
        var.targets[0].data_path = 'matrix_world[2][0]'
        # Y
        dr[1].driver.expression = varname
        var = dr[1].driver.variables.new()
        var.name = varname
        var.type = 'SINGLE_PROP'
        var.targets[0].id = lampob
        var.targets[0].data_path = 'matrix_world[2][1]'
        # Y
        dr[2].driver.expression = varname
        var = dr[2].driver.variables.new()
        var.name = varname
        var.type = 'SINGLE_PROP'
        var.targets[0].id = lampob
        var.targets[0].data_path = 'matrix_world[2][2]'

        return {'FINISHED'}

class GafAimLight(bpy.types.Operator):

    "Point the selected lights at a target"
    bl_idname = 'gaffer.aim'
    bl_label = 'Aim'
    target_type = bpy.props.StringProperty()

    def aim (self, context, obj, target=[0,0,0]):
        # Thanks to @kilbee for cleaning my crap up here :) See: https://github.com/gregzaal/Gaffer/commit/b920092
        obj_loc = obj.matrix_world.to_translation()
        direction = target - obj_loc
        # point obj '-Z' and use its 'Y' as up
        rot_quat = direction.to_track_quat('-Z', 'Y')
        obj.rotation_euler = rot_quat.to_euler()

    def execute(self, context):
        if self.target_type == 'CURSOR':
            # Aim all selected objects at cursor
            objects = context.selected_editable_objects
            if not objects:
                self.report({'ERROR'}, "No selected objects!")
                return {'CANCELLED'}
            for obj in context.selected_editable_objects:
                self.aim(context, obj, context.scene.cursor_location)

            return {'FINISHED'}

        elif self.target_type == 'SELECTED':
            # Aim the active object at the average location of all other selected objects
            active = context.scene.objects.active
            objects = [obj for obj in context.selected_objects if obj != active]
            num_objects = len(objects)

            if not active:
                self.report({'ERROR'}, "You need an active object!")
                return {'CANCELLED'}
            elif num_objects == 0:
                if active.select:
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
            active = context.scene.objects.active
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


class GafShowLightRadius(bpy.types.Operator):

    'Display a circle around each light showing their radius'
    bl_idname = 'gaffer.show_radius'
    bl_label = 'Show Radius'

    # CoDEmanX wrote a lot of this - thanks sir!

    _handle = None

    @staticmethod
    def handle_add(self, context):
        GafShowLightRadius._handle = self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_radius, (context,), 'WINDOW', 'POST_VIEW')

    @staticmethod
    def handle_remove(context):
        if GafShowLightRadius._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(GafShowLightRadius._handle, 'WINDOW')
        GafShowLightRadius._handle = None

    def draw_callback_radius(self, context):
        scene = context.scene
        region = context.region

        if context.space_data.viewport_shade == 'RENDERED':
            return

        for item in self.objects:
            obj = item[0]
            if not scene.gaf_props.LightRadiusSelectedOnly or obj.select:
                if obj:
                    if obj.data:
                        if obj.data.type in ['POINT', 'SUN', 'SPOT']:  # have to check this again, in case user changes the type while showing radius
                            if not (scene.render.engine == 'BLENDER_RENDER' and obj.data.shadow_method == 'NOSHADOW'):
                                if obj in context.visible_objects and obj.name not in [o.name for o in scene.gaf_props.Blacklist]:
                                    if scene.gaf_props.LightRadiusUseColor:
                                        if item[1][0] == 'BLACKBODY':
                                            color = convert_temp_to_RGB(item[1][1].inputs[0].default_value)
                                        elif item[1][0] == 'WAVELENGTH':
                                            color = convert_wavelength_to_RGB(item[1][1].inputs[0].default_value)
                                        else:
                                            color = item[1]
                                    else:
                                        color = scene.gaf_props.DefaultRadiusColor

                                    rv3d = context.region_data
                                    
                                    view = rv3d.view_matrix
                                    persp = rv3d.perspective_matrix

                                    bgl.glEnable(bgl.GL_BLEND)

                                    radius = obj.data.shadow_soft_size

                                    obj_matrix_world = obj.matrix_world

                                    origin = obj.matrix_world.translation

                                    view_mat = context.space_data.region_3d.view_matrix
                                    view_dir = view_mat.to_3x3()[2]
                                    up = Vector((0,0,1))

                                    angle = up.angle(view_dir)
                                    axis = up.cross(view_dir)

                                    mat = Matrix.Translation(origin) * Matrix.Rotation(angle, 4, axis)
                                    
                                    bgl.glColor4f(color[0], color[1], color[2], scene.gaf_props.LightRadiusAlpha)
                                    bgl.glEnable(bgl.GL_LINE_SMOOTH)  # anti-aliasing
                                    if scene.gaf_props.LightRadiusXray:
                                        bgl.glClear(bgl.GL_DEPTH_BUFFER_BIT)
                                    if scene.gaf_props.LightRadiusDrawType == 'filled':
                                        bgl.glBegin(bgl.GL_TRIANGLE_FAN)
                                    else:
                                        if scene.gaf_props.LightRadiusDrawType == 'dotted':
                                            bgl.glLineStipple(4, 0x3333)
                                            bgl.glEnable(bgl.GL_LINE_STIPPLE)
                                        bgl.glLineWidth(3)
                                        bgl.glBegin(bgl.GL_LINE_STRIP)
                                    sides = 64
                                    for i in range(sides + 1):
                                        cosine = radius * cos(i * 2 * pi / sides)
                                        sine = radius * sin(i * 2 * pi / sides)
                                        vec = Vector((cosine, sine, 0))
                                        bgl.glVertex3f(*(mat*vec))
                                    bgl.glEnd()

                                    # restore opengl defaults
                                    bgl.glPointSize(1)
                                    bgl.glLineWidth(1)
                                    bgl.glColor4f(0.0, 0.0, 0.0, 1.0)
                                    bgl.glDisable(bgl.GL_BLEND)
                                    bgl.glDisable(bgl.GL_LINE_SMOOTH)
                                    bgl.glDisable(bgl.GL_LINE_STIPPLE)
    
    def modal(self, context, event):
        context.area.tag_redraw()
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        scene = context.scene

        if scene.gaf_props.IsShowingRadius:
            scene.gaf_props.IsShowingRadius = False
            GafShowLightRadius.handle_remove(context)
            return {'FINISHED'}
        elif context.area.type == 'VIEW_3D':
            scene.gaf_props.IsShowingRadius = True
            
            context.window_manager.modal_handler_add(self)

            GafShowLightRadius.handle_add(self, context)

            self.objects = []
            for obj in scene.objects:
                # It doesn't make sense to try show the radius for mesh, area or hemi lamps.
                if obj.type == 'LAMP':
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

class GafShowLightLabel(bpy.types.Operator):

    'Display the name of each light in the viewport'
    bl_idname = 'gaffer.show_label'
    bl_label = 'Show Label'

    _handle = None

    @staticmethod
    def handle_add(self, context):
        GafShowLightLabel._handle = self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_label, (context,), 'WINDOW', 'POST_PIXEL')

    @staticmethod
    def handle_remove(context):
        if GafShowLightLabel._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(GafShowLightLabel._handle, 'WINDOW')
        GafShowLightLabel._handle = None

    def alignment(self, x, y, width, height, margin):
        align = bpy.context.scene.gaf_props.LabelAlign

        # X:
        if align in ['t', 'c', 'b']:  # middle
            x = x - (width/2)
        elif align in ['tl', 'l', 'bl']:  # left
            x = x - (width + margin)
        elif align in ['tr', 'r', 'br']:  # right
            x = x + margin

        # Y:
        if align in ['l', 'c', 'r']:  # middle
            y = y - (height/2)
        elif align in ['tl', 't', 'tr']:  # top
            y = y + margin
        elif align in ['bl', 'b', 'br']:  # bottom
            y = y - (height + margin)

        return x, y+3

    def draw_callback_label(self, context):
        scene = context.scene

        if context.space_data.viewport_shade == 'RENDERED':
            return

        # font_size_factor is used to scale the rectangles based on the font size and DPI, measured against a font size of 62
        font_size_factor = (scene.gaf_props.LabelFontSize/62) * (context.user_preferences.system.dpi/72)
        draw_type = scene.gaf_props.LabelDrawType
        background_color = scene.gaf_props.DefaultLabelBGColor
        text_color = scene.gaf_props.LabelTextColor

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
                loc = location_3d_to_region_2d(region, rv3d, obj.location)
                if loc:  # sometimes this is None if lights are out of view
                    x, y = loc

                    char_width = 36 * font_size_factor
                    height = 65 * font_size_factor
                    width = len(obj.name) * int(char_width) + 1
                    if item[2]:
                        width = max(width, len(item[2]) * int(char_width*0.8) + 1)

                    x, y = self.alignment(x, y, width, height if not item[2] else height - height * 0.8 - 4, scene.gaf_props.LabelMargin*font_size_factor)
                    y_sub = y - (8 * font_size_factor) - height

                    if draw_type != 'color_text':
                        # Draw background rectangles
                        bgl.glEnable(bgl.GL_BLEND)
                        if draw_type == 'color_bg' and scene.gaf_props.LabelUseColor:
                            bgl.glColor4f(color[0], color[1], color[2], scene.gaf_props.LabelAlpha)
                        else:
                            bgl.glColor4f(background_color[0], background_color[1], background_color[2], scene.gaf_props.LabelAlpha)

                        x1 = x
                        x2 = x1 + width
                        if not item[2]:
                            y1 = y - (8 * font_size_factor)
                            y2 = y1 + height
                        else:
                            y1 = y - (8 * font_size_factor) - height * 0.8 - 4
                            y2 = y1 + height + height * 0.8 + 4

                        draw_rounded_rect(x1, y1, x2, y2, 20*font_size_factor)

                        bgl.glDisable(bgl.GL_BLEND)

                    # Draw text
                    if draw_type != 'color_bg' and scene.gaf_props.LabelUseColor:
                        bgl.glColor4f(color[0], color[1], color[2], scene.gaf_props.LabelAlpha if draw_type == 'color_text' else 1.0)
                    else:
                        bgl.glColor4f(text_color[0], text_color[1], text_color[2], 1.0)
                    font_id = 1
                    blf.position(font_id, x, y, 0)
                    blf.size(font_id, scene.gaf_props.LabelFontSize, context.user_preferences.system.dpi)
                    blf.draw(font_id, obj.name)

                    if item[2]:
                        blf.position(font_id, x, y_sub, 0)
                        blf.size(font_id, int(scene.gaf_props.LabelFontSize*0.8), context.user_preferences.system.dpi)
                        blf.draw(font_id, item[2])

                    bgl.glColor4f(0.0, 0.0, 0.0, 1.0)
    
    def modal(self, context, event):
        try:
            context.area.tag_redraw()
        except:
            # When the user goes full-screen, then hovers the mouse over the info header,
            # tag_redraw fails for some reason (AttributeError, but catch all in case)
            print ("failed to redraw")
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        scene = context.scene

        if scene.gaf_props.IsShowingLabel:
            scene.gaf_props.IsShowingLabel = False
            GafShowLightLabel.handle_remove(context)
            return {'FINISHED'}
        elif context.area.type == 'VIEW_3D':
            scene.gaf_props.IsShowingLabel = True
            
            context.window_manager.modal_handler_add(self)

            GafShowLightLabel.handle_add(self, context)

            self.objects = []
            for obj in scene.objects:
                color = scene.gaf_props.DefaultLabelBGColor
                nodes = None
                data = None
                if obj.type == 'LAMP':
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

                if obj.type == 'LAMP' and not nodes:  # is a lamp but doesnt use_nodes
                    color = obj.data.color
                    self.objects.append([obj, color, data])

            return {'RUNNING_MODAL'}

        else:
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}

class GafRefreshBGL(bpy.types.Operator):

    "Update the radius and label display to account for undetected changes"
    bl_idname = 'gaffer.refresh_bgl'
    bl_label = 'Refresh Radius/Label'

    @classmethod
    def poll(cls, context):
        return context.scene.gaf_props.IsShowingRadius or context.scene.gaf_props.IsShowingLabel

    def execute(self, context):
        refresh_bgl()
        return {'FINISHED'}

class GafAddBlacklisted(bpy.types.Operator):

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

class GafRemoveBlacklisted(bpy.types.Operator):

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


class GafDetectHDRIs(bpy.types.Operator):

    "Look for HDRIs in the chosen folder, matching different resolutions and variants together based on filename"
    bl_idname = 'gaffer.detect_hdris'
    bl_label = 'Detect HDRIs'

    def execute(self, context):
        detect_hdris(self, context)
        return {'FINISHED'}

class GafHDRIThumbGen(bpy.types.Operator):

    "Generate missing thumbnail images for all HDRIs"
    bl_idname = 'gaffer.generate_hdri_thumbs'
    bl_label = 'Generate Thumbnails'
    bl_options = {'INTERNAL'}

    size_limit = 100

    skip_huge_files = bpy.props.BoolProperty(
        name = "Skip big files",
        description = "If you have big HDRIs (>"+str(size_limit)+" MB) with no smaller resolution available, these will be skipped to save time. Disabling this will mean it may take an unreasonable amount of time to generate thumbnails. Instead, it would be better if you manually create the lower resolution version first in Photoshop/Krita, then click 'Refresh' in Gaffer's User Preferences",
        default=True
        )

    # TODO render diffuse/gloss/plastic spheres instead of just the normal preview
    # TODO option to try to download sphere renders instead of rendering locally, as well as a separate option to upload local renders to help others skip rendering locally again

    def draw(self, context):
        layout = self.layout

        col = layout.column()
        col.label("This only has to be done once.")
        col.label("The only way to stop this process once you start it is to forcibly close Blender.")

        col.separator()
        col = layout.column(align=True)
        col.prop(self, 'skip_huge_files')

        if context.scene.gaf_props.ThumbnailsBigHDRIFound:
            col.label("Large HDRI files were skipped last time.", icon='ERROR')
            col.label("You may wish to disable 'Skip big files', but first read its tooltip.")

    def generate_thumb(self, name, files):
        context = bpy.context
        prefs = context.user_preferences.addons[__package__].preferences

        chosen_file = ''

        # Check if thumb file came with HDRI
        d = os.path.dirname(files[0])
        for f in os.listdir(os.path.join(prefs.hdri_path, d)):
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
                                file_sizes[f] = os.path.getsize(os.path.join(prefs.hdri_path, f))
                    chosen_file = min(file_sizes, key=file_sizes.get)
        if not chosen_file:
            chosen_file = files[0]  # Safety fallback

        # Create thumbnail
        fp = os.path.join(prefs.hdri_path, chosen_file)
        thumb_file = os.path.join(thumbnail_dir, name+"__thumb_preview.jpg")
        if not os.path.exists(thumb_file):
            filesize = os.path.getsize(fp)/1024/1024
            log('    ' + name + ": " + chosen_file + "  " + str(ceil(filesize))+" MB", also_print=True)
            
            if filesize < self.size_limit or not self.skip_huge_files:
                cmd = [bpy.app.binary_path]
                cmd.append("--background")
                cmd.append("--factory-startup")
                cmd.append("--python")
                cmd.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "resize.py"))
                cmd.append('--')
                cmd.append(fp)
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

        context.user_preferences.addons[__package__].preferences.RequestThumbGen = False
        hdris = get_hdri_list()

        progress_begin(context)

        num_hdris = len(hdris)


        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=8 if self.skip_huge_files else 4)
        threads = []
        for i, h in enumerate(hdris):
            t = executor.submit(self.generate_thumb, h, hdris[h])
            threads.append(t)

        errors = []
        while (any(t._state!="FINISHED" for t in threads)):
            num_finished = 0
            for tt in threads:
                if tt._state == "FINISHED":
                    num_finished += 1
                    if tt.result() != None:
                        errors.append(tt.result())
            progress_update(context, num_finished/num_hdris, "Generating thumbnail: "+str(num_finished+1)+'/'+str(num_hdris))
            sleep (2)

        if errors:
            for e in errors:
                print (e)
        else:
            success = True


        progress_end(context)

        log("Successfully finished generating thumbnails")

        refresh_previews()

        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420*dpifac())

class GafHDRIJPGGen(bpy.types.Operator):

    "Generate regular JPG and darkened JPG from HDRI"
    bl_idname = 'gaffer.generate_jpgs'
    bl_label = 'Generate JPGs'
    bl_options = {'INTERNAL'}

    def generate_jpgs(self, context, name):
        gaf_props = context.scene.gaf_props

        hdri_path = get_variation(name, mode="biggest")

        img_exists = False
        for m in ['', '_dark']:  # Run twice, once for normal JPG and once for darkened JPG
            jpg_path = os.path.join(jpg_dir, name + m + ".jpg")
            if not os.path.exists(jpg_path):
                if not img_exists:
                    img = bpy.data.images.load(hdri_path, check_existing=False)
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
                progress_update(context, i/num_hdris, "Generating JPG: "+str(i+1)+'/'+str(num_hdris))
                print ('('+str(i+1)+'/'+str(num_hdris)+') Generating JPG for '+hdri+' ...')
                self.generate_jpgs(context, hdri)
            print ("Done!")
            progress_end(context)
        else:
            self.generate_jpgs(context, gaf_props.hdri)

        setup_hdri(self, context)


        return {'FINISHED'}

class GafHDRIClearSearch(bpy.types.Operator):

    "Clear the search, show all HDRIs"
    bl_idname = 'gaffer.clear_search'
    bl_label = 'Clear'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.scene.gaf_props.hdri_search = ""
        
        return {'FINISHED'}

class GafHDRIPaddles(bpy.types.Operator):

    "Switch to the next/previous HDRI"
    bl_idname = 'gaffer.hdri_paddles'
    bl_label = 'Next/Previous'
    bl_options = {'INTERNAL'}
    do_next = bpy.props.BoolProperty()

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
            gaf_props.hdri = list_hdris[current_index+1] if self.do_next else list_hdris[current_index-1]
            return {'FINISHED'}

class GafHDRIAddTag(bpy.types.Operator):

    "Add this tag to the current HDRI"
    bl_idname = 'gaffer.add_tag'
    bl_label = 'Add Tag'
    bl_options = {'INTERNAL'}
    hdri = bpy.props.StringProperty()
    tag = bpy.props.StringProperty()

    def execute(self, context):
        set_tag(self.hdri, self.tag)
        
        return {'FINISHED'}

class GafHDRIRandom(bpy.types.Operator):

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

class GafFixMIS(bpy.types.Operator):

    "Set the Multiple Importance Map resolution to 1024"
    bl_idname = 'gaffer.fix_mis'
    bl_label = 'Fix'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.scene.world.cycles.sample_as_light = True
        context.scene.world.cycles.sample_map_resolution = 1024
        return {'FINISHED'}

class GafGetHDRIHaven(bpy.types.Operator):

    "Instantly download free CC-BY HDRIs from hdrihaven.com"
    bl_idname = 'gaffer.get_hdri_haven'
    bl_label = 'Get Free HDRIs'
    bl_options = {'INTERNAL'}

    def draw(self, context):
        num_hdris = 100  # Assume 100, but check the actual number if possible
        if hdri_haven_list:
            num_hdris = len(hdri_haven_list)
        download_size = 1.6 * num_hdris

        layout = self.layout
        col = layout.column(align=True)
        row = col.row()
        row.alignment='CENTER'
        row.label("This will download ~"+str(num_hdris)+" 1k HDRIs from hdrihaven.com")
        row = col.row()
        row.alignment='CENTER'
        row.label("(~"+str(download_size)+" MB)")

        col.separator()
        row = col.row()
        row.alignment='CENTER'
        row.label("The HDRIs are licenced under a creative commons attribution license,")
        row = col.row()
        row.alignment='CENTER'
        row.label("this means you can use them for any purpose as long as you credit hdrihaven.com")

        col.separator()
        row = col.row()
        row.alignment='CENTER'
        row.label("If you already have some of them, those will be skipped")

    def download_file(self, context, i, hh, h_list, out_folder, num_hdris):
        from urllib.request import urlretrieve

        filename = hh+'_1k.hdr'
        if hh not in h_list:
            filepath = os.path.join(out_folder, filename)
            print (str(i+1)+'/'+str(num_hdris), "Downloading:", filename)
            try:
                urlretrieve('https://hdrihaven.com/hdris/hdris/'+filename, filepath)
                success = True
            except:
                import sys
                print ("    Failed to download " + filename + " ("+sys.exc_info()[0]+")")
        else:
            print ("Skipping " + filename + ", you already have it")
                    
    def execute(self, context):
        hdrihaven_hdris = get_hdri_haven_list(force_update=True)
        num_hdris = len(hdrihaven_hdris)
        success = False
        if hdrihaven_hdris:
            hdri_list = get_hdri_list()

            progress_begin(context)

            prefs = bpy.context.user_preferences.addons[__package__].preferences
            out_folder = os.path.join(prefs.hdri_path, 'HDRI Haven')
            if not os.path.exists(out_folder):
                os.makedirs(out_folder)

            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=12)
            threads = []
            for i, hh in enumerate(hdrihaven_hdris):
                t = executor.submit(self.download_file, context, i, hh, hdri_list, out_folder, num_hdris)
                threads.append(t)

            errors = []
            while (any(t._state!="FINISHED" for t in threads)):
                num_finished = 0
                for tt in threads:
                    if tt._state == "FINISHED":
                        num_finished += 1
                        if tt.result() != None:
                            errors.append(tt.result())
                progress_update(context, num_finished/num_hdris, "Downloading: "+str(num_finished+1)+'/'+str(num_hdris))
                sleep (2)

            if errors:
                for e in errors:
                    print (e)
            else:
                success = True

            progress_end(context)
        else:
            self.report({'ERROR'}, "Cannot connect to HDRI Haven website, check your internet connection or try again later")
            return {'CANCELLED'}

        if success:
            context.scene.gaf_props.ShowHDRIHaven = False

        detect_hdris(self, context)
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=500*dpifac())

class GafHideHDRIHaven(bpy.types.Operator):

    "Hide this button for good."
    bl_idname = 'gaffer.hide_hdri_haven'
    bl_label = 'Hide'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        set_persistent_setting('show_hdri_haven', False)
        context.scene.gaf_props.ShowHDRIHaven = False
        return {'FINISHED'}

class GafOpenHDRIHaven(bpy.types.Operator):

    "Buy the full 16k resolution of this HDRI for $5.95 (opens web browser)"
    bl_idname = 'gaffer.buy_hdri_haven'
    bl_label = 'Buy full-res HDRI'
    url = bpy.props.StringProperty()

    def execute(self, context):
        bpy.ops.wm.url_open(url=self.url)
        return {'FINISHED'}

class GafHDRIOpenDataFolder(bpy.types.Operator):

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
            self.report({'WARNING'}, "This might not have worked :( Navigate to the path manually: "+data_dir)
        
        return {'FINISHED'}

class GafDebugDeleteThumbs(bpy.types.Operator):

    "Delete all thumbnail images"
    bl_idname = 'gaffer.dbg_delete_thumbs'
    bl_label = 'Delete thumbnails'

    def draw(self, context):
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label("This will delete all thumbnail files that Gaffer has made.", icon="ERROR")
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label("You will need to generate them again.")

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
        return context.window_manager.invoke_props_dialog(self, width=340*dpifac())

class GafDebugUploadHDRIList(bpy.types.Operator):

    "Upload your list of HDRIs to the internet"
    bl_idname = 'gaffer.dbg_upload_hdri_list'
    bl_label = 'Upload HDRI List'

    def draw(self, context):
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label("This will upload Gaffer's HDRI list to the internet,", icon="ERROR")
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label("and then open the public URL in your browser.")

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
            get_file_list(bpy.context.user_preferences.addons[__package__].preferences.hdri_path)
            file_list = sorted(file_list, key=lambda x: x.lower())
            hastebin_file(hdri_list_path, extra_string = "    Actual files:\n" + '\n'.join(file_list))
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "File does not exist")
            return {'CANCELLED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300*dpifac())

class GafDebugUploadLogs(bpy.types.Operator):

    "Upload Gaffer's debugging logs to the internet"
    bl_idname = 'gaffer.dbg_upload_logs'
    bl_label = 'Upload Logs'

    def draw(self, context):
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label("This will upload Gaffer's logs to the internet,", icon="ERROR")
        row = col.row(align=True)
        row.alignment = 'CENTER'
        row.label("and then open the public URL in your browser.")

    def execute(self, context):
        if os.path.exists(log_file):
            hastebin_file(log_file)
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "File does not exist")
            return {'CANCELLED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300*dpifac())

