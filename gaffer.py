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
    "version": (2, 2),
    "blender": (2, 72, 0),
    "location": "3D View > Tools",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "3D View"}

import bpy
from collections import OrderedDict
import bgl, blf
from math import pi, cos, sin, log
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.app.handlers import persistent


supported_renderers = ['BLENDER_RENDER', 'CYCLES']

col_temp = {"01_Flame (1700)": 1700,
            "02_Tungsten (3200)": 3200,
            "03_Sunset (5000)": 5000,
            "04_Daylight (5500)": 5500,
            "05_Overcast (6500)": 6500,
            "06_Monitor (7000)": 7000,
            "07_Shade (8000)": 8000,
            "08_LCD (10500)": 10500,
            "09_Sky (12000)": 12000}


'''
    FUNCTIONS
'''
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
    bpy.context.scene.GafferIsShowingRadius = False
    bpy.context.scene.GafferIsShowingLabel = False

def hack_force_update(context, nodes):
    node = nodes.new('ShaderNodeMath')
    node.inputs[0].default_value = 0.0
    nodes.remove(node)
    return False

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
        raw[i] += ']'
        i += 1
    newraw = []
    for item in raw:
        newraw.append(stringToList(item, stripquotes))
    return newraw

def castBool(str):
    if str == 'True':
        return True
    else:
        return False

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
    if tmp_internal <=66:
        tmp_green = 99.4708025861 * log(tmp_internal) - 161.1195681661
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
    if tmp_internal >=66:
        blue = 255
    elif tmp_internal <= 19:
        blue = 0
    else:
        tmp_blue = 138.5177312231 * log(tmp_internal - 10) - 305.0447927307
        if tmp_blue < 0:
            blue = 0
        elif tmp_blue > 255:
            blue = 255
        else:
            blue = tmp_blue
    
    return [red/255, green/255, blue/255]  # return RGB in a 0-1 range

def convert_wavelength_to_RGB(wavelength):
    # List of RGB values that correlate to the 380-780 wavelength range. Even though this
    # is the exact list from the Cycles code, for some reason it doesn't always match :(
    wavelength_list = ((0.0014,0.0000,0.0065), (0.0022,0.0001,0.0105), (0.0042,0.0001,0.0201),
                       (0.0076,0.0002,0.0362), (0.0143,0.0004,0.0679), (0.0232,0.0006,0.1102),
                       (0.0435,0.0012,0.2074), (0.0776,0.0022,0.3713), (0.1344,0.0040,0.6456),
                       (0.2148,0.0073,1.0391), (0.2839,0.0116,1.3856), (0.3285,0.0168,1.6230),
                       (0.3483,0.0230,1.7471), (0.3481,0.0298,1.7826), (0.3362,0.0380,1.7721),
                       (0.3187,0.0480,1.7441), (0.2908,0.0600,1.6692), (0.2511,0.0739,1.5281),
                       (0.1954,0.0910,1.2876), (0.1421,0.1126,1.0419), (0.0956,0.1390,0.8130),
                       (0.0580,0.1693,0.6162), (0.0320,0.2080,0.4652), (0.0147,0.2586,0.3533),
                       (0.0049,0.3230,0.2720), (0.0024,0.4073,0.2123), (0.0093,0.5030,0.1582),
                       (0.0291,0.6082,0.1117), (0.0633,0.7100,0.0782), (0.1096,0.7932,0.0573),
                       (0.1655,0.8620,0.0422), (0.2257,0.9149,0.0298), (0.2904,0.9540,0.0203),
                       (0.3597,0.9803,0.0134), (0.4334,0.9950,0.0087), (0.5121,1.0000,0.0057),
                       (0.5945,0.9950,0.0039), (0.6784,0.9786,0.0027), (0.7621,0.9520,0.0021),
                       (0.8425,0.9154,0.0018), (0.9163,0.8700,0.0017), (0.9786,0.8163,0.0014),
                       (1.0263,0.7570,0.0011), (1.0567,0.6949,0.0010), (1.0622,0.6310,0.0008),
                       (1.0456,0.5668,0.0006), (1.0026,0.5030,0.0003), (0.9384,0.4412,0.0002),
                       (0.8544,0.3810,0.0002), (0.7514,0.3210,0.0001), (0.6424,0.2650,0.0000),
                       (0.5419,0.2170,0.0000), (0.4479,0.1750,0.0000), (0.3608,0.1382,0.0000),
                       (0.2835,0.1070,0.0000), (0.2187,0.0816,0.0000), (0.1649,0.0610,0.0000),
                       (0.1212,0.0446,0.0000), (0.0874,0.0320,0.0000), (0.0636,0.0232,0.0000),
                       (0.0468,0.0170,0.0000), (0.0329,0.0119,0.0000), (0.0227,0.0082,0.0000),
                       (0.0158,0.0057,0.0000), (0.0114,0.0041,0.0000), (0.0081,0.0029,0.0000),
                       (0.0058,0.0021,0.0000), (0.0041,0.0015,0.0000), (0.0029,0.0010,0.0000),
                       (0.0020,0.0007,0.0000), (0.0014,0.0005,0.0000), (0.0010,0.0004,0.0000),
                       (0.0007,0.0002,0.0000), (0.0005,0.0002,0.0000), (0.0003,0.0001,0.0000),
                       (0.0002,0.0001,0.0000), (0.0002,0.0001,0.0000), (0.0001,0.0000,0.0000),
                       (0.0001,0.0000,0.0000), (0.0001,0.0000,0.0000), (0.0000,0.0000,0.0000))
    
    # normalize wavelength into a number between 0 and 80 and use it as the index for the list
    return wavelength_list[min(80, max(0, int((wavelength - 380) * 0.2)))]

def getHiddenStatus(scene, lights):
    statelist = []
    temparr = []
    for light in lights:
        if light[0]:
            temparr = [light[0], bpy.data.objects[light[0]].hide, bpy.data.objects[light[0]].hide_render]
            statelist.append(temparr)

    temparr = ["WorldEnviroLight", scene.GafferWorldVis, scene.GafferWorldReflOnly]
    statelist.append(temparr)

    scene.GafferLightsHiddenRecord = str(statelist)

def isOnVisibleLayer(obj, scene):
    obj_layers = []
    for i, layer in enumerate(obj.layers):
        if layer == True:
            obj_layers.append(i)

    scene_layers = []
    for i, layer in enumerate(scene.layers):
        if layer == True:
            scene_layers.append(i)

    common = set(obj_layers) & set(scene_layers)

    if common:
        return True
    else:
        return False

def dictOfLights():
    # Create dict of light name as key with node name as value
    lights = stringToNestedList(bpy.context.scene.GafferLights, stripquotes=True)
    lights_with_nodes = []
    light_dict = {}
    if lights:
        for light in lights:  # TODO check if node still exists
            if len(light) > 1:
                lights_with_nodes.append(light[0])
                lights_with_nodes.append(light[2])
        light_dict = dict(lights_with_nodes[i:i + 2] for i in range(0, len(lights_with_nodes), 2))
    return light_dict

