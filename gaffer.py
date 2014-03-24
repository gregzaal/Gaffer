# ##### BEGIN GPL LICENSE BLOCK #####
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
# ##### END GPL LICENSE BLOCK #####

bl_info = {
    "name": "Gaffer",
    "description": "Manage all your lights together quickly and efficiently from a single panel",
    "author": "Greg Zaal",
    "version": (0, 1, 1),
    "blender": (2, 69, 1),
    "location": "3D View > Tools",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "3D View"}

import bpy
from collections import OrderedDict

'''
TODO:
    work for BI
    poll funcs
    custom node for color or strength
    aim lamp at cursor
    settings for world light

    "More" button:
        Connect Wavelength/Blackbody to colour
        Falloff

    Fix:
        when emission is disconnected, doesn't register as light
'''

col_temp={"01_Flame (1700)": 1700,
          "02_Tungsten (3200)": 3200,
          "03_Sunset (5000)": 5000,
          "04_Daylight (5500)": 5500,
          "05_Overcast (6500)": 6500,
          "06_Monitor (5500)": 5500,
          "07_Shade (8000)": 8000,
          "08_LCD (10500)": 10500,
          "09_Sky (12000)": 12000}

'''
    FUNCTIONS
'''
def stringToList(str="", stripquotes=False):
    raw=str.split(", ")
    raw[0]=(raw[0])[1:]
    raw[-1]=(raw[-1])[:-1]
    if stripquotes:
        tmplist=[]
        for item in raw:
            tmpvar=item
            if tmpvar.startswith("'"):
                item=tmpvar[1:-1]
            tmplist.append(item)
        raw=tmplist
    return raw

def stringToNestedList(str="", stripquotes=False):
    raw=str.split("], ")
    raw[0]=(raw[0])[1:]
    raw[-1]=(raw[-1])[:-2]
    i=0
    for item in raw:
        raw[i]+=']'
        i+=1
    newraw=[]
    for item in raw:
        newraw.append(stringToList(item,stripquotes))
    return newraw

def castBool(str):
    if str=='True':
        return True
    else:
        return False

def setColTemp(node, temp):
    node.inputs[0].default_value=temp
    
def getHiddenStatus(scene, lights):
    statelist=[]
    temparr=[]
    for light in lights:
        temparr=[light[0], bpy.data.objects[light[0]].hide, bpy.data.objects[light[0]].hide_render]
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

    common = set(obj_layers)&set(scene_layers)

    if common:
        return True
    else:
        return False

def isMeshLight(obj):
    if obj.type != 'MESH':
        return False  # Not a mesh
    if len(obj.material_slots) == 0:
        return False  # No materials

    for slot in obj.material_slots:
        if slot.material:
            if slot.material.use_nodes:
                for node in slot.material.node_tree.nodes:
                    if node.type == 'EMISSION':
                        if node.outputs[0].is_linked:
                            return True

def dictOfLights():
    # Create dict of light name as key with node name as value
    lights=stringToNestedList(bpy.context.scene.GafferLights, stripquotes=True)
    lights_with_nodes = []
    light_dict = {}
    if lights:
        for light in lights:  # TODO check if node still exists
            if len(light) > 1:
                print ("light: " + str(light) + " " + str(len(lights)))
                lights_with_nodes.append(light[0])
                lights_with_nodes.append(light[2])
        light_dict = dict(lights_with_nodes[i:i+2] for i in range(0, len(lights_with_nodes), 2))
    return light_dict


'''
    OPERATORS
'''
class GafSetTemp(bpy.types.Operator):
    'Set the color temperature to a preset'
    bl_idname='gaffer.col_temp_preset'
    bl_label='Color Temperature Preset'
    temperature=bpy.props.StringProperty()
    light=bpy.props.StringProperty()
    material=bpy.props.StringProperty()
    node=bpy.props.StringProperty()
    
    def execute(self,context):
        #global col_temp
        light=context.scene.objects[self.light]
        if light.type == 'LAMP':
            node = light.data.node_tree.nodes[self.node]
        else:
            node = bpy.data.materials[self.material].node_tree.nodes[self.node]
        node.inputs[0].links[0].from_node.inputs[0].default_value=col_temp[self.temperature]
        return {'FINISHED'}

