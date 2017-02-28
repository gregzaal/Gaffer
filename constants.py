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
import bgl, blf
from math import pi, cos, sin, log
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.app.handlers import persistent

supported_renderers = ['BLENDER_RENDER', 'CYCLES']

col_temp = {"01_Flame (1700)": 1700,
            "02_Tungsten (3200)": 3200,
            "03_Daylight (5500)": 5500,
            "04_Overcast (6500)": 6500,
            "05_Shade (8000)": 8000,
            "06_LCD (10500)": 10500,
            "07_Sky (12000)": 12000}
            
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

data_dir = os.path.join(os.path.abspath(os.path.join(bpy.utils.resource_path('USER'), '..')), 'data', 'gaffer')
log_file = os.path.join(data_dir, 'logs.txt')
thumbnail_dir = os.path.join(data_dir, 'thumbs')
if not os.path.exists(thumbnail_dir): os.makedirs(thumbnail_dir)
thumb_endings = ['preview', 'thumb', 'thumbnail']
hdr_file_types = ['.tif', '.tiff', '.hdr', '.exr']
allowed_file_types = hdr_file_types + ['.jpg', '.jpeg', '.png', '.tga']
jpg_dir = os.path.join(data_dir, 'hdri_jpgs')
if not os.path.exists(jpg_dir): os.makedirs(jpg_dir)
hdri_list_path = os.path.join(data_dir, 'gaffer_hdris.json')
tags_path = os.path.join(data_dir, 'tags.json')
settings_file = os.path.join(data_dir, 'settings.json')
preview_collections = {}
icon_dir = os.path.join(os.path.dirname(__file__), 'icons')
hdri_list = {}
hdri_haven_list = []
hdri_haven_list_path = os.path.join(data_dir, 'hdri_haven_hdris.json')
custom_icons = None
default_tags = ['outdoor',
                'indoor',
                '##split##',
                'rural',
                'urban',
                '##split##',
                'clear',
                'partly cloudy',
                'overcast',
                'sun',
                '##split##',
                'early morning',
                'midday',
                'late afternoon',
                'night',
                '##split##',
                'low contrast',
                'medium contrast',
                'high contrast',
                '##split##',
                'natural light',
                'artificial light',
                '##split##']
possible_tags = []