def setGafferNode(context, nodetype, tree=None, obj=None):
    if nodetype == 'STRENGTH':
        list_nodeindex = 2
        list_socketindex = 3
    elif nodetype == 'COLOR':
        list_nodeindex = 4
        list_socketindex = 5

    if tree:
        nodetree = tree
    else:
        nodetree = context.space_data.node_tree
    node = nodetree.nodes.active
    lights = stringToNestedList(context.scene.GafferLights, stripquotes=True)

    if obj == None:
        obj = context.object
    for light in lights:
        # TODO poll for pinned nodetree (active object is not necessarily the one that this tree belongs to)
        if light[0] == obj.name:
            light[list_nodeindex] = node.name
            socket_index = 0

            if node.inputs:
                for socket in node.inputs:
                    if socket.type == 'VALUE' and not socket.is_linked:  # use first Value socket as strength
                        light[list_socketindex] = 'i' + str(socket_index)
                        break
                    socket_index += 1
                break
            elif node.outputs:
                for socket in node.outputs:
                    if socket.type == 'VALUE':  # use first Value socket as strength
                        light[list_socketindex] = 'o' + str(socket_index)
                        break
                    socket_index += 1
                break
    # TODO catch if there is no available socket to use
    context.scene.GafferLights = str(lights)

def do_update_falloff(self):
    light = self
    scene = bpy.context.scene
    lights = stringToNestedList(scene.GafferLights, stripquotes=True)
    lightitems = []
    for l in lights:
        if l[0] == light.name:
            lightitems = l
            break

    socket_no = 2
    falloff = light.GafferFalloff
    if falloff == 'linear':
        socket_no = 1
    elif falloff == 'quadratic':
        socket_no = 0

    connections = []
    if light.type == 'LAMP':
        tree = light.data.node_tree
    else:
        tree = bpy.data.materials[lightitems[1]].node_tree

    try:
        node = tree.nodes[lightitems[2]]
        if node.type == 'LIGHT_FALLOFF':
            for outpt in node.outputs:
                if outpt.is_linked:
                    for link in outpt.links:
                        connections.append(link.to_socket)
            for link in connections:
                tree.links.new(node.outputs[socket_no], link)
        else:
            if light.GafferFalloff != 'quadratic':  # No point making Light Falloff node if you're setting it to quadratic and a falloff node already exists
                fnode = tree.nodes.new('ShaderNodeLightFalloff')
                fnode.inputs[0].default_value = node.inputs[int(str(lightitems[3])[-1])].default_value
                fnode.location.x = node.location.x - 250
                fnode.location.y = node.location.y
                tree.links.new(fnode.outputs[socket_no], node.inputs[int(str(lightitems[3])[-1])])
                tree.nodes.active = fnode
                setGafferNode(bpy.context, 'STRENGTH', tree, light)
        hack_force_update(bpy.context, tree.nodes)
    except:
        print ("Warning: do_update_falloff failed, node may not exist anymore")

def _update_falloff(self, context):
    do_update_falloff(self)

def refresh_bgl():
    print ("refreshed bgl")

    if bpy.context.scene.GafferIsShowingRadius:
        bpy.ops.gaffer.show_radius('INVOKE_DEFAULT')
        bpy.ops.gaffer.show_radius('INVOKE_DEFAULT')

    if bpy.context.scene.GafferIsShowingLabel:
        bpy.ops.gaffer.show_label('INVOKE_DEFAULT')
        bpy.ops.gaffer.show_label('INVOKE_DEFAULT')

def draw_rect(x1, y1, x2, y2):
    # For each quad, the draw order is important. Start with bottom left and go anti-clockwise.
    bgl.glBegin(bgl.GL_QUADS)
    bgl.glVertex2f(x1,y1)
    bgl.glVertex2f(x1,y2)
    bgl.glVertex2f(x2,y2)
    bgl.glVertex2f(x2,y1)
    bgl.glEnd()

def draw_corner(x, y, r, corner):
    sides = 16
    if corner == 'BL':
        r1 = 8
        r2 = 12
    elif corner == 'TL':
        r1 = 4
        r2 = 8
    elif corner == 'BR':
        r1 = 12
        r2 = 16
    elif corner == 'TR':
        r1 = 0
        r2 = 4

    bgl.glBegin(bgl.GL_TRIANGLE_FAN)
    bgl.glVertex2f(x, y)
    for i in range(r1, r2+1):
        cosine = r * cos(i * 2 * pi / sides) + x
        sine = r * sin(i * 2 * pi / sides) + y
        bgl.glVertex2f(cosine, sine)
    bgl.glEnd()

def draw_rounded_rect(x1, y1, x2, y2, r):
    draw_rect(x1, y1, x2, y2)  # Main quad
    draw_rect(x1-r, y1, x1, y2)  # Left edge
    draw_rect(x2, y1, x2+r, y2)  # Right edge
    draw_rect(x1, y2, x2, y2+r)  # Top edge
    draw_rect(x1, y1-r, x2, y1)  # Bottom edge
    
    draw_corner(x1, y1, r, 'BL')  # Bottom left
    draw_corner(x1, y2, r, 'TL')  # Top left
    draw_corner(x2, y2, r, 'TR')  # Top right
    draw_corner(x2, y1, r, 'BR')  # Bottom right
    

'''
    OPERATORS
'''
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
        context.scene.GafferColTempExpand = True
        context.scene.GafferLightUIIndex = self.l_index
        return {'FINISHED'}


class GafTempHideList(bpy.types.Operator):

    'Hide color temperature presets'
    bl_idname = 'gaffer.col_temp_hide'
    bl_label = 'Hide Presets'

    def execute(self, context):
        context.scene.GafferColTempExpand = False
        return {'FINISHED'}


class GafShowMore(bpy.types.Operator):

    'Show settings such as MIS, falloff, ray visibility...'
    bl_idname = 'gaffer.more_options_show'
    bl_label = 'Show more options'
    light = bpy.props.StringProperty()

    def execute(self, context):
        exp_list = context.scene.GafferMoreExpand
        # prepend+append funny stuff so that the light name is
        # unique (otherwise Fill_03 would also expand Fill_03.001)
        exp_list += ("_Light:_(" + self.light + ")_")
        context.scene.GafferMoreExpand = exp_list
        return {'FINISHED'}