class GafTempShowList(bpy.types.Operator):
    'Set the color temperature to a preset'
    bl_idname='gaffer.col_temp_show'
    bl_label='Color Temperature Preset'
    l_index=bpy.props.IntProperty()
    
    def execute(self,context):
        context.scene.GafferColTempExpand=True
        context.scene.GafferLightUIIndex=self.l_index        
        return {'FINISHED'}
class GafTempHideList(bpy.types.Operator):
    'Hide color temperature presets'
    bl_idname='gaffer.col_temp_hide'
    bl_label='Hide Presets'
    
    def execute(self,context):
        context.scene.GafferColTempExpand=False   
        return {'FINISHED'}

class GafShowMore(bpy.types.Operator):
    'Show settings such as MIS, falloff, ray visibility...'
    bl_idname='gaffer.more_options_show'
    bl_label='Show more options'
    light=bpy.props.StringProperty()
    
    def execute(self,context):
        exp_list = context.scene.GafferMoreExpand
        # prepend+append funny stuff so that the light name is
        # unique (otherwise Fill_03 would also expand Fill_03.001)
        exp_list += ("_Light:_("+self.light+")_")
        context.scene.GafferMoreExpand=exp_list
        return {'FINISHED'}
class GafHideMore(bpy.types.Operator):
    'Hide settings such as MIS, falloff, ray visibility...'
    bl_idname='gaffer.more_options_hide'
    bl_label='Hide more options'
    light=bpy.props.StringProperty()
    
    def execute(self,context):
        context.scene.GafferMoreExpand=context.scene.GafferMoreExpand.replace(self.light, "")
        return {'FINISHED'}

class GafHideShowLight(bpy.types.Operator):
    'Hide/Show this light (in viewport and in render)'
    bl_idname='gaffer.hide_light'
    bl_label='Hide Light'
    light=bpy.props.StringProperty()
    hide=bpy.props.BoolProperty()
    
    def execute(self,context):
        light = bpy.data.objects[self.light]
        light.hide = self.hide
        light.hide_render = self.hide
        return {'FINISHED'}

class GafSelectLight(bpy.types.Operator):
    'Select this light'
    bl_idname='gaffer.select_light'
    bl_label='Select'
    light=bpy.props.StringProperty()
    
    def execute(self,context):
        obj=bpy.data.objects[self.light]
        bpy.ops.object.select_all(action='DESELECT')
        obj.select=True
        context.scene.objects.active=obj
        return {'FINISHED'}

class GafSolo(bpy.types.Operator):
    'Hide all other lights but this one'
    bl_idname='gaffer.solo'
    bl_label='Solo Light'
    light=bpy.props.StringProperty()
    showhide=bpy.props.BoolProperty()
    
    def execute(self,context):
        light=self.light
        showhide=self.showhide
        scene=context.scene
        
        statelist=stringToNestedList(scene.GafferLightsHiddenRecord, True)
            
        if showhide:
            bpy.ops.gaffer.refresh_lights()
            scene.GafferSoloActive=light
            getHiddenStatus(scene, stringToNestedList(scene.GafferLights, True))
            for l in statelist: # first check if lights still exist
                try:
                    obj = bpy.data.objects[l[0]]
                except:
                    getHiddenStatus(scene, stringToNestedList(scene.GafferLights, True))
                    bpy.ops.gaffer.solo()
                    return {'FINISHED'} # if one of the lights has been deleted/changed, update the list and dont restore visibility
                    
            for l in statelist: # then restore visibility
                obj = bpy.data.objects[l[0]]
                if obj.name != light:
                    obj.hide = True
                    obj.hide_render = True
                else:
                    obj.hide = False
                    obj.hide_render = False
                    
        else:
            oldlight=scene.GafferSoloActive
            scene.GafferSoloActive=''
            for l in statelist:
                try:
                    obj = bpy.data.objects[l[0]]
                except:
                    bpy.ops.gaffer.refresh_lights()
                    getHiddenStatus(scene, stringToNestedList(scene.GafferLights, True))
                    scene.GafferSoloActive=oldlight
                    bpy.ops.gaffer.solo()
                    return {'FINISHED'}
                obj.hide = castBool(l[1])
                obj.hide_render = castBool(l[2])
        
        return {'FINISHED'}

