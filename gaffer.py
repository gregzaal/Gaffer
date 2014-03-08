bl_info = {
    "name": "Gaffer",
    "description": "Manage all your lights together quickly and efficiently from a single panel",
    "author": "Greg Zaal",
    "version": (0, 1),
    "blender": (2, 69, 1),
    "location": "3D View > Properties",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "3D View"}

import bpy

'''
TODO:
    work for BI
    node input for strength
    misc node input for col
    aim lamp at cursor
    settings for world light

    "More" button:
        Connect Wavelength/Blackbody to colour
        Falloff
        Samples (in branched path tracing)

    For mesh lamps:
        option to show materials instead of objects
'''


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
        temparr=[light, bpy.data.objects[light].hide, bpy.data.objects[light].hide_render]
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



'''
    OPERATORS
'''
class GafSetTemp(bpy.types.Operator):
    'Set the color temperature to a preset'
    bl_idname='gaffer.col_temp_preset'
    bl_label='Color Temperature Preset'
    temperature=bpy.props.StringProperty()
    light=bpy.props.StringProperty()
    
    def execute(self,context):
        col_temp={"flame": 1700,
                  "studio": 3200,
                  "sunset": 5000,
                  "daylight": 5500,
                  "overcast": 6500,
                  "lcd_low": 5500,
                  "lcd_high": 10500,
                  "sky": 12000}
        light=context.scene.objects[self.light]
        light.data.node_tree.nodes['Emission'].inputs[0].links[0].from_node.inputs[0].default_value=col_temp[self.temperature]
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

class GafSelectLight(bpy.types.Operator):
    'Select/Deselect this light'
    bl_idname='gaffer.select_light'
    bl_label='Select'
    light=bpy.props.StringProperty()
    
    def execute(self,context):
        obj=bpy.data.objects[self.light]
        if obj.select:
            obj.select=False
        else:
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
            print ("Enter")
            bpy.ops.gaffer.refresh_lights()
            scene.GafferSoloActive=light
            getHiddenStatus(scene, stringToList(scene.GafferLights, True))
            for l in statelist: # first check if lights still exist
                try:
                    obj = bpy.data.objects[l[0]]
                except:
                    getHiddenStatus(scene, stringToList(scene.GafferLights, True))
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
            print ("Restore")
            oldlight=scene.GafferSoloActive
            scene.GafferSoloActive=''
            for l in statelist:
                try:
                    obj = bpy.data.objects[l[0]]
                except:
                    bpy.ops.gaffer.refresh_lights()
                    getHiddenStatus(scene, stringToList(scene.GafferLights, True))
                    scene.GafferSoloActive=oldlight
                    bpy.ops.gaffer.solo()
                    return {'FINISHED'}
                obj.hide = castBool(l[1])
                obj.hide_render = castBool(l[2])
        
        return {'FINISHED'}

class GafReOrderUp(bpy.types.Operator):
    'Move this light up the list'
    bl_idname='gaffer.order_list_up'
    bl_label='Move Up'
    current_index=bpy.props.IntProperty()
    do_nothing=bpy.props.BoolProperty()
    
    def execute(self,context):
        if not self.do_nothing:
            lights=stringToList(context.scene.GafferLights, stripquotes=True)
            i=self.current_index
            lights.insert(i-1, lights.pop(i))
            context.scene.GafferLights=str(lights)
            context.scene.GafferLightUIIndex -= 1
        return {'FINISHED'}

class GafReOrderDown(bpy.types.Operator):
    'Move this light down the list'
    bl_idname='gaffer.order_list_down'
    bl_label='Move Down'
    current_index=bpy.props.IntProperty()
    do_nothing=bpy.props.BoolProperty()
    
    def execute(self,context):
        if not self.do_nothing:
            lights=stringToList(context.scene.GafferLights, stripquotes=True)
            i=self.current_index
            lights.insert(i+1, lights.pop(i))
            context.scene.GafferLights=str(lights)
            context.scene.GafferLightUIIndex += 1
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
        return {'FINISHED'}