class GafHideMore(bpy.types.Operator):

    'Hide settings such as MIS, falloff, ray visibility...'
    bl_idname = 'gaffer.more_options_hide'
    bl_label = 'Hide more options'
    light = bpy.props.StringProperty()

    def execute(self, context):
        context.scene.GafferMoreExpand = context.scene.GafferMoreExpand.replace("_Light:_(" + self.light + ")_", "")
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

        statelist = stringToNestedList(scene.GafferLightsHiddenRecord, True)

        if showhide:  # Enter Solo mode
            bpy.ops.gaffer.refresh_lights()
            scene.GafferSoloActive = light
            getHiddenStatus(scene, stringToNestedList(scene.GafferLights, True))
            for l in statelist:  # first check if lights still exist
                if l[0] != "WorldEnviroLight":
                    try:
                        obj = bpy.data.objects[l[0]]
                    except:
                        # TODO not sure if this ever happens, if it does, doesn't it break?
                        getHiddenStatus(scene, stringToNestedList(scene.GafferLights, True))
                        bpy.ops.gaffer.solo()
                        return {'FINISHED'}  # if one of the lights has been deleted/changed, update the list and dont restore visibility

            for l in statelist:  # then restore visibility
                if l[0] != "WorldEnviroLight":
                    obj = bpy.data.objects[l[0]]
                    if obj.name == light or obj.name in linked_lights:
                        obj.hide = False
                        obj.hide_render = False
                    else:
                        obj.hide = True
                        obj.hide_render = True

            if context.scene.render.engine == 'CYCLES':
                if worldsolo:
                    if not scene.GafferWorldVis:
                        scene.GafferWorldVis = True
                else:
                    if scene.GafferWorldVis:
                        scene.GafferWorldVis = False

        else:  # Exit solo
            oldlight = scene.GafferSoloActive
            scene.GafferSoloActive = ''
            for l in statelist:
                if l[0] != "WorldEnviroLight":
                    try:
                        obj = bpy.data.objects[l[0]]
                    except:
                        # TODO not sure if this ever happens, if it does, doesn't it break?
                        bpy.ops.gaffer.refresh_lights()
                        getHiddenStatus(scene, stringToNestedList(scene.GafferLights, True))
                        scene.GafferSoloActive = oldlight
                        bpy.ops.gaffer.solo()
                        return {'FINISHED'}
                    obj.hide = castBool(l[1])
                    obj.hide_render = castBool(l[2])
                elif context.scene.render.engine == 'CYCLES':
                    scene.GafferWorldVis = castBool(l[1])
                    scene.GafferWorldReflOnly = castBool(l[2])

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
        m = []

        if not hasattr(bpy.types.Object, "GafferFalloff"):
            bpy.types.Object.GafferFalloff = bpy.props.EnumProperty(
                name="Light Falloff",
                items=(("constant","Constant","No light falloff"),
                       ("linear","Linear","Fade light strength linearly over the distance it travels"),
                       ("quadratic","Quadratic","(Realisic) Light strength is inversely proportional to the square of the distance it travels")),
                default="quadratic",
                description="The rate at which the light loses intensity over distance",
                update=_update_falloff)
            print ("Created GafferFalloff property")

        light_dict = dictOfLights()

        objects = sorted(scene.objects, key=lambda x: x.name)

        if scene.render.engine == 'BLENDER_RENDER':
            for obj in objects:
                if obj.type == 'LAMP':
                    m.append([obj.name, None, None])  # only use first element of list to keep usage consistent with cycles mode
        elif scene.render.engine == 'CYCLES':
            for obj in objects:
                light_mats = []
                if obj.type == 'LAMP':
                    if obj.data.use_nodes:
                        invalid_node = False
                        if obj.name in light_dict:
                            if light_dict[obj.name] == "None":  # A light that previously did not use nodes (like default light)
                                invalid_node = True
                            elif light_dict[obj.name] not in obj.data.node_tree.nodes:
                                invalid_node = True
                        if obj.name not in light_dict or invalid_node:
                            for node in obj.data.node_tree.nodes:
                                if node.name != "Emission Viewer":
                                    if node.type == 'EMISSION':
                                        if node.outputs[0].is_linked:
                                            if node.inputs[1].is_linked:
                                                socket_index = 0
                                                subnode = node.inputs[1].links[0].from_node
                                                if subnode.inputs:
                                                    for inpt in subnode.inputs:
                                                        if inpt.type == 'VALUE':  # use first Value socket as strength
                                                            m.append([obj.name, None, subnode.name, 'i'+str(socket_index)])
                                                            break
                                            else:
                                                m.append([obj.name, None, node.name, 1])
                                            break
                        else:
                            node = obj.data.node_tree.nodes[light_dict[obj.name]]
                            socket_index = 0
                            if node.inputs:
                                for inpt in node.inputs:
                                    if inpt.type == 'VALUE':  # use first Value socket as strength
                                        m.append([obj.name, None, node.name, 'i'+str(socket_index)])
                                        break
                                    socket_index += 1
                            elif node.outputs:
                                for oupt in node.outputs:
                                    if oupt.type == 'VALUE':  # use first Value socket as strength
                                        m.append([obj.name, None, node.name, 'o'+str(socket_index)])
                                        break
                                    socket_index += 1
                    else:
                        m.append([obj.name, None, None])
                elif obj.type == 'MESH' and len(obj.material_slots) > 0:
                    slot_break = False
                    for slot in obj.material_slots:
                        if slot_break:
                            break  # only use first emission material in slots
                        if slot.material:
                            if slot.material not in light_mats:
                                if slot.material.use_nodes:
                                    invalid_node = False
                                    if obj.name in light_dict:
                                        if light_dict[obj.name] == "None":  # A light that previously did not use nodes (like default light)
                                            invalid_node = True
                                        elif light_dict[obj.name] not in slot.material.node_tree.nodes:
                                            invalid_node = True
                                    if obj.name not in light_dict or invalid_node:
                                        for node in slot.material.node_tree.nodes:
                                            if node.name != "Emission Viewer":
                                                if node.type == 'EMISSION':
                                                    if node.outputs[0].is_linked:
                                                        if node.inputs[1].is_linked:
                                                            socket_index = 0
                                                            subnode = node.inputs[1].links[0].from_node
                                                            if subnode.inputs:
                                                                for inpt in subnode.inputs:
                                                                    if inpt.type == 'VALUE':  # use first Value socket as strength
                                                                        m.append([obj.name, slot.material.name, subnode.name, 'i'+str(socket_index)])
                                                                        light_mats.append(slot.material)
                                                                        slot_break = True
                                                                        break
                                                        else:
                                                            m.append([obj.name, slot.material.name, node.name, 1])
                                                            light_mats.append(slot.material)  # skip this material next time it's checked
                                                            slot_break = True
                                                            break
                                    else:
                                        node = slot.material.node_tree.nodes[light_dict[obj.name]]
                                        socket_index = 0
                                        if node.inputs:
                                            for inpt in node.inputs:
                                                if inpt.type == 'VALUE':  # use first Value socket as strength
                                                    m.append([obj.name, slot.material.name, node.name, 'i'+str(socket_index)])
                                                    break
                                                socket_index += 1
                                        elif node.outputs:
                                            for oupt in node.outputs:
                                                if oupt.type == 'VALUE':  # use first Value socket as strength
                                                    m.append([obj.name, slot.material.name, node.name, 'o'+str(socket_index)])
                                                    break
                                                socket_index += 1

        for light in m:
            obj = bpy.data.objects[light[0]]
            nodes = None
            if obj.type == 'LAMP':
                if obj.data.use_nodes:
                    nodes = obj.data.node_tree.nodes
            else:
                if bpy.data.materials[light[1]].use_nodes:
                    nodes = bpy.data.materials[light[1]].node_tree.nodes
            if nodes:
                if light[2]:
                    if nodes[light[2]].type != 'LIGHT_FALLOFF' and bpy.data.objects[light[0]].GafferFalloff != 'quadratic':
                        bpy.data.objects[light[0]].GafferFalloff = 'quadratic'
        scene.GafferLights = str(m)
        self.report({'INFO'}, "Light list refreshed")
        if scene.GafferSoloActive == '':
            getHiddenStatus(scene, stringToNestedList(scene.GafferLights, True))
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
        lampob = bpy.data.objects[context.scene.GafferSunObject]

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
        varname = nodename + "_" + str(context.scene.GafferVarNameCounter)  # create unique variable name for each node
        context.scene.GafferVarNameCounter += 1

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

        for item in self.objects:
            obj = item[0]
            if not scene.GafferLightRadiusSelectedOnly or obj.select:
                if obj:
                    if obj.data:
                        if obj.data.type in ['POINT', 'SUN', 'SPOT']:  # have to check this again, in case user changes the type while showing radius
                            if not (scene.render.engine == 'BLENDER_RENDER' and obj.data.shadow_method == 'NOSHADOW'):
                                if obj in context.visible_objects and obj.name not in [o.name for o in scene.GafferBlacklist]:
                                    if scene.GafferLightRadiusUseColor:
                                        if item[1][0] == 'BLACKBODY':
                                            color = convert_temp_to_RGB(item[1][1].inputs[0].default_value)
                                        elif item[1][0] == 'WAVELENGTH':
                                            color = convert_wavelength_to_RGB(item[1][1].inputs[0].default_value)
                                        else:
                                            color = item[1]
                                    else:
                                        color = scene.GafferDefaultRadiusColor

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
                                    
                                    bgl.glColor4f(color[0], color[1], color[2], scene.GafferLightRadiusAlpha)
                                    bgl.glEnable(bgl.GL_LINE_SMOOTH)  # anti-aliasing
                                    if scene.GafferLightRadiusXray:
                                        bgl.glClear(bgl.GL_DEPTH_BUFFER_BIT)
                                    if scene.GafferLightRadiusDrawType == 'filled':
                                        bgl.glBegin(bgl.GL_TRIANGLE_FAN)
                                    else:
                                        if scene.GafferLightRadiusDrawType == 'dotted':
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

        if scene.GafferIsShowingRadius:
            scene.GafferIsShowingRadius = False
            GafShowLightRadius.handle_remove(context)
            return {'FINISHED'}
        elif context.area.type == 'VIEW_3D':
            scene.GafferIsShowingRadius = True
            
            context.window_manager.modal_handler_add(self)

            GafShowLightRadius.handle_add(self, context)

            self.objects = []
            for obj in scene.objects:
                # It doesn't make sense to try show the radius for mesh, area or hemi lamps.
                if obj.type == 'LAMP':
                    if obj.data.type in ['POINT', 'SUN', 'SPOT']:
                        color = scene.GafferDefaultRadiusColor
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
        align = bpy.context.scene.GafferLabelAlign

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

        # font_size_factor is used to scale the rectangles based on the font size and DPI, measured against a font size of 62
        font_size_factor = (scene.GafferLabelFontSize/62) * (context.user_preferences.system.dpi/72)
        draw_type = scene.GafferLabelDrawType
        background_color = scene.GafferDefaultLabelBGColor
        text_color = scene.GafferLabelTextColor

        for item in self.objects:
            obj = item[0]
            if obj in context.visible_objects and obj.name not in [o.name for o in scene.GafferBlacklist]:
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

                    char_width = 38 * font_size_factor
                    height = 65 * font_size_factor
                    width = len(obj.name)*char_width

                    x, y = self.alignment(x, y, width, height, scene.GafferLabelMargin*font_size_factor)

                    if draw_type != 'color_text':
                        # Draw background rectangles
                        bgl.glEnable(bgl.GL_BLEND)
                        if draw_type == 'color_bg' and scene.GafferLabelUseColor:
                            bgl.glColor4f(color[0], color[1], color[2], scene.GafferLabelAlpha)
                        else:
                            bgl.glColor4f(background_color[0], background_color[1], background_color[2], scene.GafferLabelAlpha)

                        x1 = x
                        y1 = y-(8 * font_size_factor)
                        x2 = x1+width
                        y2 = y1+height

                        draw_rounded_rect(x1, y1, x2, y2, 20*font_size_factor)

                        bgl.glDisable(bgl.GL_BLEND)

                    # Draw text
                    if draw_type != 'color_bg' and scene.GafferLabelUseColor:
                        bgl.glColor4f(color[0], color[1], color[2], scene.GafferLabelAlpha if draw_type == 'color_text' else 1.0)
                    else:
                        bgl.glColor4f(text_color[0], text_color[1], text_color[2], 1.0)
                    font_id = 1
                    blf.position(font_id, x, y, 0)
                    blf.size(font_id, scene.GafferLabelFontSize, context.user_preferences.system.dpi)
                    blf.draw(font_id, obj.name)

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

        if scene.GafferIsShowingLabel:
            scene.GafferIsShowingLabel = False
            GafShowLightLabel.handle_remove(context)
            return {'FINISHED'}
        elif context.area.type == 'VIEW_3D':
            scene.GafferIsShowingLabel = True
            
            context.window_manager.modal_handler_add(self)

            GafShowLightLabel.handle_add(self, context)

            self.objects = []
            for obj in scene.objects:
                color = scene.GafferDefaultLabelBGColor
                nodes = None
                if obj.type == 'LAMP':
                    if scene.render.engine == 'CYCLES' and obj.data.use_nodes:
                        nodes = obj.data.node_tree.nodes
                elif scene.render.engine == 'CYCLES' and obj.type == 'MESH' and len(obj.material_slots) > 0:
                    for slot in obj.material_slots:
                        if slot.material:
                            if slot.material.use_nodes:
                                if [node for node in slot.material.node_tree.nodes if node.type == 'EMISSION']:
                                    nodes = slot.material.node_tree.nodes
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

                        self.objects.append([obj, color])

                if obj.type == 'LAMP' and not nodes:  # is a lamp but doesnt use_nodes
                    color = obj.data.color
                    self.objects.append([obj, color])

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
        return context.scene.GafferIsShowingRadius or context.scene.GafferIsShowingLabel

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
        blacklist = context.scene.GafferBlacklist
        existing = [obj.name for obj in blacklist]
        for obj in context.selected_objects:
            if obj.name not in existing:
                item = blacklist.add()
                item.name = obj.name

        context.scene.GafferBlacklistIndex = len(context.scene.GafferBlacklist) - 1
        return {'FINISHED'}