class GafLampUseNodes(bpy.types.Operator):
    'Make this lamp use nodes'
    bl_idname='gaffer.lamp_use_nodes'
    bl_label='Use Nodes'
    light=bpy.props.StringProperty()
    
    def execute(self,context):
        obj=bpy.data.objects[self.light]
        if obj.type=='LAMP':
            obj.data.use_nodes=True
        bpy.ops.gaffer.refresh_lights()
        return {'FINISHED'}


def setGafferNode(context, nodetype):
    if nodetype == 'STRENGTH':
        list_nodeindex = 2
        list_socketindex = 3
    elif nodetype == 'COLOR':
        list_nodeindex = 4
        list_socketindex = 5

    node = context.space_data.node_tree.nodes.active
    lights=stringToNestedList(context.scene.GafferLights, stripquotes=True)
    for light in lights:
        # TODO poll for pinned nodetree (active object is not necessarily the one that this tree belongs to) 
        if light[0] == context.object.name:
            light[list_nodeindex] = node.name
            socket_index = 0
            for inpt in node.inputs:
                if inpt.type == 'VALUE' and not inpt.is_linked:  # use first Value socket as strength
                    light[list_socketindex] = socket_index
                    break
                socket_index += 1
            break
    context.scene.GafferLights=str(lights)

class GafNodeSetStrength(bpy.types.Operator):
    "Use this node's first Value input as the Strength slider for this light in the Gaffer panel"
    bl_idname='gaffer.node_set_strength'
    bl_label='Set as Gaffer Strength'
    # current_index=bpy.props.IntProperty()
    # do_nothing=bpy.props.BoolProperty()
    
    # TODO poll if object is not light
    def execute(self,context):
        setGafferNode(context, 'STRENGTH')
        return {'FINISHED'}


class GafRefreshLightList(bpy.types.Operator):
    'Refresh the list of lights'
    bl_idname='gaffer.refresh_lights'
    bl_label='Refresh Light List'
    
    def execute(self,context):
        scene=context.scene
        m=[]

        light_dict = dictOfLights()

        # TODO refresh a specific light
        for obj in scene.objects:
            light_mats = []
            if obj.type == 'LAMP':
                if obj.data.use_nodes:
                    no_node_specified = False
                    if obj.name in light_dict:
                        if light_dict[obj.name] == "None":  # A light that previously did not use nodes (like default light)
                            no_node_specified = True
                    if obj.name not in light_dict or no_node_specified:
                        for node in obj.data.node_tree.nodes:
                            if node.type == 'EMISSION':
                                if node.outputs[0].is_linked:
                                    socket_index = 0
                                    for inpt in node.inputs:  # TODO handle if all sockets are linked or non are Value (check nodes connected to inputs)
                                        if inpt.type == 'VALUE' and not inpt.is_linked:  # use first Value socket as strength
                                            m.append([obj.name, None, node.name, socket_index])
                                            break
                                        socket_index += 1
                                    break
                    else:
                        node = obj.data.node_tree.nodes[light_dict[obj.name]]
                        socket_index = 0
                        for inpt in node.inputs:
                            if inpt.type == 'VALUE' and not inpt.is_linked:  # use first Value socket as strength
                                m.append([obj.name, None, node.name, socket_index])
                                break
                            socket_index += 1
                else:
                    m.append([obj.name, None, None])
            elif obj.type == 'MESH' and len (obj.material_slots) > 0:
                slot_break = False
                for slot in obj.material_slots:
                    if slot_break:
                        break  # only use first emission material in slots
                    if slot.material:
                        if slot.material.use_nodes:
                            for node in slot.material.node_tree.nodes:
                                if node.type == 'EMISSION':
                                    if node.outputs[0].is_linked:
                                        socket_index = 0
                                        for inpt in node.inputs:  # TODO handle if all sockets are linked or non are Value (check nodes connected to inputs)
                                            if inpt.type == 'VALUE' and not inpt.is_linked:  # use first Value socket as strength
                                                m.append([obj.name, slot.material.name, node.name, socket_index])
                                                break
                                            socket_index += 1
                                        light_mats.append(slot.material)  # TODO (currently unused) if material is already a light, dont loop through nodes
                                        #m.append([obj.name, slot.material.name, node.name])  # TODO same as above
                                        slot_break = True
                                        break
                
        # check if anything's changed
        mcheck=m
        ocheck=stringToNestedList(scene.GafferLights, stripquotes=True)
        mcheck.sort()
        ocheck.sort()
        if mcheck==ocheck:
            self.report({'INFO'}, "Nothing Changed")
        else:        
            scene.GafferLights=str(m)
            self.report({'INFO'}, "Light list refreshed")
            if scene.GafferSoloActive=='':
                getHiddenStatus(scene, stringToNestedList(scene.GafferLights, True))
        return {'FINISHED'}
    