class GafRefreshLightList(bpy.types.Operator):
    'Refresh the list of lights'
    bl_idname='gaffer.refresh_lights'
    bl_label='Refresh Light List'
    
    def execute(self,context):
        scene=context.scene
        m=[]
        for obj in scene.objects:
            light_mats = []
            if obj.type == 'LAMP':
                m.append(obj.name)
            elif obj.type == 'MESH' and len (obj.material_slots) > 0:
                slot_break = False
                for slot in obj.material_slots:
                    if slot_break:
                        break  # only use first emission material in slots
                    if slot.material:
                        # don't check nodes in material if obj uses a mat that was previously approved
                        if slot.material.name in light_mats:
                            m.append(obj.name)
                        elif slot.material.use_nodes:
                            for node in slot.material.node_tree.nodes:
                                if node.type == 'EMISSION':
                                    if node.outputs[0].is_linked:
                                        light_mats.append(slot.material.name)
                                        m.append(obj.name)
                                        slot_break = True
                                        break  # avoid adding same object for every emission shader
                
        # check if anything's changed
        mcheck=m
        ocheck=stringToList(scene.GafferLights, stripquotes=True)        
        mcheck.sort()
        ocheck.sort()
        if mcheck==ocheck:
            self.report({'INFO'}, "Nothing Changed")
        else:        
            scene.GafferLights=str(m)
            self.report({'INFO'}, "Light list refreshed")
            if scene.GafferSoloActive=='':
                getHiddenStatus(scene, stringToList(scene.GafferLights, True))
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
        lights=stringToList(lights_str)
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
                #solobtn.light=light.name
                solobtn.showhide=False
                row.label("       ")

        maincol=layout.column(align=True)

        lights_to_show = []
        for light in lights:
            try:
                if scene.GafferVisibleLayersOnly:
                    if isOnVisibleLayer(bpy.data.objects[light[1:-1]], scene):
                        lights_to_show.append(light)
                else:
                    l = bpy.data.objects[light[1:-1]]  # var isn't used, but this will cause error
                    lights_to_show.append(light)
            except:
                box=maincol.box()
                row=box.row(align=True)
                row.label("Light list out of date")
                row.operator('gaffer.refresh_lights', icon='FILE_REFRESH', text='')

        i=0
        for item in lights_to_show:
            light=scene.objects[item[1:-1]] #drop the apostrophies
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
            row.prop(light, 'hide', text='', emboss=False)
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
                
            
            #color
            row.separator()
            if light.type == 'LAMP':
                if light.data.use_nodes: #check if uses nodes
                    node=light.data.node_tree.nodes['Emission']  # TODO replace with stored node
                    socket=0
                    if not node.inputs[socket].is_linked:
                        row.prop(node.inputs[socket], 'default_value', text='')
                    else:
                        from_node=node.inputs[socket].links[0].from_node
                        if from_node.type=='RGB':
                            row.prop(from_node.outputs[0], 'default_value', text='')
                        elif from_node.type=='TEX_IMAGE' or from_node.type=='TEX_ENVIRONMENT':
                            row.prop(from_node, 'image', text='')
                        elif from_node.type=='BLACKBODY':                            
                            row.prop(from_node.inputs[0], 'default_value', text='Temperature')
                            if scene.GafferColTempExpand and scene.GafferLightUIIndex==i:
                                row.operator('gaffer.col_temp_hide', text='', icon='MOVE_UP_VEC')
                                col=col.column(align=True)
                                col.separator()
                                col.label("Color Temperature Presets:")
                                op=col.operator('gaffer.col_temp_preset', text='Flame (1700)', icon='COLOR')
                                op.temperature='flame'
                                op.light=light.name
                                op=col.operator('gaffer.col_temp_preset', text='Studio (3200)', icon='COLOR')
                                op.temperature='studio'
                                op.light=light.name
                                op=col.operator('gaffer.col_temp_preset', text='Sunset (5000)', icon='COLOR')
                                op.temperature='sunset'
                                op.light=light.name
                                op=col.operator('gaffer.col_temp_preset', text='Daylight (5500)', icon='COLOR')
                                op.temperature='daylight'
                                op.light=light.name
                                op=col.operator('gaffer.col_temp_preset', text='Overcast (6500)', icon='COLOR')
                                op.temperature='overcast'
                                op.light=light.name
                                op=col.operator('gaffer.col_temp_preset', text='LCD (5500)', icon='COLOR')
                                op.temperature='lcd_low'
                                op.light=light.name
                                op=col.operator('gaffer.col_temp_preset', text='LCD (10500)', icon='COLOR')
                                op.temperature='lcd_high'
                                op.light=light.name
                                op=col.operator('gaffer.col_temp_preset', text='Sky (12000)', icon='COLOR')
                                op.temperature='sky'
                                op.light=light.name
                                col.separator()
                            else:
                                row.operator('gaffer.col_temp_show', text='', icon='COLOR').l_index=i
                        elif from_node.type=='WAVELENGTH':
                            row.prop(from_node.inputs[0], 'default_value', text='Wavelength')
                else:
                    row.prop(light.data, 'color', text='')
            else:  # MESH light
                row.label("mwahaha")

            
            #size and strength
            row=col.row(align=True)
            if light.type == 'LAMP':
                if light.data.type == 'POINT':
                    row.label(text='', icon='LAMP_POINT')
                elif  light.data.type == 'SUN':
                    row.label(text='', icon='LAMP_SUN')
                elif  light.data.type == 'SPOT':
                    row.label(text='', icon='LAMP_SPOT')
                elif  light.data.type == 'HEMI':
                    row.label(text='', icon='LAMP_HEMI')
                elif  light.data.type == 'AREA':
                    row.label(text='', icon='LAMP_AREA')
                row.separator()
                if light.data.type=='AREA':
                    row.prop(light.data, 'size')
                else:
                    row.prop(light.data, 'shadow_soft_size', text='Size')
                if light.data.use_nodes: #check if uses nodes
                    row.prop(light.data.node_tree.nodes['Emission'].inputs[1], 'default_value', text='Strength')
                else:
                    row.operator('gaffer.lamp_use_nodes', icon='NODETREE', text='').light=light.name
            else:  # MESH light
                row.label(text='', icon='MESH_PLANE')


                
            # move light up/down
            if not scene.GafferVisibleLayersOnly:
                split=rowmain.split()
                col=split.column(align=True)
                if i!=0:
                    a=col.operator('gaffer.order_list_up', icon='TRIA_UP', text='')
                    a.current_index=i
                    a.do_nothing=False
                else:
                    col.operator('gaffer.order_list_up', icon='MOVE_UP_VEC', text='').do_nothing=True
                if i!=len(lights_to_show)-1:
                    a=col.operator('gaffer.order_list_down', icon='TRIA_DOWN', text='')
                    a.current_index=i
                    a.do_nothing=False
                else:
                    col.operator('gaffer.order_list_down', icon='MOVE_DOWN_VEC', text='').do_nothing=True


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
                    # MIS
                    row.label("lawl")
                row.separator()
                row.prop(light.cycles_visibility, "diffuse", text='Diffuse')
                row.prop(light.cycles_visibility, "glossy", text='Specular')
            i+=1

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
        description="Only show lamps that are on visible layers (disableds ability to re-order list)")
        
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
    
    bpy.utils.unregister_module(__name__)
        
if __name__ == "__main__":
	register() 