class GafRemoveBlacklisted(bpy.types.Operator):

    "Remove the active list item from the blacklist"
    bl_idname = 'gaffer.blacklist_remove'
    bl_label = 'Remove'

    @classmethod
    def poll(cls, context):
        return context.scene.GafferBlacklist

    def execute(self, context):
        blist = context.scene.GafferBlacklist
        index = context.scene.GafferBlacklistIndex

        blist.remove(index)

        if index >= len(blist):
            context.scene.GafferBlacklistIndex = len(blist) - 1

        return {'FINISHED'}


class GafAimLight(bpy.types.Operator):

    "Point the selected lights at a target"
    bl_idname = 'gaffer.aim'
    bl_label = 'Aim'
    target_type = bpy.props.StringProperty()

    def aim (self, context, obj, target=[0,0,0]):
        print ("Aiming " + obj.name + " at " + str(target))

        # Make a dummy Empty to aim at
        n = "DummyEmptyForGafferAim"
        if n in bpy.data.objects:  # Delete dummy if it exists, otherwise we can't use it's name relyably
            bpy.data.objects.remove(bpy.data.objects[n])
        edata = bpy.data.objects.new(n, None)
        context.scene.objects.link(edata)
        empty = context.scene.objects[n]
        empty.location = target

        constraint = obj.constraints.new(type='TRACK_TO')
        constraint.target = empty
        constraint.track_axis = 'TRACK_Z' if obj.type != 'LAMP' else 'TRACK_NEGATIVE_Z'
        constraint.up_axis = 'UP_X'

        orig_selection = context.selected_objects  # store selection
        bpy.ops.object.select_all(action='DESELECT')
        obj.select = True
        bpy.ops.object.visual_transform_apply()

        obj.constraints.remove(constraint)
        context.scene.objects.unlink(empty)
        bpy.data.objects.remove(empty)

        bpy.ops.object.select_all(action='DESELECT')
        for o in orig_selection:
            o.select = True  # restore selection

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

            self.aim(context, active, [avg_x, avg_y, avg_z])

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