'''
    INTERFACE
'''
class GafferPanel(bpy.types.Panel):
    bl_label = "Gaffer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_category = "Gaffer"
    
    def draw (self, context):
        scene=context.scene
        lights_str=scene.GafferLights
        lights=stringToNestedList(lights_str)
        layout=self.layout

        col=layout.column(align=True)
        row=col.row(align=True)
        row.operator('gaffer.refresh_lights', icon='FILE_REFRESH') # may not be needed if drawing errors are cought correctly (eg newly added lights)
        row.prop(scene, "GafferVisibleLayersOnly", text='', icon='LAYER_ACTIVE')
        row.prop(scene, "GafferMoreExpandAll", text='', icon='PREFERENCES')

        if scene.GafferSoloActive != '':
            try:
                o=bpy.data.objects[scene.GafferSoloActive]
            except:
                # In case solo'd light changes name, theres no other way to exit solo mode
                col.separator()
                row=col.row()
                row.label("       ")
                solobtn = row.operator("gaffer.solo", icon='ZOOM_PREVIOUS', text='Reset Solo')
                solobtn.showhide=False
                row.label("       ")

        maincol=layout.column(align=True)

        lights_to_show = []
        # Check validity of list and make list of lights to display
        for light in lights:
            try:#if True:
                if scene.GafferVisibleLayersOnly:
                    a = bpy.data.objects[light[0][1:-1]]  # abc vars aren't used, but will cause exception
                    if light[1] != 'None' and light[1] != "'None'":
                        b = bpy.data.materials[light[1][1:-1]]
                        if b.use_nodes:
                            c = b.node_tree.nodes[light[2][1:-1]]
                    else:
                        if a.data.use_nodes:
                            c = a.data.node_tree.nodes[light[2][1:-1]]
                    if isOnVisibleLayer(bpy.data.objects[light[0][1:-1]], scene):
                        lights_to_show.append(light)
                else:
                    a = bpy.data.objects[light[0][1:-1]]  # abc vars aren't used, but will cause exception
                    if light[1] != 'None' and light[1] != "'None'":
                        b = bpy.data.materials[light[1][1:-1]]
                        if b.use_nodes:
                            c = b.node_tree.nodes[light[2][1:-1]]
                    else:
                        if a.data.use_nodes:
                            c = a.data.node_tree.nodes[light[2][1:-1]]
                    lights_to_show.append(light)
            except:
                box=maincol.box()
                row=box.row(align=True)
                row.label("Light list out of date")
                row.operator('gaffer.refresh_lights', icon='FILE_REFRESH', text='')

        i=0
        for item in lights_to_show:
            light=scene.objects[item[0][1:-1]] #drop the apostrophies
            doesnt_use_nodes = False
            if light.type == 'LAMP':
                material = None
                if light.data.use_nodes:
                    node_strength = light.data.node_tree.nodes[item[2][1:-1]]
                else: doesnt_use_nodes = True
            else:
                material = bpy.data.materials[item[1][1:-1]]
                if material.use_nodes:
                    node_strength = material.node_tree.nodes[item[2][1:-1]]
                else: doesnt_use_nodes = True

            if doesnt_use_nodes:
                box=maincol.box()
                row=box.row()
                row.label("\""+light.name+"\" doesn't use nodes!")
                row.operator('gaffer.lamp_use_nodes', icon='NODETREE', text='').light=light.name
            else:
                if item[3].startswith("'"):
                    socket_strength = int(item[3][1:-1])
                else:
                    socket_strength = int(item[3])

                box=maincol.box()
                rowmain=box.row()
                split=rowmain.split()
                col=split.column()
                row=col.row(align=True)

                if "_Light:_("+light.name+")_" in scene.GafferMoreExpand and not scene.GafferMoreExpandAll:
                    row.operator("gaffer.more_options_hide", icon='TRIA_DOWN', text='', emboss=False).light=light.name
                elif not scene.GafferMoreExpandAll:
                    row.operator("gaffer.more_options_show", icon='TRIA_RIGHT', text='', emboss=False).light=light.name

                if scene.GafferSoloActive == '':
                    # Don't allow names to be edited during solo, will break the record of what was originally hidden
                    row.prop(light, 'name', text='')
                else:
                    row.label(text=light.name)
                visop = row.operator('gaffer.hide_light', text='', icon="%s" % 'RESTRICT_VIEW_ON' if light.hide else 'RESTRICT_VIEW_OFF', emboss=False)
                visop.light = light.name
                if light.hide:
                    visop.hide = False
                else:
                    visop.hide = True
                select_icon='RESTRICT_SELECT_ON'
                if light.select:
                    select_icon='RESTRICT_SELECT_OFF'
                row.operator("gaffer.select_light", icon=select_icon, text="", emboss=False).light=light.name
                if scene.GafferSoloActive == '':
                    solobtn = row.operator("gaffer.solo", icon='ZOOM_SELECTED', text='', emboss=False)
                    solobtn.light=light.name
                    solobtn.showhide=True
                elif scene.GafferSoloActive == light.name:
                    solobtn = row.operator("gaffer.solo", icon='ZOOM_PREVIOUS', text='', emboss=False)
                    solobtn.light=light.name
                    solobtn.showhide=False
                    
                
                #color TODO make colour prop smaller in row (using split)
                row.separator()
                try:
                #if True:
                    if light.type == 'LAMP':
                        if not light.data.use_nodes:
                            1/0
                        node_color=light.data.node_tree.nodes['Emission']
                    else:
                        node_color=material.node_tree.nodes['Emission']
                    socket_color=0
                except:
                    row.label("TODO, handle custom color node")
                else:
                    if not node_color.inputs[socket_color].is_linked:
                        subcol = row.column(align=True)
                        subrow = subcol.row(align=True)
                        subrow.scale_x = 0.3
                        subrow.prop(node_color.inputs[socket_color], 'default_value', text='')
                    else:
                        from_node=node_color.inputs[socket_color].links[0].from_node
                        if from_node.type=='RGB':
                            subcol = row.column(align=True)
                            subrow = subcol.row(align=True)
                            subrow.scale_x = 0.3
                            subrow.prop(from_node.outputs[0], 'default_value', text='')
                        elif from_node.type=='TEX_IMAGE' or from_node.type=='TEX_ENVIRONMENT':
                            row.prop(from_node, 'image', text='')
                        elif from_node.type=='BLACKBODY':                            
                            row.prop(from_node.inputs[0], 'default_value', text='Temperature')
                            if scene.GafferColTempExpand and scene.GafferLightUIIndex==i:
                                row.operator('gaffer.col_temp_hide', text='', icon='MOVE_UP_VEC')
                                col=col.column(align=True)
                                col.separator()
                                col.label("Color Temperature Presets:")
                                ordered_col_temps = OrderedDict(sorted(col_temp.items()))
                                for temp in ordered_col_temps:
                                    op=col.operator('gaffer.col_temp_preset', text=temp[3:], icon='COLOR')  # temp[3:] removes number used for ordering
                                    op.temperature=temp
                                    op.light = light.name
                                    if material:
                                        op.material = material.name
                                    if node_color:
                                        op.node = node_color.name
                                col.separator()
                            else:
                                row.operator('gaffer.col_temp_show', text='', icon='COLOR').l_index=i
                        elif from_node.type=='WAVELENGTH':
                            row.prop(from_node.inputs[0], 'default_value', text='Wavelength')

                
                #size and strength
                row=col.row(align=True)
                if light.type == 'LAMP':
                    row.label(text='', icon='LAMP_%s' % light.data.type)
                    row.separator()
                    if light.data.type=='AREA':
                        row.prop(light.data, 'size')
                    else:
                        row.prop(light.data, 'shadow_soft_size', text='Size')
                    if light.data.use_nodes: #check if uses nodes
                        if not node_strength.inputs[socket_strength].is_linked:
                            row.prop(node_strength.inputs[socket_strength], 'default_value', text='Strength')
                        else:
                            row.label("  Node Invalid")  # rather check for next available slot?
                    else:
                        row.operator('gaffer.lamp_use_nodes', icon='NODETREE', text='').light=light.name
                else:  # MESH light
                    row.label(text='', icon='MESH_PLANE')
                    row.separator()
                    row.prop(node_strength.inputs[socket_strength], 'default_value', text='Strength')


                # More Options
                if "_Light:_("+light.name+")_" in scene.GafferMoreExpand or scene.GafferMoreExpandAll:
                    col=box.column(align=True)
                    row = col.row(align=True)
                    if light.type == 'LAMP':
                        row.prop(light.data.cycles, "use_multiple_importance_sampling", text='MIS', toggle=True)
                        row.prop(light.data.cycles, "cast_shadow", text='Shadows', toggle=True)
                        row.separator()
                        row.prop(light.cycles_visibility, "diffuse", text='Diffuse')
                        row.prop(light.cycles_visibility, "glossy", text='Specular')
                        if light.data.type == 'SPOT':
                            row = col.row(align=True)
                            row.prop(light.data, "spot_size", text='Spot Size')
                            row.prop(light.data, "spot_blend", text='Blend')
                        if scene.cycles.progressive == 'BRANCHED_PATH':
                            col.prop(light.data.cycles, "samples")
                    else:  # MESH light
                        row.prop(material.cycles, "sample_as_light", text='MIS', toggle=True)
                        row.separator()
                        row.prop(light.cycles_visibility, "camera", text='Camera')
                        row.prop(light.cycles_visibility, "diffuse", text='Diffuse')
                        row.prop(light.cycles_visibility, "glossy", text='Specular')
                i+=1

        # maincol.label("Node: "+node_strength.name)
        # maincol.label("Socket: "+str(socket_strength))

        if len(lights_to_show) == 0:
            row = maincol.row()
            row.alignment = 'CENTER'
            row.label("No lights to show :)")


