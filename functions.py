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
from collections import OrderedDict
import bgl, blf
from math import pi, cos, sin, log
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.app.handlers import persistent

from .constants import *

'''
    FUNCTIONS
'''

def refresh_light_list(scene):
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
    scene.gaf_props.Lights = str(m)

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
    # normalize wavelength into a number between 0 and 80 and use it as the index for the list
    return wavelength_list[min(80, max(0, int((wavelength - 380) * 0.2)))]

def getHiddenStatus(scene, lights):
    statelist = []
    temparr = []
    for light in lights:
        if light[0]:
            temparr = [light[0], bpy.data.objects[light[0]].hide, bpy.data.objects[light[0]].hide_render]
            statelist.append(temparr)

    temparr = ["WorldEnviroLight", scene.gaf_props.WorldVis, scene.gaf_props.WorldReflOnly]
    statelist.append(temparr)

    scene.gaf_props.LightsHiddenRecord = str(statelist)

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
    lights = stringToNestedList(bpy.context.scene.gaf_props.Lights, stripquotes=True)
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
    lights = stringToNestedList(context.scene.gaf_props.Lights, stripquotes=True)

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
        force_update(bpy.context, light)
    except:
        print ("Warning: do_update_falloff failed, node may not exist anymore")

def _update_falloff(self, context):
    do_update_falloff(self)

def refresh_bgl():
    print ("refreshed bgl")

    if bpy.context.scene.gaf_props.IsShowingRadius:
        bpy.ops.gaffer.show_radius('INVOKE_DEFAULT')
        bpy.ops.gaffer.show_radius('INVOKE_DEFAULT')

    if bpy.context.scene.gaf_props.IsShowingLabel:
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