'''
    INTERFACE
'''
def draw_renderer_independant(scene, row, light, users=[None, 1]):  # UI stuff that's shown for all renderers
    '''
        Parameters:
        users: a list, 0th position is data name, 1st position is number of users
    '''

    if "_Light:_(" + light.name + ")_" in scene.GafferMoreExpand and not scene.GafferMoreExpandAll:
        row.operator("gaffer.more_options_hide", icon='TRIA_DOWN', text='', emboss=False).light = light.name
    elif not scene.GafferMoreExpandAll:
        row.operator("gaffer.more_options_show", icon='TRIA_RIGHT', text='', emboss=False).light = light.name

    if scene.GafferSoloActive == '':
        # Don't allow names to be edited during solo, will break the record of what was originally hidden
        row.prop(light, 'name', text='')
    else:
        row.label(text=light.name)

    if users[1] > 1:
        row.label(str(users[1]) + " Users")

    visop = row.operator('gaffer.hide_light', text='', icon="%s" % 'RESTRICT_VIEW_ON' if light.hide else 'RESTRICT_VIEW_OFF', emboss=False)
    visop.light = light.name
    visop.dataname = users[0] if users[1] > 1 else "__SINGLE_USER__"
    visop.hide = not light.hide

    selop = row.operator("gaffer.select_light", icon="%s" % 'RESTRICT_SELECT_OFF' if light.select else 'SMALL_TRI_RIGHT_VEC', text="", emboss=False)
    selop.light = light.name
    selop.dataname = users[0] if users[1] > 1 else "__SINGLE_USER__"
    if scene.GafferSoloActive == '':
        solobtn = row.operator("gaffer.solo", icon='ZOOM_SELECTED', text='', emboss=False)
        solobtn.light = light.name
        solobtn.showhide = True
        solobtn.worldsolo = False
        solobtn.dataname = users[0] if users[1] > 1 else "__SINGLE_USER__"
    elif scene.GafferSoloActive == light.name:
        solobtn = row.operator("gaffer.solo", icon='ZOOM_PREVIOUS', text='', emboss=False)
        solobtn.light = light.name
        solobtn.showhide = False
        solobtn.worldsolo = False


def draw_BI_UI(context, layout, lights):
    maincol = layout.column(align=True)
    scene = context.scene

    lights_to_show = []
    # Check validity of list and make list of lights to display
    for light in lights:
        try:
            if light[0]:
                a = bpy.data.objects[light[0][1:-1]]  # will cause exception if obj no longer exists
                if (scene.GafferVisibleLightsOnly and not a.hide) or (not scene.GafferVisibleLightsOnly):
                    if (scene.GafferVisibleLayersOnly and isOnVisibleLayer(a, scene)) or (not scene.GafferVisibleLayersOnly):
                        if a.name not in [o.name for o in scene.GafferBlacklist]:
                            lights_to_show.append(light)
        except:
            box = maincol.box()
            row = box.row(align=True)
            row.label("Light list out of date")
            row.operator('gaffer.refresh_lights', icon='FILE_REFRESH', text='')

    # Don't show lights that share the same data
    duplicates = {}
    '''
    duplicates:
        A dict with the key: object type + data name (cannot use only the name in case of conflicts).
        The values are the number of duplicates for that key.
    '''
    templist = []
    for item in lights_to_show:
        light = scene.objects[item[0][1:-1]]  # drop the apostrophies
        if ('LAMP' + light.data.name) in duplicates:
            duplicates['LAMP' + light.data.name] += 1
        else:
            templist.append(item)
            duplicates['LAMP' + light.data.name] = 1
    lights_to_show = templist

    i = 0
    for item in lights_to_show:
        light = scene.objects[item[0][1:-1]]  # drop the apostrophies

        box = maincol.box()
        rowmain = box.row()
        split = rowmain.split()
        col = split.column()
        row = col.row(align=True)

        users = ['LAMP' + light.data.name, duplicates['LAMP' + light.data.name]]
        draw_renderer_independant(scene, row, light, users)

        # strength
        row = col.row(align=True)
        row.prop(light.data, "type", text='', icon='LAMP_%s' % light.data.type, icon_only=True, emboss=False)
        row.separator()
        row.prop(light.data, 'energy', text="Strength")

        # color
        subcol = row.column(align=True)
        subrow = subcol.row(align=True)
        subrow.scale_x = 0.3
        subrow.prop(light.data, 'color', text='')

        # More Options
        if "_Light:_(" + light.name + ")_" in scene.GafferMoreExpand or scene.GafferMoreExpandAll:
            if light.data.type != 'HEMI':
                if light.data.type == 'AREA':
                    col = box.column()
                    if light.data.shape == 'RECTANGLE':
                        subcol = col.column(align=True)
                        row = subcol.row(align=True)
                        row.prop(light.data, "size", text="Size X")
                        row.prop(light.data, "shadow_ray_samples_x", text="Samples X")
                        row = subcol.row(align=True)
                        row.prop(light.data, "size_y", text="Size Y")
                        row.prop(light.data, "shadow_ray_samples_y", text="Samples Y")
                    else:
                        row = col.row(align=True)
                        row.prop(light.data, "size", text="Size")
                        row.prop(light.data, "shadow_ray_samples_x", text="Samples")
                elif light.data.type == 'SPOT':
                    col = box.column(align=True)
                    row = col.row(align=True)
                    row.prop(light.data, "spot_size", text='Spot Size')
                    row.prop(light.data, "spot_blend", text='Blend')
                    if light.data.shadow_method == 'RAY_SHADOW':
                        row = col.row(align=True)
                        row.prop(light.data, "shadow_soft_size", text="Size")
                        row.prop(light.data, "shadow_ray_samples", text="Samples")
                    col = box.column()
                else:
                    if light.data.shadow_method == 'RAY_SHADOW':
                        col = box.column()
                        row = col.row(align=True)
                        row.prop(light.data, "shadow_soft_size", text="Size")
                        row.prop(light.data, "shadow_ray_samples", text="Samples")

                col.prop(light.data, "shadow_method", text="")

                row = col.row(align=True)
                row.prop(light.data, "use_diffuse", toggle=True)
                row.prop(light.data, "use_specular", toggle=True)
            else:
                row = col.row(align=True)
                row.prop(light.data, "use_diffuse", toggle=True)
                row.prop(light.data, "use_specular", toggle=True)
            if light.data.type in ['SPOT', 'POINT']:
                col.prop(light.data, "falloff_type", text="Falloff")

    if len(lights_to_show) == 0:
        row = maincol.row()
        row.alignment = 'CENTER'
        row.label("No lights to show :)")

    # World
    if context.scene.world:
        world = context.scene.world
        box = layout.box()
        worldcol = box.column(align=True)
        col = worldcol.column(align=True)

        row = col.row(align=True)

        if "_Light:_(WorldEnviroLight)_" in scene.GafferMoreExpand and not scene.GafferMoreExpandAll:
            row.operator("gaffer.more_options_hide", icon='TRIA_DOWN', text='', emboss=False).light = "WorldEnviroLight"
        elif not scene.GafferMoreExpandAll:
            row.operator("gaffer.more_options_show", icon='TRIA_RIGHT', text='', emboss=False).light = "WorldEnviroLight"

        row.label(text="World")
        if scene.GafferSoloActive == '':
            solobtn = row.operator("gaffer.solo", icon='ZOOM_SELECTED', text='', emboss=False)
            solobtn.light = "WorldEnviroLight"
            solobtn.showhide = True
            solobtn.worldsolo = True
        elif scene.GafferSoloActive == "WorldEnviroLight":
            solobtn = row.operator("gaffer.solo", icon='ZOOM_PREVIOUS', text='', emboss=False)
            solobtn.light = "WorldEnviroLight"
            solobtn.showhide = False
            solobtn.worldsolo = True

        col = worldcol.column()
        row = col.row(align=True)

        row.label(text="", icon='WORLD')
        row.separator()

        row.prop(world, 'horizon_color', text='')
        if world.use_sky_blend:
            row.prop(world, 'zenith_color', text='')

        if "_Light:_(WorldEnviroLight)_" in scene.GafferMoreExpand or scene.GafferMoreExpandAll:
            col = worldcol.column()
            row = col.row(align=True)
            row.prop(world, 'use_sky_blend')
            if world.use_sky_blend:
                row.prop(world, 'use_sky_paper', text="Paper", toggle=True)
                row.prop(world, 'use_sky_real', text="Real", toggle=True)

            row = col.row(align=True)
            row.prop(world.light_settings, "use_ambient_occlusion", text="Ambient Occlusion")
            if world.light_settings.use_ambient_occlusion:
                row.prop(world.light_settings, "ao_blend_type", text="")
            if world.light_settings.use_ambient_occlusion:
                row = col.row(align=True)
                row.prop(world.light_settings, "ao_factor")
                row.prop(world.light_settings, "distance")

            col.prop(world.light_settings, "use_environment_light", text="Environment Lighting")
            if world.light_settings.use_environment_light:
                col.prop(world.light_settings, "environment_energy", text='Energy')

            if world.light_settings.use_environment_light or world.light_settings.use_ambient_occlusion:
                if world.light_settings.gather_method == 'APPROXIMATE':
                    col.prop(world.light_settings, "use_indirect_light", text="Indirect Lighting")
                    if world.light_settings.use_indirect_light:
                        row = col.row(align=True)
                        row.prop(world.light_settings, "indirect_factor")
                        row.prop(world.light_settings, "indirect_bounces")

                worldcol.separator()
                col = worldcol.column(align=True)
                row = col.row(align=True)
                row.prop(world.light_settings, "gather_method", expand=True)

                if world.light_settings.gather_method == 'APPROXIMATE':
                    col.prop(world.light_settings, "passes")
                    col.prop(world.light_settings, "error_threshold")
                    col.prop(world.light_settings, "correction")
                else:
                    col.prop(world.light_settings, "samples")