def gaffer_node_menu_func(self, context):
    # TODO check if object is not light
    layout = self.layout
    layout.operator('gaffer.node_set_strength')


def register():
    bpy.types.Scene.GafferLights = bpy.props.StringProperty(
        name="Lights",
        default="",
        description="The objects to include in the isolation")
    bpy.types.Scene.GafferLightNodes = bpy.props.StringProperty(
        name="Lights",
        default="",
        description="The objects to include in the isolation")
    bpy.types.Scene.GafferColTempExpand = bpy.props.BoolProperty(
        name="Color Temperature Presets",
        default=False,
        description="Preset color temperatures based on real-world light sources")
    bpy.types.Scene.GafferMoreExpand = bpy.props.StringProperty(
        name="Show more options",
        default="",
        description="Show settings such as MIS, falloff, ray visibility...")
    bpy.types.Scene.GafferMoreExpandAll = bpy.props.BoolProperty(
        name="Show more options",
        default=False,
        description="Show settings such as MIS, falloff, ray visibility...")
    bpy.types.Scene.GafferLightUIIndex = bpy.props.IntProperty(
        name="light index",
        default=0,
        min=0,
        description="light index")
    bpy.types.Scene.GafferLightsHiddenRecord = bpy.props.StringProperty(
        name="hidden record",
        default="",
        description="hidden record")
    bpy.types.Scene.GafferSoloActive = bpy.props.StringProperty(
        name="soloactive",
        default='',
        description="soloactive")
    bpy.types.Scene.GafferVisibleLayersOnly = bpy.props.BoolProperty(
        name="Visible Layers Only",
        default=False,
        description="Only show lamps that are on visible layers")

    bpy.types.NODE_PT_active_node_generic.append(gaffer_node_menu_func)
        
    bpy.utils.register_module(__name__) 
       
def unregister():    
    del bpy.types.Scene.GafferLights
    del bpy.types.Scene.GafferLightNodes
    del bpy.types.Scene.GafferColTempExpand
    del bpy.types.Scene.GafferMoreExpand
    del bpy.types.Scene.GafferLightUIIndex
    del bpy.types.Scene.GafferLightsHiddenRecord
    del bpy.types.Scene.GafferSoloActive
    del bpy.types.Scene.GafferVisibleLayersOnly

    bpy.types.NODE_PT_active_node_generic.remove(gaffer_node_menu_func)
    
    bpy.utils.unregister_module(__name__)
        
if __name__ == "__main__":
	register() 