def draw_cycles_UI(context, layout, lights):
    maincol = layout.column(align=False)
    scene = context.scene

    lights_to_show = []
    # Check validity of list and make list of lights to display
    for light in lights:
        try:
            if light[0]:
                a = bpy.data.objects[light[0][1:-1]]  # will cause exception if obj no longer exists
                if (scene.GafferVisibleLightsOnly and not a.hide) or (not scene.GafferVisibleLightsOnly):
                    if a.type != 'LAMP':
                        b = bpy.data.materials[light[1][1:-1]]
                        if b.use_nodes:
                            c = b.node_tree.nodes[light[2][1:-1]]
                    else:
                        if a.data.use_nodes:
                            c = a.data.node_tree.nodes[light[2][1:-1]]
                    if (scene.GafferVisibleLayersOnly and isOnVisibleLayer(a, scene)) or (not scene.GafferVisibleLayersOnly):
                        if a.name not in [o.name for o in scene.GafferBlacklist]:
                            lights_to_show.append(light)
        except:
            box = maincol.box()
            row = box.row(align=True)
            row.label("Light list out of date")
            row.operator('gaffer.refresh_lights', icon='FILE_REFRESH', text='')

    # Don't show lights that share the same data
    duplicates = {}
    '''
    duplicates:
        A dict with the key: object type + data name (cannot use only the name in case of conflicts).
        The values are the number of duplicates for that key.
    '''
    templist = []
    for item in lights_to_show:
        light = scene.objects[item[0][1:-1]]  # drop the apostrophies
        if light.type == 'LAMP':
            if ('LAMP' + light.data.name) in duplicates:
                duplicates['LAMP' + light.data.name] += 1
            else:
                templist.append(item)
                duplicates['LAMP' + light.data.name] = 1
        else:
            mat = bpy.data.materials[item[1][1:-1]]
            if ('MAT' + mat.name) in duplicates:
                duplicates['MAT' + mat.name] += 1
            else:
                templist.append(item)
                duplicates['MAT' + mat.name] = 1
    lights_to_show = templist

    i = 0
    for item in lights_to_show:
        light = scene.objects[item[0][1:-1]]  # drop the apostrophies
        doesnt_use_nodes = False
        if light.type == 'LAMP':
            material = None
            if light.data.use_nodes:
                node_strength = light.data.node_tree.nodes[item[2][1:-1]]
            else:
                doesnt_use_nodes = True
        else:
            material = bpy.data.materials[item[1][1:-1]]
            if material.use_nodes:
                node_strength = material.node_tree.nodes[item[2][1:-1]]
            else:
                doesnt_use_nodes = True

        if doesnt_use_nodes:
            box = maincol.box()
            row = box.row()
            row.label("\"" + light.name + "\" doesn't use nodes!")
            if light.type == 'LAMP':
                row.operator('gaffer.lamp_use_nodes', icon='NODETREE', text='').light = light.name
        else:
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

            box = maincol.box()
            rowmain = box.row()
            split = rowmain.split()
            col = split.column()
            row = col.row(align=True)

            if light.type == 'LAMP':
                users = ['LAMP' + light.data.name, duplicates['LAMP' + light.data.name]]
            else:
                users = ['MAT' + material.name, duplicates['MAT' + material.name]]
            draw_renderer_independant(scene, row, light, users)

            # strength
            row = col.row(align=True)
            strength_sockets = node_strength.inputs
            if socket_strength_type == 'o':
                strength_sockets = node_strength.outputs
            if light.type == 'LAMP':
                row.prop(light.data, "type", text='', icon='LAMP_%s' % light.data.type, icon_only=True, emboss=False)
            else:
                row.label(text='', icon='MESH_GRID')
            row.separator()
            try:
                if ((socket_strength_type == 'i' and not strength_sockets[socket_strength].is_linked) \
                or (socket_strength_type == 'o' and strength_sockets[socket_strength].is_linked)) \
                and hasattr(strength_sockets[socket_strength], "default_value"):
                    row.prop(strength_sockets[socket_strength], 'default_value', text='Strength')
                else:
                    row.label("  Node Invalid")
            except:
                row.label("  Node Invalid")

            # color
            if light.type == 'LAMP':
                nodes = light.data.node_tree.nodes
            else:
                nodes = material.node_tree.nodes
            socket_color = 0
            node_color = None
            emissions = []  # make a list of all linked Emission shaders, use the right-most one
            for node in nodes:
                if node.type == 'EMISSION':
                    if node.outputs[0].is_linked:
                        emissions.append(node)
            if emissions:
                node_color = sorted(emissions, key=lambda x: x.location.x, reverse=True)[0]

                if not node_color.inputs[socket_color].is_linked:
                    subcol = row.column(align=True)
                    subrow = subcol.row(align=True)
                    subrow.scale_x = 0.3
                    subrow.prop(node_color.inputs[socket_color], 'default_value', text='')
                else:
                    from_node = node_color.inputs[socket_color].links[0].from_node
                    if from_node.type == 'RGB':
                        subcol = row.column(align=True)
                        subrow = subcol.row(align=True)
                        subrow.scale_x = 0.3
                        subrow.prop(from_node.outputs[0], 'default_value', text='')
                    elif from_node.type == 'TEX_IMAGE' or from_node.type == 'TEX_ENVIRONMENT':
                        row.prop(from_node, 'image', text='')
                    elif from_node.type == 'BLACKBODY':
                        row.prop(from_node.inputs[0], 'default_value', text='Temperature')
                        if scene.GafferColTempExpand and scene.GafferLightUIIndex == i:
                            row.operator('gaffer.col_temp_hide', text='', icon='MOVE_UP_VEC')
                            col = col.column(align=True)
                            col.separator()
                            col.label("Color Temperature Presets:")
                            ordered_col_temps = OrderedDict(sorted(col_temp.items()))
                            for temp in ordered_col_temps:
                                op = col.operator('gaffer.col_temp_preset', text=temp[3:], icon='COLOR')  # temp[3:] removes number used for ordering
                                op.temperature = temp
                                op.light = light.name
                                if material:
                                    op.material = material.name
                                if node_color:
                                    op.node = node_color.name
                            col.separator()
                        else:
                            row.operator('gaffer.col_temp_show', text='', icon='COLOR').l_index = i
                    elif from_node.type == 'WAVELENGTH':
                        row.prop(from_node.inputs[0], 'default_value', text='Wavelength')

            # More Options
            if "_Light:_(" + light.name + ")_" in scene.GafferMoreExpand or scene.GafferMoreExpandAll:
                col = box.column()
                row = col.row(align=True)
                if light.type == 'LAMP':
                    if light.data.type == 'AREA':
                        if light.data.shape == 'RECTANGLE':
                            row.prop(light.data, 'size')
                            row.prop(light.data, 'size_y')
                            row = col.row(align=True)
                        else:
                            row.prop(light.data, 'size')
                    else:
                        row.prop(light.data, 'shadow_soft_size', text='Size')

                    if scene.cycles.progressive == 'BRANCHED_PATH':
                        row.prop(light.data.cycles, "samples")

                    row = col.row(align=True)
                    row.prop(light.data.cycles, "use_multiple_importance_sampling", text='MIS', toggle=True)
                    row.prop(light.data.cycles, "cast_shadow", text='Shadows', toggle=True)
                    row.separator()
                    row.prop(light.cycles_visibility, "diffuse", text='Diff', toggle=True)
                    row.prop(light.cycles_visibility, "glossy", text='Spec', toggle=True)

                    if light.data.type == 'SPOT':
                        row = col.row(align=True)
                        row.prop(light.data, "spot_size", text='Spot Size')
                        row.prop(light.data, "spot_blend", text='Blend')
                else:  # MESH light
                    row.prop(material.cycles, "sample_as_light", text='MIS', toggle=True)
                    row.separator()
                    row.prop(light.cycles_visibility, "camera", text='Cam', toggle=True)
                    row.prop(light.cycles_visibility, "diffuse", text='Diff', toggle=True)
                    row.prop(light.cycles_visibility, "glossy", text='Spec', toggle=True)
                if hasattr(light, "GafferFalloff"):
                    drawfalloff = True
                    if light.type == 'LAMP':
                        if light.data.type == 'SUN' or light.data.type == 'HEMI':
                            drawfalloff = False
                    if drawfalloff:
                        col.prop(light, "GafferFalloff", text="Falloff")
                        if node_strength.type != 'LIGHT_FALLOFF' and light.GafferFalloff != 'quadratic':
                            col.label("Light Falloff node is missing", icon="ERROR")
            i += 1

    if len(lights_to_show) == 0:
        row = maincol.row()
        row.alignment = 'CENTER'
        row.label("No lights to show :)")

    # World
    if context.scene.world:
        world = context.scene.world
        box = layout.box()
        worldcol = box.column(align=True)
        col = worldcol.column(align=True)

        row = col.row(align=True)

        if "_Light:_(WorldEnviroLight)_" in scene.GafferMoreExpand and not scene.GafferMoreExpandAll:
            row.operator("gaffer.more_options_hide", icon='TRIA_DOWN', text='', emboss=False).light = "WorldEnviroLight"
        elif not scene.GafferMoreExpandAll:
            row.operator("gaffer.more_options_show", icon='TRIA_RIGHT', text='', emboss=False).light = "WorldEnviroLight"

        row.label(text="World")
        row.prop(scene, "GafferWorldVis", text="", icon='%s' % 'RESTRICT_VIEW_OFF' if scene.GafferWorldVis else 'RESTRICT_VIEW_ON', emboss=False)

        if scene.GafferSoloActive == '':
            solobtn = row.operator("gaffer.solo", icon='ZOOM_SELECTED', text='', emboss=False)
            solobtn.light = "WorldEnviroLight"
            solobtn.showhide = True
            solobtn.worldsolo = True
        elif scene.GafferSoloActive == "WorldEnviroLight":
            solobtn = row.operator("gaffer.solo", icon='ZOOM_PREVIOUS', text='', emboss=False)
            solobtn.light = "WorldEnviroLight"
            solobtn.showhide = False
            solobtn.worldsolo = True

        col = worldcol.column()
        row = col.row(align=True)

        row.label(text="", icon='WORLD')
        row.separator()

        color_node = None
        if world.use_nodes:
            backgrounds = []  # make a list of all linked Background shaders, use the right-most one
            background = None
            for node in world.node_tree.nodes:
                if node.type == 'BACKGROUND':
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
                    while strength_node == None and i < 100:  # limitted to 100 chained nodes
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
                                row.prop(socket, 'default_value', text="Strength")
                                break
                else:
                    row.prop(background.inputs[1], "default_value", text="Strength")

                # Color
                if background.inputs[0].is_linked:
                    current_node = background.inputs[0].links[0].from_node
                    i = 0  # Failsafe in case of infinite loop (which can happen from accidental cyclic links)
                    while color_node == None and i < 100:  # limitted to 100 chained nodes
                        i += 1
                        connected_inputs = False
                        for socket in current_node.inputs:
                            # stop at node end of chain, or node with only vector inputs:
                            if socket.type != 'VECTOR' and socket.is_linked:
                                connected_inputs = True
                                current_node = socket.links[0].from_node
                        if not connected_inputs:
                            color_node = current_node

                    if color_node.type == 'TEX_IMAGE' or color_node.type == 'TEX_ENVIRONMENT':
                        row.prop(color_node, 'image', text='')
                    elif color_node.type == 'TEX_SKY':
                        row.prop(color_node, 'sun_direction', text='')
                    else:
                        if color_node.inputs:
                            for socket in color_node.inputs:
                                if socket.type == 'RGBA':  # use first color socket
                                    row.prop(socket, 'default_value', text='')
                                    break
                else:
                    row.prop(background.inputs[0], "default_value", text="")
            else:
                row.label("No node found!")
        else:
            row.prop(world, 'horizon_color', text='')

        # Extra
        if "_Light:_(WorldEnviroLight)_" in scene.GafferMoreExpand or scene.GafferMoreExpandAll:
            worldcol.separator()
            col = worldcol.column()
            row = col.row()
            row.prop(world.cycles, "sample_as_light", text="MIS", toggle=True)
            row.prop(scene, "GafferWorldReflOnly", text="Refl Only")
            if world.cycles.sample_as_light:
                col = worldcol.column()
                row = col.row(align=True)
                row.prop(world.cycles, "sample_map_resolution", text="MIS res")
                if scene.cycles.progressive == 'BRANCHED_PATH':
                    row.prop(world.cycles, "samples", text="Samples")
            worldcol.separator()
            col = worldcol.column(align=True)
            col.prop(world.light_settings, "use_ambient_occlusion", text="Ambient Occlusion")
            if world.light_settings.use_ambient_occlusion:
                row = col.row(align=True)
                row.prop(world.light_settings, "ao_factor")
                row.prop(world.light_settings, "distance")

            if color_node:
                if color_node.type == 'TEX_SKY':
                    if world.node_tree and world.use_nodes:
                        col = worldcol.column(align = True)
                        row = col.row(align = True)
                        if context.scene.GafferSunObject:
                            row.operator('gaffer.link_sky_to_sun', icon="LAMP_SUN").node_name = color_node.name
                        else:
                            row.label("Link Sky Texture:")
                        row.prop_search(context.scene, "GafferSunObject", bpy.data, "objects", text="")


class GafferPanelLights(bpy.types.Panel):

    bl_label = "Lights"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_category = "Gaffer"

    @classmethod
    def poll(cls, context):
        return True if context.scene.render.engine in supported_renderers else False

    def draw(self, context):
        scene = context.scene
        lights_str = scene.GafferLights
        lights = stringToNestedList(lights_str)
        layout = self.layout

        col = layout.column(align=True)
        row = col.row(align=True)
        if scene.GafferSoloActive != "":  # if in solo mode
            solobtn = row.operator("gaffer.solo", icon='ZOOM_PREVIOUS', text='')
            solobtn.light = "None"
            solobtn.showhide = False
            solobtn.worldsolo = False
        row.operator('gaffer.refresh_lights', text="Refresh", icon='FILE_REFRESH')  # may not be needed if drawing errors are cought correctly (eg newly added lights)
        row.prop(scene, "GafferVisibleLayersOnly", text='', icon='LAYER_ACTIVE')
        row.prop(scene, "GafferVisibleLightsOnly", text='', icon='VISIBLE_IPO_ON')
        row.prop(scene, "GafferMoreExpandAll", text='', icon='PREFERENCES')

        if scene.GafferSoloActive != '':
            try:
                o = bpy.data.objects[scene.GafferSoloActive]  # Will cause exception if object by that name doesn't exist
            except:
                if scene.GafferSoloActive != "WorldEnviroLight":
                    # In case solo'd light changes name, theres no other way to exit solo mode
                    col.separator()
                    row = col.row()
                    row.label("       ")
                    solobtn = row.operator("gaffer.solo", icon='ZOOM_PREVIOUS', text='Reset Solo')
                    solobtn.showhide = False
                    row.label("       ")

        if scene.render.engine == 'BLENDER_RENDER':
            draw_BI_UI(context, layout, lights)
        elif scene.render.engine == 'CYCLES':
            draw_cycles_UI(context, layout, lights)
        else:
            layout.label ("Render Engine not supported!")


class GafferPanelTools(bpy.types.Panel):

    bl_label = "Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_category = "Gaffer"

    @classmethod
    def poll(cls, context):
        return True if context.scene.render.engine in supported_renderers else False

    def draw(self, context):
        scene = context.scene
        layout = self.layout

        maincol = layout.column()

        # Aiming
        col = maincol.column(align = True)
        col.label("Aim:", icon='MAN_TRANS')
        col.operator('gaffer.aim', text="Selection at 3D cursor").target_type = 'CURSOR'
        col.operator('gaffer.aim', text="Selected at active").target_type = 'ACTIVE'
        col.operator('gaffer.aim', text="Active at selected").target_type = 'SELECTED'

        maincol.separator()

        # Draw Radius
        box = maincol.box() if scene.GafferIsShowingRadius else maincol.column()
        sub = box.column(align=True)
        row = sub.row(align=True)
        row.operator('gaffer.show_radius', text="Show Radius" if not scene.GafferIsShowingRadius else "Hide Radius", icon='META_EMPTY')
        if scene.GafferIsShowingRadius:
            row.operator('gaffer.refresh_bgl', text="", icon="FILE_REFRESH")
            sub.prop(scene, 'GafferLightRadiusAlpha', slider=True)
            row = sub.row(align=True)
            row.active = scene.GafferIsShowingRadius
            row.prop(scene, 'GafferLightRadiusDrawType', text="")
            row.prop(scene, 'GafferLightRadiusUseColor')
            row = sub.row(align=True)
            row.active = scene.GafferIsShowingRadius
            row.prop(scene, 'GafferLightRadiusXray')
            row.prop(scene, 'GafferLightRadiusSelectedOnly')
            row = sub.row(align=True)
            row.prop(scene, 'GafferDefaultRadiusColor')

        maincol.separator()

        # Draw Label
        box = maincol.box() if scene.GafferIsShowingLabel else maincol.column()
        sub = box.column(align=True)
        row = sub.row(align=True)
        row.operator('gaffer.show_label', text="Show Label" if not scene.GafferIsShowingLabel else "Hide Label", icon='LONGDISPLAY')
        if scene.GafferIsShowingLabel:
            row.operator('gaffer.refresh_bgl', text="", icon="FILE_REFRESH")
            label_draw_type = scene.GafferLabelDrawType
            sub.prop(scene, 'GafferLabelAlpha', slider=True)
            sub.prop(scene, 'GafferLabelFontSize')
            row = sub.row(align=True)
            row.prop(scene, 'GafferLabelDrawType', text='')
            row.prop(scene, 'GafferLabelUseColor')
            if label_draw_type == 'color_bg' or not scene.GafferLabelUseColor:
                row = sub.row(align=True)
                row.prop(scene, 'GafferLabelTextColor')
            if label_draw_type == 'plain_bg' or (not scene.GafferLabelUseColor and label_draw_type != 'color_text'):
                row = sub.row(align=True)
                row.prop(scene, 'GafferDefaultLabelBGColor')
            row = sub.row(align=True)
            row.prop(scene, 'GafferLabelAlign', text="")
            if scene.GafferLabelAlign != 'c':
                row.prop(scene, 'GafferLabelMargin')

        maincol.separator()

        # Blacklist
        box = maincol.box()
        sub = box.column(align=True)
        sub.label('Blacklist:')
        if context.scene.GafferBlacklist:
            sub.template_list("OBJECT_UL_object_list", "", context.scene, "GafferBlacklist", scene, "GafferBlacklistIndex", rows=2)
        row = sub.row(align=True)
        row.operator('gaffer.blacklist_add', icon='ZOOMIN')
        row.operator('gaffer.blacklist_remove', icon='ZOOMOUT')


class OBJECT_UL_object_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        obj = item
        layout.prop(obj, 'name', text="", emboss=False)
        

def gaffer_node_menu_func(self, context):
    if context.space_data.node_tree.type == 'SHADER' and context.space_data.shader_type == 'OBJECT':
        light_dict = dictOfLights()
        if context.object.name in light_dict:
            layout = self.layout
            layout.operator('gaffer.node_set_strength')


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


def _update_world_refl_only(self, context):
    do_set_world_refl_only(context)
    hack_force_update(context, context.scene.world.node_tree.nodes)


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


def _update_world_vis(self, context):
    do_set_world_vis(context)
    hack_force_update(context, context.scene.world.node_tree.nodes)


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

    bpy.types.NODE_PT_active_node_generic.append(gaffer_node_menu_func)

    bpy.utils.register_module(__name__)

    bpy.types.Scene.GafferBlacklist = bpy.props.CollectionProperty(type=BlacklistedObject)  # must be registered after classes

    bpy.app.handlers.load_post.append(load_handler)

def unregister():
    bpy.app.handlers.load_post.remove(load_handler)

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

    bpy.types.NODE_PT_active_node_generic.remove(gaffer_node_menu_func)

    bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
    register()
