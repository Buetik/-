#!/usr/bin/env python3
"""3D-визуализация кухни-гостиной и балкона по эскизу заказчика K2 (Blender / Cycles).

Эскиз: 01-input/refs/kitchen-balcony-sketch-K2.png (столовая на балконе — круглый стол Ø1000 и 4 кресла,
в кухне диван 3000 лицом к ТВ на стене W8, линейная кухня вдоль W3, раздвижная стеклянная дверь в проёме O4).
Стены и проёмы — 01-input/measurements.json, цвета — 02-concept/palette.json, отделка — решения D1–D32.

Нужен модуль bpy (Blender 5.x, Python 3.11) и shapely:
    python3.11 -m venv .venv && .venv/bin/pip install bpy shapely
    .venv/bin/python tools/viz_kitchen_balcony.py --views V1,V2 --res 1920x1080 --samples 256
    .venv/bin/python tools/viz_kitchen_balcony.py --views V6 --cut          # «кукольный домик» без потолка
Без --views сцена только собирается и сохраняется в 07-visualization/kitchen-balcony.blend.
"""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

import bpy  # noqa: I001 — bpy первым: он подключает bmesh и mathutils
import bmesh
from mathutils import Matrix, Vector, noise
from shapely.geometry import Polygon, MultiPolygon
from shapely.geometry.polygon import orient

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '07-visualization'
RND = random.Random(108)


def M(v):
    """мм → м"""
    return v / 1000.0


# ---------------------------------------------------------------- палитра и материалы
def _palette():
    p = json.load(open(ROOT / '02-concept/palette.json'))
    items = p if isinstance(p, list) else p.get('colors', p.get('palette', p))
    items = items if isinstance(items, list) else list(items.values())
    return {c['code']: c['hex'] for c in items if isinstance(c, dict) and 'code' in c}


PAL = _palette()


def lin(h, a=1.0):
    h = h.lstrip('#')
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (a,)


def _set(node, name, val):
    if name in node.inputs:
        node.inputs[name].default_value = val


MATS = {}


def _newmat(name):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except AttributeError:
        pass
    return m


def mat(name, color, rough=0.6, metal=0.0, sheen=0.0, coat=0.0, spec=0.5, bump=0.0):
    if name in MATS:
        return MATS[name]
    m = _newmat(name)
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    _set(b, 'Base Color', color if len(color) == 4 else lin(color))
    _set(b, 'Roughness', rough)
    _set(b, 'Metallic', metal)
    _set(b, 'Specular IOR Level', spec)
    if sheen:
        _set(b, 'Sheen Weight', sheen)
        _set(b, 'Sheen Roughness', 0.35)
    if coat:
        _set(b, 'Coat Weight', coat)
        _set(b, 'Coat Roughness', 0.08)
    if bump:
        nz = nt.nodes.new('ShaderNodeTexNoise')
        nz.inputs['Scale'].default_value = 400.0
        nz.inputs['Detail'].default_value = 2.0
        bp = nt.nodes.new('ShaderNodeBump')
        bp.inputs['Strength'].default_value = bump
        bp.inputs['Distance'].default_value = 0.0005
        nt.links.new(nz.outputs['Fac'], bp.inputs['Height'])
        nt.links.new(bp.outputs['Normal'], b.inputs['Normal'])
    m.diffuse_color = color if len(color) == 4 else lin(color)
    MATS[name] = m
    return m


def mat_oak(name, base='#B8986F', rough=0.42, coords='uv', grain_axis='x', light='#C9AC83', dark='#98754F'):
    """Дуб. coords='uv' — по UV доски (u вдоль волокон, атрибут 'prand' — разброс тона);
    coords='object' — по координатам объекта, волокна вдоль grain_axis."""
    if name in MATS:
        return MATS[name]
    m = _newmat(name)
    nt, N, L = m.node_tree, m.node_tree.nodes, m.node_tree.links
    b = N['Principled BSDF']
    mp = N.new('ShaderNodeMapping')
    if coords == 'uv':
        src = N.new('ShaderNodeUVMap').outputs['UV']
        mp.inputs['Scale'].default_value = (2.5, 70.0, 1.0)
    else:
        src = N.new('ShaderNodeTexCoord').outputs['Object']
        mp.inputs['Scale'].default_value = (2.5, 70.0, 70.0) if grain_axis == 'x' else (70.0, 70.0, 2.5)
    L.new(src, mp.inputs['Vector'])
    grain = N.new('ShaderNodeTexNoise')
    grain.inputs['Scale'].default_value = 1.2
    grain.inputs['Detail'].default_value = 9.0
    grain.inputs['Distortion'].default_value = 0.8
    L.new(mp.outputs['Vector'], grain.inputs['Vector'])
    ramp = N.new('ShaderNodeValToRGB')
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.38, lin(light)
    cr.elements[1].position, cr.elements[1].color = 0.68, lin(dark)
    L.new(grain.outputs['Fac'], ramp.inputs['Fac'])
    # разброс досок
    at = N.new('ShaderNodeAttribute')
    at.attribute_name = 'prand'
    at.attribute_type = 'GEOMETRY'
    mr = N.new('ShaderNodeMapRange')
    mr.inputs['To Min'].default_value = 0.86
    mr.inputs['To Max'].default_value = 1.10
    L.new(at.outputs['Fac'], mr.inputs['Value'])
    hsv = N.new('ShaderNodeHueSaturation')
    L.new(ramp.outputs['Color'], hsv.inputs['Color'])
    L.new(mr.outputs['Result'], hsv.inputs['Value'])
    mix = N.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.inputs['Factor'].default_value = 0.35
    L.new(hsv.outputs['Color'], mix.inputs['A'])
    mix.inputs['B'].default_value = lin(base)
    L.new(mix.outputs['Result'], b.inputs['Base Color'])
    # поры / шероховатость
    pores = N.new('ShaderNodeTexNoise')
    pores.inputs['Scale'].default_value = 9.0
    pores.inputs['Detail'].default_value = 4.0
    L.new(mp.outputs['Vector'], pores.inputs['Vector'])
    rr = N.new('ShaderNodeMapRange')
    rr.inputs['To Min'].default_value = rough - 0.08
    rr.inputs['To Max'].default_value = rough + 0.12
    L.new(pores.outputs['Fac'], rr.inputs['Value'])
    L.new(rr.outputs['Result'], b.inputs['Roughness'])
    bp = N.new('ShaderNodeBump')
    bp.inputs['Strength'].default_value = 0.08
    bp.inputs['Distance'].default_value = 0.0003
    L.new(grain.outputs['Fac'], bp.inputs['Height'])
    L.new(bp.outputs['Normal'], b.inputs['Normal'])
    m.diffuse_color = lin(base)
    MATS[name] = m
    return m


def mat_marble(name, base, vein, scale=1.6, rough=0.3, veins=0.05):
    """Светлый камень (кварц / керамогранит «мрамор»): волны с искажением → тонкие прожилки."""
    if name in MATS:
        return MATS[name]
    m = _newmat(name)
    N, L = m.node_tree.nodes, m.node_tree.links
    b = N['Principled BSDF']
    tc = N.new('ShaderNodeTexCoord')
    wv = N.new('ShaderNodeTexWave')
    wv.inputs['Scale'].default_value = scale
    wv.inputs['Distortion'].default_value = 14.0
    wv.inputs['Detail'].default_value = 8.0
    wv.inputs['Detail Scale'].default_value = 1.5
    L.new(tc.outputs['Object'], wv.inputs['Vector'])
    ramp = N.new('ShaderNodeValToRGB')
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.0, lin(vein)
    cr.elements[1].position, cr.elements[1].color = veins, lin(base)
    L.new(wv.outputs['Fac'], ramp.inputs['Fac'])
    cloud = N.new('ShaderNodeTexNoise')
    cloud.inputs['Scale'].default_value = 3.0
    L.new(tc.outputs['Object'], cloud.inputs['Vector'])
    mix = N.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'OVERLAY'
    mix.inputs['Factor'].default_value = 0.12
    L.new(ramp.outputs['Color'], mix.inputs['A'])
    L.new(cloud.outputs['Color'], mix.inputs['B'])
    L.new(mix.outputs['Result'], b.inputs['Base Color'])
    _set(b, 'Roughness', rough)
    m.diffuse_color = lin(base)
    MATS[name] = m
    return m


def mat_glass(name, tint=(0.96, 0.98, 0.97, 1)):
    """Тонкое стекло: прозрачность + френелевское отражение (солнце проходит без каустики)."""
    if name in MATS:
        return MATS[name]
    m = _newmat(name)
    N, L = m.node_tree.nodes, m.node_tree.links
    N.remove(N['Principled BSDF'])
    out = N['Material Output']
    tr = N.new('ShaderNodeBsdfTransparent')
    tr.inputs['Color'].default_value = tint
    gl = N.new('ShaderNodeBsdfGlossy')
    gl.inputs['Roughness'].default_value = 0.0
    lw = N.new('ShaderNodeLayerWeight')
    lw.inputs['Blend'].default_value = 0.12
    mx = N.new('ShaderNodeMixShader')
    L.new(lw.outputs['Fresnel'], mx.inputs['Fac'])
    L.new(tr.outputs['BSDF'], mx.inputs[1])
    L.new(gl.outputs['BSDF'], mx.inputs[2])
    L.new(mx.outputs['Shader'], out.inputs['Surface'])
    m.diffuse_color = (0.8, 0.9, 0.95, 0.2)
    MATS[name] = m
    return m


def mat_emit(name, color, strength):
    if name in MATS:
        return MATS[name]
    m = _newmat(name)
    N, L = m.node_tree.nodes, m.node_tree.links
    N.remove(N['Principled BSDF'])
    e = N.new('ShaderNodeEmission')
    e.inputs['Color'].default_value = color
    e.inputs['Strength'].default_value = strength
    L.new(e.outputs['Emission'], N['Material Output'].inputs['Surface'])
    MATS[name] = m
    return m


def mat_sheer(name, color, transp=0.45):
    """Тюль/лён: просвечивающая ткань."""
    if name in MATS:
        return MATS[name]
    m = _newmat(name)
    N, L = m.node_tree.nodes, m.node_tree.links
    N.remove(N['Principled BSDF'])
    df = N.new('ShaderNodeBsdfDiffuse')
    df.inputs['Color'].default_value = lin(color)
    tl = N.new('ShaderNodeBsdfTranslucent')
    tl.inputs['Color'].default_value = lin(color)
    tp = N.new('ShaderNodeBsdfTransparent')
    m1 = N.new('ShaderNodeMixShader')
    m1.inputs['Fac'].default_value = 0.5
    L.new(df.outputs['BSDF'], m1.inputs[1])
    L.new(tl.outputs['BSDF'], m1.inputs[2])
    m2 = N.new('ShaderNodeMixShader')
    m2.inputs['Fac'].default_value = transp
    L.new(m1.outputs['Shader'], m2.inputs[1])
    L.new(tp.outputs['BSDF'], m2.inputs[2])
    L.new(m2.outputs['Shader'], N['Material Output'].inputs['Surface'])
    m.diffuse_color = lin(color)
    MATS[name] = m
    return m


def mat_leaves(name, color):
    if name in MATS:
        return MATS[name]
    m = _newmat(name)
    N, L = m.node_tree.nodes, m.node_tree.links
    b = N['Principled BSDF']
    tc = N.new('ShaderNodeTexCoord')
    nz = N.new('ShaderNodeTexNoise')
    nz.inputs['Scale'].default_value = 6.0
    nz.inputs['Detail'].default_value = 6.0
    L.new(tc.outputs['Object'], nz.inputs['Vector'])
    ramp = N.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = lin('#2F4A22')
    ramp.color_ramp.elements[1].color = lin(color)
    L.new(nz.outputs['Fac'], ramp.inputs['Fac'])
    L.new(ramp.outputs['Color'], b.inputs['Base Color'])
    vor = N.new('ShaderNodeTexVoronoi')
    vor.inputs['Scale'].default_value = 22.0
    L.new(tc.outputs['Object'], vor.inputs['Vector'])
    bp = N.new('ShaderNodeBump')
    bp.inputs['Strength'].default_value = 0.9
    bp.inputs['Distance'].default_value = 0.05
    L.new(vor.outputs['Distance'], bp.inputs['Height'])
    L.new(bp.outputs['Normal'], b.inputs['Normal'])
    _set(b, 'Roughness', 0.75)
    _set(b, 'Subsurface Weight', 0.2)
    m.diffuse_color = lin(color)
    MATS[name] = m
    return m


def materials():
    C = PAL
    return {
        'wall': mat('wall_C2', C['C2'], 0.85, bump=0.15),
        'ceil': mat('ceil_C1', C['C1'], 0.9),
        'white': mat('trim_C1', C['C1'], 0.55),
        'sage': mat('sage_C4', C['C4'], 0.5, spec=0.4),
        'upper': mat('upper_C2', C['C2'], 0.5, spec=0.4),
        'greige': mat('greige_C3', C['C3'], 0.6),
        'olive': mat('olive_C6', C['C6'], 0.95, spec=0.2, bump=0.1),
        'brass': mat('brass_C8', '#C9AE72', 0.32, metal=1.0),
        'bronze': mat('bronze_C10', '#4D433C', 0.38, metal=0.7),
        'steel': mat('steel', '#C8C8C6', 0.25, metal=1.0),
        'black_glass': mat('black_glass', '#0B0B0C', 0.05, spec=0.6, coat=0.6),
        'tv': mat('tv_screen', '#050506', 0.03, spec=0.7, coat=1.0),
        'tv_body': mat('tv_body', '#1B1B1C', 0.4),
        'quartz': mat_marble('quartz_M13', '#EDE8E0', '#CFC6BA', scale=0.7, rough=0.28, veins=0.02),
        'marble': mat_marble('marble_C9', C['C9'], '#C7BDB1', scale=0.9, rough=0.32, veins=0.025),
        'oak_floor': mat_oak('oak_floor_C7', C['C7']),
        'oak': mat_oak('oak_furniture_h', '#B48F62', rough=0.5, coords='object', grain_axis='x',
                       light='#C2A27B', dark='#A9865E'),
        'oak_v': mat_oak('oak_furniture_v', '#B48F62', rough=0.5, coords='object', grain_axis='z',
                         light='#C2A27B', dark='#A9865E'),
        'sofa': mat('sofa_sand', '#D2C7B4', 0.9, sheen=0.6, bump=0.25),
        'chair': mat('chair_caramel', '#A68B6E', 0.85, sheen=0.6, bump=0.25),
        'pillow_a': mat('pillow_olive', '#6B6A55', 0.85, sheen=0.5, bump=0.2),
        'pillow_b': mat('pillow_caramel', C['C11'], 0.85, sheen=0.5, bump=0.2),
        'wood_dark': mat('wood_dark', '#3B2D22', 0.5),
        'pvc': mat('pvc_white', '#F1F0EB', 0.35),
        'glass': mat_glass('glass'),
        'sheer': mat_sheer('sheer_C2', C['C2']),
        'shade': mat_sheer('shade_linen', '#EFE6D6', transp=0.05),
        'opal': mat_emit('opal_globe', (1.0, 0.86, 0.70, 1), 9.0),
        'led': mat_emit('led_3000', (1.0, 0.80, 0.60, 1), 10.0),
        'trim_ring': mat('downlight_trim', '#F2F1EC', 0.4),
        'sub': mat('subfloor', '#1A1612', 0.9),
        'ground': mat('grass', '#5E7344', 0.9),
        'paving': mat('paving', '#9C978E', 0.85),
        'facade': mat('facade_brick', '#B9A48A', 0.9),
        'trunk': mat('trunk', '#4A3B2E', 0.9),
        'leaves': mat_leaves('leaves', '#7FA052'),
        'slab': mat('concrete', '#A8A39A', 0.9),
        'rubber': mat('black_matte', '#121212', 0.7),
        'cut_wall': mat('cut_wall', '#E9E6DF', 0.9),
        'plan_ground': mat('plan_ground', '#E4E1DA', 0.95),
    }


# ---------------------------------------------------------------- геометрия
COL = {}


def collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    COL['cur'] = c
    return c


def link(name, me, mats, smooth=False):
    o = bpy.data.objects.new(name, me)
    COL['cur'].objects.link(o)
    for m in mats:
        me.materials.append(m)
    if smooth:
        me.shade_smooth()
    return o


def box(name, x0, x1, y0, y1, z0, z1, m, bevel=0.0, seg=2, subsurf=0):
    """Параллелепипед (мм); начало координат объекта — в его центре (для поворотов)."""
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    z0, z1 = min(z0, z1), max(z0, z1)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    sx, sy, sz = M(x1 - x0), M(y1 - y0), M(z1 - z0)
    for v in bm.verts:
        v.co = Vector((v.co.x * sx, v.co.y * sy, v.co.z * sz))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = link(name, me, [m], smooth=subsurf > 0)
    o.location = (M(x0 + x1) / 2, M(y0 + y1) / 2, M(z0 + z1) / 2)
    if bevel > 0:
        md = o.modifiers.new('bevel', 'BEVEL')
        md.width = min(M(bevel), 0.49 * min(sx, sy, sz))
        md.segments = seg
        md.limit_method = 'NONE'
    if subsurf:
        md = o.modifiers.new('sub', 'SUBSURF')
        md.levels = md.render_levels = subsurf
    return o


def prism(name, coords, z0, z1, m):
    """Призма из многоугольника (мм)."""
    poly = orient(Polygon(coords), 1.0)
    bm = bmesh.new()
    bot = [bm.verts.new((M(x), M(y), M(z0))) for x, y in list(poly.exterior.coords)[:-1]]
    top = [bm.verts.new((M(x), M(y), M(z1))) for x, y in list(poly.exterior.coords)[:-1]]
    bm.faces.new(top)
    bm.faces.new(list(reversed(bot)))
    n = len(bot)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([bot[i], bot[j], top[j], top[i]])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return link(name, me, [m])


def cylinder(name, x, y, z0, z1, r, m, seg=32, r_top=None, axis='Z'):
    bm = bmesh.new()
    rt = r if r_top is None else r_top
    ring0, ring1 = [], []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        ring0.append(bm.verts.new((M(r) * math.cos(a), M(r) * math.sin(a), 0)))
        ring1.append(bm.verts.new((M(rt) * math.cos(a), M(rt) * math.sin(a), M(z1 - z0))))
    for i in range(seg):
        j = (i + 1) % seg
        bm.faces.new([ring0[i], ring0[j], ring1[j], ring1[i]])
    bm.faces.new(list(reversed(ring0)))
    bm.faces.new(ring1)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = link(name, me, [m], smooth=True)
    if axis == 'Z':
        o.location = (M(x), M(y), M(z0))
    return o


def lathe(name, profile, x, y, m, seg=48, caps=True):
    """Тело вращения: profile — [(r, z)] мм снизу вверх."""
    bm = bmesh.new()
    rings = []
    for r, z in profile:
        rings.append([bm.verts.new((M(r) * math.cos(2 * math.pi * i / seg),
                                    M(r) * math.sin(2 * math.pi * i / seg), M(z))) for i in range(seg)])
    for k in range(len(rings) - 1):
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new([rings[k][i], rings[k][j], rings[k + 1][j], rings[k + 1][i]])
    if caps and profile[0][0] > 0:
        bm.faces.new(list(reversed(rings[0])))
    if caps and profile[-1][0] > 0:
        bm.faces.new(rings[-1])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = link(name, me, [m], smooth=True)
    o.location = (M(x), M(y), 0)
    return o


def sweep(name, pts, pn, prof, m, closed=False, closed_prof=False):
    """Протяжка профиля [(s, t) мм] вдоль плоской ломаной pts (мм, 3D) с нормалью плоскости pn.
    s — смещение влево от направления обхода в плоскости (для CCW-контура — внутрь), t — вдоль pn."""
    P = [Vector((M(a), M(b), M(c))) for a, b, c in pts]
    pn = Vector(pn).normalized()
    n = len(P)
    ne = n if closed else n - 1
    en = [pn.cross((P[(i + 1) % n] - P[i]).normalized()).normalized() for i in range(ne)]
    mv = []
    for i in range(n):
        if closed:
            n0, n1 = en[i - 1], en[i % ne]
        else:
            n0 = en[i - 1] if i > 0 else en[0]
            n1 = en[i] if i < ne else en[-1]
        d = 1.0 + n0.dot(n1)
        mv.append((n0 + n1) / d if d > 1e-6 else n0)
    bm = bmesh.new()
    rings = [[bm.verts.new(P[i] + mv[i] * M(s) + pn * M(t)) for s, t in prof] for i in range(n)]
    k = len(prof)
    for i in range(ne):
        r0, r1 = rings[i], rings[(i + 1) % n]
        for j in range(k if closed_prof else k - 1):
            jj = (j + 1) % k
            bm.faces.new([r0[j], r0[jj], r1[jj], r1[j]])
    if not closed and k > 2:
        try:
            bm.faces.new(rings[0])
            bm.faces.new(list(reversed(rings[-1])))
        except ValueError:
            pass
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return link(name, me, [m])


# профили (s — от стены в комнату, t — по высоте / от стены)
CORNICE = [(0, -80), (8, -80), (10, -66), (22, -58), (30, -44), (46, -32), (60, -14), (70, -8), (80, 0)]
SKIRT = [(0, 0), (14, 0), (14, 100), (11, 106), (8, 112), (5, 118), (0, 120)]
SKIRT_B = [(0, 0), (12, 0), (12, 76), (8, 80), (0, 80)]
MOLD = [(-15, 0), (-15, 6), (-11, 11), (-5, 16), (5, 18), (12, 12), (15, 6), (15, 0)]
CASING = [(-35, 0), (-35, 12), (-30, 18), (10, 22), (28, 16), (35, 10), (35, 0)]


def frame_on_wall(name, plane, a0, a1, z0, z1, m, prof=MOLD):
    """Рамка-молдинг в плоскости стены. plane = ('y', 3580, -1): стена y=3580, выступ в −Y."""
    ax, c, sg = plane
    if ax == 'y':
        pts = [(a0, c, z0), (a1, c, z0), (a1, c, z1), (a0, c, z1)]
        pn = (0, sg, 0)
    else:
        pts = [(c, a0, z0), (c, a1, z0), (c, a1, z1), (c, a0, z1)]
        pn = (sg, 0, 0)
    return sweep(name, pts, pn, [(s, t) for s, t in prof], m, closed=True)


# ---------------------------------------------------------------- фасады и ручки
def knob(name, x, y, z, nsign, m):
    """Ручка-кнопка; ось — по Y (nsign — наружу)."""
    o = lathe(name, [(0, 0), (7, 0), (6, 10), (5, 14), (13, 20), (15, 26), (13, 31), (6, 34), (0, 34.5)], 0, 0, m, seg=24)
    o.rotation_euler = (-math.pi / 2 * nsign, 0, 0)
    o.location = (M(x), M(y), M(z))
    return o


def bar_pull(name, x0, x1, y, z, nsign, m):
    """Горизонтальная скоба Ø12 на двух стойках; y — лицевая плоскость фасада."""
    r, stand = 6, 32
    bar = cylinder(name, 0, 0, 0, x1 - x0, r, m, seg=16)
    bar.rotation_euler = (0, math.pi / 2, 0)
    bar.location = (M(x0), M(y + nsign * stand), M(z))
    for i, xx in enumerate((x0 + 15, x1 - 15)):
        p = cylinder(f'{name}_p{i}', 0, 0, 0, stand, 5, m, seg=12)
        p.rotation_euler = (-math.pi / 2 * nsign, 0, 0)
        p.location = (M(xx), M(y), M(z))
    return bar


def vbar_pull(name, x, y, z0, z1, nsign, m):
    """Вертикальная скоба (холодильник)."""
    r, stand = 7, 34
    bar = cylinder(name, x, y + nsign * stand, z0, z1, r, m, seg=16)
    for i, zz in enumerate((z0 + 18, z1 - 18)):
        p = cylinder(f'{name}_p{i}', 0, 0, 0, stand, 5, m, seg=12)
        p.rotation_euler = (-math.pi / 2 * nsign, 0, 0)
        p.location = (M(x), M(y), M(zz))
    return bar


def front(name, x0, x1, z0, z1, yb, nsign, m, style='shaker', handle=None, hm=None, gap=1.5):
    """Фасад в плоскости XZ. yb — плоскость тыльной стороны, nsign — куда смотрит лицо (+1 → +Y)."""
    t = 19
    xa, xb, za, zb = x0 + gap, x1 - gap, z0 + gap, z1 - gap
    y0, y1 = yb, yb + nsign * t
    box(name, xa, xb, y0, y1, za, zb, m, bevel=1.2, seg=1)
    yf = y1
    if style == 'shaker' and (xb - xa) > 160 and (zb - za) > 160:
        w = 62 if (xb - xa) > 260 else 48
        d = 6
        y2 = yf + nsign * d
        box(name + '_l', xa, xa + w, yf, y2, za, zb, m, bevel=1.5, seg=2)
        box(name + '_r', xb - w, xb, yf, y2, za, zb, m, bevel=1.5, seg=2)
        box(name + '_b', xa + w, xb - w, yf, y2, za, za + w, m, bevel=1.5, seg=2)
        box(name + '_t', xa + w, xb - w, yf, y2, zb - w, zb, m, bevel=1.5, seg=2)
        yf = y2
    if handle and hm is not None:
        kind, *pos = handle
        if kind == 'knob':
            hx, hz = pos
            knob(name + '_h', hx, yf, hz, nsign, hm)
        elif kind == 'bar':
            hx0, hx1, hz = pos
            bar_pull(name + '_h', hx0, hx1, yf, hz, nsign, hm)
        elif kind == 'vbar':
            hx, hz0, hz1 = pos
            vbar_pull(name + '_h', hx, yf, hz0, hz1, nsign, hm)
    return yf


# ---------------------------------------------------------------- пол «ёлочкой»
def herringbone(name, region, m, L=600, W=100, axis_y=1520, phase_x=0, gap_mat=None):
    s2 = math.sqrt(2)
    y_off = axis_y - (W - L) / (2 * s2)

    def tw(a, b):
        return ((a + b) / s2 + phase_x, (b - a) / s2 + y_off)

    minx, miny, maxx, maxy = region.bounds
    ss, tt = [], []
    for x, y in ((minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)):
        xp, yp = x - phase_x, y - y_off
        a, b = (xp - yp) / s2, (xp + yp) / s2
        ss.append((a + b) / (2 * W))
        tt.append((a - b) / (2 * L))
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new('UVMap')
    pr = bm.faces.layers.float.new('prand')
    count = 0
    for k in range(int(min(ss)) - 3, int(max(ss)) + 4):
        for mm in range(int(min(tt)) - 3, int(max(tt)) + 4):
            a0, b0 = k * W + mm * L, k * W - mm * L
            for rect, along in (((a0, a0 + L, b0, b0 + W), 'a'), ((a0 + L, a0 + L + W, b0 + W - L, b0 + W), 'b')):
                ra0, ra1, rb0, rb1 = rect
                pl = Polygon([tw(ra0, rb0), tw(ra1, rb0), tw(ra1, rb1), tw(ra0, rb1)])
                if not pl.intersects(region):
                    continue
                piece = pl.intersection(region)
                parts = list(piece.geoms) if isinstance(piece, MultiPolygon) else [piece]
                d = Vector((1, -1)).normalized() if along == 'a' else Vector((1, 1)).normalized()
                pp = Vector((-d.y, d.x))
                ru, rv, rnd = RND.uniform(0, 6), RND.uniform(0, 6), RND.random()
                for part in parts:
                    if not isinstance(part, Polygon) or part.area < 50:
                        continue
                    _plank(bm, part, d, pp, ru, rv, rnd, uvl, pr)
                    count += 1
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = link(name, me, [m])
    return o, count


def _plank(bm, poly, d, pp, ru, rv, rnd, uvl, pr):
    poly = orient(poly.simplify(0.05), 1.0)
    inner = poly.buffer(-1.0, join_style=2)
    outer = poly.buffer(-0.3, join_style=2)
    if inner.is_empty or not isinstance(inner, Polygon) or not isinstance(outer, Polygon):
        inner = outer = poly
    ci = list(orient(inner, 1.0).exterior.coords)[:-1]
    co = list(orient(outer, 1.0).exterior.coords)[:-1]
    chamfer = len(ci) == len(co) and len(ci) >= 3
    if chamfer:
        j0 = min(range(len(ci)), key=lambda j: (ci[j][0] - co[0][0]) ** 2 + (ci[j][1] - co[0][1]) ** 2)
        ci = ci[j0:] + ci[:j0]
    else:
        ci = co

    def uv(x, y):
        v = Vector((x, y))
        return (v.dot(d) / 1000 + ru, v.dot(pp) / 1000 + rv)

    top = [bm.verts.new((M(x), M(y), 0.0)) for x, y in ci]
    f = bm.faces.new(top)
    f[pr] = rnd
    for lp in f.loops:
        lp[uvl].uv = uv(lp.vert.co.x * 1000, lp.vert.co.y * 1000)
    if chamfer:
        mid = [bm.verts.new((M(x), M(y), -0.0006)) for x, y in co]
        n = len(top)
        for i in range(n):
            j = (i + 1) % n
            ff = bm.faces.new([top[i], mid[i], mid[j], top[j]])
            ff[pr] = rnd
            for lp in ff.loops:
                lp[uvl].uv = uv(lp.vert.co.x * 1000, lp.vert.co.y * 1000)
        ring = mid
    else:
        ring = top
    bot = [bm.verts.new((v.co.x, v.co.y, -0.003)) for v in ring]
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        ff = bm.faces.new([ring[i], bot[i], bot[j], ring[j]])
        ff[pr] = rnd


# ---------------------------------------------------------------- сцена
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    MATS.clear()
    COL.clear()


def build(cut=False):
    """cut=True — «кукольный домик»: без потолков и навесных, стены срезаны на +1600."""
    reset()
    X = materials()
    H_K, H_B, SLAB = 2650, 2500, 2750
    CUT = 1100

    def hz(z):
        return min(z, CUT) if cut else z

    # ---------------- полы
    collection('floor')
    kitchen = Polygon([(0, 0), (4090, 0), (4090, 2011), (7541, 2011), (7541, 3121), (4820, 3121),
                       (4820, 5970), (3525, 5970), (3525, 3580), (0, 3580)])
    OT = LAY['open_top']  # верх проёма O4 по Y (K3 — проём расширен до торца балкона)
    portal = Polygon([(-420, 590), (0, 590), (0, OT), (-420, OT)])
    balcony = Polygon([(-2431, 45), (-420, 45), (-420, 3068), (-2431, 3068)])
    if cut:  # в «кукольном домике» — только кухня-гостиная и балкон
        kitchen = Polygon([(0, 0), (4090, 0), (4090, 3580), (0, 3580)])
    region = kitchen.union(portal).union(balcony)
    _, n = herringbone('floor_herringbone', region, X['oak_floor'])
    print(f'  ёлочка: {n} досок')
    prism('subfloor', list(region.buffer(5).exterior.coords)[:-1], -10, -3, X['sub'])
    box('profile_brass', -213, -207, 590, OT, -1, 1.5, X['brass'])

    # ---------------- стены (мм)
    collection('walls')
    walls = [
        ('W2_a', -420, 0, 0, 590, 0, SLAB), ('W2_lintel', -420, 0, 590, OT, 2450, SLAB),
        ('W2_b', -420, 0, OT, 3720, 0, SLAB), ('W3', -420, 6000, -160, 0, 0, SLAB),
        ('W10', 4090, 4170, 0, 2011, 0, SLAB), ('W11_a', 4170, 4240, 1931, 2011, 0, SLAB),
        ('W11_top', 4240, 4960, 1931, 2011, 2180, SLAB), ('W11_b', 4960, 7541, 1931, 2011, 0, SLAB),
        ('W8', 0, 3530, 3580, 3720, 0, SLAB), ('W7_top', 3380, 3525, 3720, 4621, 2180, SLAB),
        ('W7', 3380, 3525, 4621, 6050, 0, SLAB), ('end_a', 3525, 3720, 5970, 6050, 0, SLAB),
        ('end_top', 3720, 4600, 5970, 6050, 2180, SLAB), ('end_b', 4600, 4900, 5970, 6050, 0, SLAB),
        ('W12_a', 4820, 4900, 3721, 4150, 0, SLAB), ('W12_top', 4820, 4900, 4150, 4930, 2180, SLAB),
        ('W12_b', 4820, 4900, 4930, 6050, 0, SLAB), ('W14', 7541, 7700, 2011, 3721, 0, SLAB),
    ]
    if cut:
        walls = [w for w in walls if w[0] in ('W2_a', 'W2_b', 'W3', 'W10', 'W8')]
        walls = [w for w in walls if w[0] not in ('W10', 'W8')] + [('W10', 4090, 4170, 0, 3580, 0, SLAB),
                                                                  ('W8', 0, 4170, 3580, 3720, 0, SLAB)]
    for nm, x0, x1, y0, y1, z0, z1 in walls:
        if z0 < hz(z1):
            box(nm, x0, x1, y0, y1, z0, hz(z1), X['cut_wall'] if cut else X['wall'])
    # откосы портала O4 — C1 (D21), тонким слоем поверх кладки
    box('O4_reveal_l', -420, 0, 590, 592, 0, hz(2448), X['white'])
    box('O4_reveal_r', -420, 0, OT - 2, OT, 0, hz(2448), X['white'])
    if not cut:
        box('O4_reveal_top', -420, 0, 590, OT, 2446, 2448, X['white'])
    # балконная сторона W2 — тёмная олива (C6)
    box('W2_balc_1', -426, -420, 45, 590, 0, hz(H_B), X['olive'])
    if OT < 3068:
        box('W2_balc_2', -426, -420, OT, 3068, 0, hz(H_B), X['olive'])
    if not cut:
        box('W2_balc_3', -426, -420, 590, OT, 2450, H_B, X['olive'])
    if not cut:  # прихожая и коридор — фон для видов в сторону входа
        hall_and_doors(X)

    # ---------------- потолки, карнизы, плинтусы
    if not cut:
        collection('ceiling')
        prism('ceiling_kitchen_hall', list(kitchen.exterior.coords)[:-1], H_K, H_K + 30, X['ceil'])
        box('CB1_upper', 650, 4090 if CORNER else 3450, 0, 350, 2400, H_K, X['upper'])
        box('CB1_tall_l', 0, 650, 0, 620, 2400, H_K, X['upper'])
        if CORNER:
            box('CB1_w10', 3740, 4090, 350, 1240, 2400, H_K, X['upper'])
            box('CB1_fridge', 3470, 4090, 1240, 1880, 2400, H_K, X['upper'])
            ring = [(0, 620), (650, 620), (650, 350), (3740, 350), (3740, 1240), (3470, 1240), (3470, 1880),
                    (4090, 1880), (4090, 2011),
                    (7541, 2011), (7541, 3121), (4820, 3121), (4820, 5970), (3525, 5970), (3525, 3580), (0, 3580)]
        else:
          box('CB1_tall_r', 3450, 4090, 0, 620, 2400, H_K, X['upper'])
          ring = [(0, 620), (650, 620), (650, 350), (3450, 350), (3450, 620), (4090, 620), (4090, 2011),
                (7541, 2011), (7541, 3121), (4820, 3121), (4820, 5970), (3525, 5970), (3525, 3580), (0, 3580)]
        rp = orient(Polygon(ring), 1.0)
        sweep('cornice_kitchen', [(x, y, H_K) for x, y in list(rp.exterior.coords)[:-1]], (0, 0, 1), CORNICE,
              X['ceil'], closed=True)
        # балкон: потолок +2500 (C6), ниша штор CN-3 150 до +2600 по контуру остекления
        box('ceiling_balcony', -2281, -420, 195, 2918, H_B, H_B + 40, X['olive'])
        box('niche_balcony', -2531, -420, -55, 3168, 2600, 2640, X['olive'])
        box('niche_side_B1', -2300, -2281, 195, 2918, H_B, 2600, X['olive'])
        box('niche_side_B2', -2281, -420, 2918, 2937, H_B, 2600, X['olive'])
        box('niche_side_B3', -2281, -420, 176, 195, H_B, 2600, X['olive'])
        if LAYOUT == 'K4':
            for i, (x, y) in enumerate(((-1500, 900), (-1500, 2200))):
                cylinder(f'balc_downlight_{i}', x, y, H_B - 4, H_B, 40, X['trim_ring'], seg=24)
                cylinder(f'balc_downlight_lens_{i}', x, y, H_B - 6, H_B - 4, 28, X['led'], seg=24)
        for i, (x, y) in enumerate(spots_for_layout()):
            cylinder(f'downlight_{i}', x, y, H_K - 4, H_K, 48, X['trim_ring'], seg=24)
            cylinder(f'downlight_lens_{i}', x, y, H_K - 6, H_K - 4, 34, X['led'], seg=24)
    collection('trim')
    skirts = [  # обход против часовой стрелки — комната слева
        [(3525, 3721, 0), (3525, 3580, 0), (0, 3580, 0), (0, OT, 0)],
        [(3720, 5970, 0), (3525, 5970, 0), (3525, 4621, 0)],
        [(4820, 4930, 0), (4820, 5970, 0), (4600, 5970, 0)],
        [(4820, 3721, 0), (4820, 4150, 0)],
        [(4090, 1880 if CORNER else 640, 0), (4090, 2011, 0), (4240, 2011, 0)],
        [(4960, 2011, 0), (7541, 2011, 0)],
    ]
    if cut:
        skirts = [[(4090, 640, 0), (4090, 3580, 0), (0, 3580, 0), (0, OT, 0)]]
    for i, path in enumerate(skirts):
        sweep(f'skirting_{i}', path, (0, 0, 1), SKIRT, X['wall'])
    bpath = [(-420, OT, 0), (-420, 3068, 0), (-2431, 3068, 0), (-2431, 45, 0), (-420, 45, 0), (-420, 590, 0)]
    if OT >= 3068:
        bpath = bpath[1:]
    sweep('skirting_balcony', bpath, (0, 0, 1), SKIRT_B, X['olive'])

    # ---------------- кухня вдоль W3 (эскиз K2)
    collection('kitchen')
    S, U, BR = X['sage'], X['upper'], X['brass']
    FY = 600  # тыльная плоскость фасадов
    box('filler_wall', 0, 50, 0, FY + 19, 120, 2400, S)
    # пенал K-01: ящики, духовой шкаф, компактная СВЧ, антресоль
    box('T1_body', 50, 650, 0, FY, 120, 2400, S)
    box('T1_plinth', 52, 648, 0, FY - 50, 0, 120, X['rubber'])
    front('T1_dr1', 50, 650, 120, 520, FY, +1, S, handle=('bar', 270, 430, 470), hm=BR)
    front('T1_dr2', 50, 650, 520, 860, FY, +1, S, handle=('bar', 270, 430, 810), hm=BR)
    box('T1_oven', 53, 647, FY, FY + 22, 862, 1457, X['black_glass'], bevel=2)
    box('T1_oven_strip', 60, 640, FY + 22, FY + 24, 1385, 1450, X['steel'])
    bar_pull('T1_oven_h', 120, 580, FY + 22, 1360, +1, X['steel'])
    box('T1_micro', 53, 647, FY, FY + 22, 1460, 1915, X['black_glass'], bevel=2)
    box('T1_micro_strip', 60, 640, FY + 22, FY + 24, 1850, 1910, X['steel'])
    front('T1_top', 50, 650, 1918, 2400, FY, +1, S, handle=('knob', 560, 1980), hm=BR)
    # базы
    bases = [(650, 850, 'pull'), (850, 1450, 'drawers'), (1450, 2050, 'drawers'), (2050, 2650, 'dw'),
             (2650, 3250, 'sink'), (3250, 3450, 'pull')]
    for i, (x0, x1, kind) in enumerate(bases):
        box(f'B{i}_body', x0, x1, 40, FY, 120, 880, S)
        box(f'B{i}_plinth', x0, x1, FY - 60, FY - 40, 0, 120, X['rubber'])
        cx = (x0 + x1) / 2
        if kind in ('pull', 'dw'):
            w = 60 if kind == 'pull' else 90
            front(f'B{i}_f', x0, x1, 120, 880, FY, +1, S, handle=('bar', cx - w, cx + w, 825), hm=BR)
        elif kind == 'drawers':
            for j, (z0, z1) in enumerate([(120, 340), (340, 610), (610, 880)]):
                front(f'B{i}_d{j}', x0, x1, z0, z1, FY, +1, S, handle=('bar', cx - 90, cx + 90, z1 - 55), hm=BR)
        elif kind == 'sink':
            front(f'B{i}_l', x0, cx, 120, 880, FY, +1, S, handle=('knob', cx - 45, 800), hm=BR)
            front(f'B{i}_r', cx, x1, 120, 880, FY, +1, S, handle=('knob', cx + 45, 800), hm=BR)
    if CORNER:
        kitchen_w10_leg(X, cut)
    # пенал холодильника K-07 + доборная 40
    if not CORNER:
      box('T2_body', 3450, 4050, 0, FY, 120, 2400, S)
      box('T2_plinth', 3452, 4048, 0, FY - 50, 0, 120, X['rubber'])
      front('T2_freezer', 3450, 4050, 120, 800, FY, +1, S, handle=('bar', 3660, 3840, 745), hm=BR)
      front('T2_fridge', 3450, 4050, 800, 1880, FY, +1, S, handle=('vbar', 3510, 950, 1450), hm=BR)
      front('T2_top', 3450, 4050, 1880, 2400, FY, +1, S, handle=('knob', 3510, 1950), hm=BR)
      box('T2_panel', 4050, 4090, 0, FY + 25, 0, 2400, S)
    # столешница — кварц, вырез под мойку
    WT0, WT1 = 880, 900
    for nm, x0, x1, y0, y1 in (('top_a', 650, 2700, 0, 640), ('top_b', 3200, 4090 if CORNER else 3450, 0, 640),
                               ('top_front', 2700, 3200, 520, 640), ('top_back', 2700, 3200, 0, 120)):
        box(nm, x0, x1, y0, y1, WT0, WT1, X['quartz'], bevel=1.5, seg=2)
    sk = X['steel']
    box('sink_bottom', 2700, 3200, 120, 520, 690, 700, sk)
    box('sink_wall_f', 2700, 3200, 510, 520, 700, WT0, sk)
    box('sink_wall_b', 2700, 3200, 120, 130, 700, WT0, sk)
    box('sink_wall_l', 2700, 2710, 120, 520, 700, WT0, sk)
    box('sink_wall_r', 3190, 3200, 120, 520, 700, WT0, sk)
    cylinder('sink_drain', 2950, 320, 700, 702, 40, sk)
    # смеситель — латунь, гусак
    cylinder('tap_base', 2950, 70, WT1, WT1 + 30, 28, BR)
    cylinder('tap_body', 2950, 70, WT1 + 30, WT1 + 300, 14, BR)
    sweep('tap_spout', [(2950, 70, WT1 + 290), (2950, 95, WT1 + 345), (2950, 160, WT1 + 378), (2950, 230, WT1 + 365),
                        (2950, 275, WT1 + 315), (2950, 290, WT1 + 255)], (1, 0, 0),
          [(-10, -10), (10, -10), (10, 10), (-10, 10)], BR, closed_prof=True)
    box('tap_lever', 2985, 3060, 62, 78, WT1 + 214, WT1 + 228, BR, bevel=4)
    # индукционная панель
    box('hob', 855, 1445, 60, 580, WT1, WT1 + 5, X['black_glass'], bevel=2)
    for i, (hx, hy, r) in enumerate([(1000, 200, 105), (1300, 200, 90), (1000, 440, 90), (1300, 440, 110)]):
        cylinder(f'hob_zone_{i}', hx, hy, WT1 + 5, WT1 + 5.3, r, X['tv_body'], seg=40)
    # фартук: керамогранит «мрамор» C9, высота 650, швы по модулям
    xs = [650, 850, 1450, 2050, 2650, 3250, 3450] + ([4090] if CORNER else [])
    for i in range(len(xs) - 1):
        box(f'backsplash_{i}', xs[i] + 1, xs[i + 1] - 1, 0, 10, WT1 + 1, 1549, X['marble'])
    # навесные C2 «шейкер» (в «кукольном домике» не показываем)
    if not cut:
        UZ0, UZ1, UD = 1550, 2400, 330
        uppers = [(650, 850), (850, 1450), (1450, 2050), (2050, 2650), (2650, 3250), (3250, 3450)] + \
            ([(3450, 4090)] if CORNER else [])
        for i, (x0, x1) in enumerate(uppers):
            box(f'U{i}_body', x0, x1, 0, UD, UZ0, UZ1, U)
            cx = (x0 + x1) / 2
            if i == 1:
                front('U_hood_top', x0, x1, UZ0 + 300, UZ1, UD, +1, U, handle=('knob', cx, UZ0 + 360), hm=BR)
                box('hood_visor', x0 + 5, x1 - 5, UD - 10, UD + 22, UZ0 - 5, UZ0 + 298, X['steel'], bevel=2)
            elif (x1 - x0) >= 600:
                front(f'U{i}_l', x0, cx, UZ0, UZ1, UD, +1, U, handle=('knob', cx - 45, UZ0 + 60), hm=BR)
                front(f'U{i}_r', cx, x1, UZ0, UZ1, UD, +1, U, handle=('knob', cx + 45, UZ0 + 60), hm=BR)
            else:
                hx = x0 + 45 if i == 0 else x1 - 45
                front(f'U{i}', x0, x1, UZ0, UZ1, UD, +1, U, handle=('knob', hx, UZ0 + 60), hm=BR)
        box('led_strip', 660, 4080 if CORNER else 3440, 40, 60, UZ0 - 4, UZ0 - 2, X['led'])

    # ---------------- ТВ-зона на W8 (y=3580): подвесная консоль, ТВ, молдинги, бра
    collection('tv_wall')
    if LAY.get('tv', True):
        tv_zone(X, S, BR)
    if LAYOUT == 'K4':
        projector_cinema(X, cut)
    if not cut:
        for i, (a0, a1) in enumerate(LAY['frames']):
            frame_on_wall(f'mould_W8_{i}', ('y', 3580, -1), a0, a1, *LAY.get('frame_z', (760, 2380)), X['wall'])
        if OT < 2600:
            frame_on_wall('mould_W2', ('x', 0, +1), 2700, 3330, 760, 2380, X['wall'])
        for i, sx in enumerate(LAY['sconces']):
            pl = cylinder(f'sconce_plate_{i}', 0, 0, 0, 20, 45, BR)
            pl.rotation_euler = (math.pi / 2, 0, 0)
            pl.location = (M(sx), M(3580), M(1600))
            box(f'sconce_arm_{i}', sx - 6, sx + 6, 3460, 3560, 1594, 1606, BR)
            cylinder(f'sconce_cup_{i}', sx, 3450, 1560, 1600, 12, BR)
            sh = lathe(f'sconce_shade_{i}', [(85, 0), (70, 160)], sx, 3450, X['shade'], seg=40, caps=False)
            sh.location.z = M(1580)
            sh.visible_shadow = False

    if LAYOUT == 'K2':
        sofa_k2(X)
        glass_door_k2(X)
    elif LAYOUT == 'K3':
        sofa_k3(X)
    else:
        sofa_k4(X)

    # ---------------- балкон: парапеты, остекление, шторы
    collection('balcony')
    O = X['olive']
    box('par_B1', -2531, -2431, -55, 3168, 0, 1000, O)
    box('par_B2', -2431, -420, 3068, 3168, 0, 1000, O)
    box('par_B3', -2431, -420, -55, 45, 0, 1000, O)
    box('sill_B1', -2531, -2411, -55, 3168, 1000, 1022, X['white'], bevel=2)
    box('sill_B2', -2411, -420, 3048, 3168, 1000, 1022, X['white'], bevel=2)
    box('sill_B3', -2411, -420, -55, 65, 1000, 1022, X['white'], bevel=2)
    if not cut:
        box('head_B1', -2531, -2431, -55, 3168, 2450, 2640, O)
        box('head_B2', -2431, -420, 3068, 3168, 2450, 2640, O)
        box('head_B3', -2431, -420, -55, 45, 2450, 2640, O)
        glazing('B1', 'x', -2531, -2461, [-55, 751, 1556, 2362, 3168], +1, X)
        glazing('B2', 'y', 3098, 3168, [-2531, -1835, -1128, -420], -1, X)
        glazing('B3', 'y', -55, 15, [-2531, -1835, -1128, -420], +1, X)
        if LAYOUT == 'K2':
            curtain('curtain_B1_a', 'x', -2370, 120, 560, X)
            curtain('curtain_B1_b', 'x', -2370, 2560, 3010, X)
            curtain('curtain_B3', 'y', 110, -2380, -1990, X)
            curtain('curtain_B2', 'y', 3005, -2380, -1990, X)

    # ---------------- столовая: K2 — на балконе, K3 — в кухне
    collection('dining')
    TX, TY = LAY['table']
    if LAYOUT == 'K4':
        dining_long(X, cut)
    else:
        dining(X, TX, TY, LAY['chairs'], cut, LAY['pendant_z0'])

    # ---------------- снаружи: перекрытие балкона, фасад, земля, деревья
    collection('exterior')
    box('balcony_slab', -2631, -420, -231, 3268, -260, -120, X['slab'])
    if cut:
        box('ground', -60000, 60000, -60000, 60000, -1150, -1100, X['plan_ground'])
    else:
        box('ground', -60000, 60000, -60000, 60000, -1150, -1100, X['ground'])
        box('paving', -5200, -420, -30000, 30000, -1100, -1095, X['paving'])
        box('balcony_slab_up', -2631, -420, -231, 3268, 2750, 2950, X['slab'])
        box('facade_n', -460, -420, 3268, 30000, -1100, 14000, X['facade'])
        box('facade_s', -460, -420, -30000, -231, -1100, 14000, X['facade'])
        box('facade_up', -460, -420, -231, 3268, 2950, 14000, X['facade'])
        box('facade_down', -460, -420, -231, 3268, -1100, -260, X['facade'])
    trees = [(-9500, -2500, 1.0), (-12500, 3200, 1.2), (-8800, 7600, 0.9), (-16000, -6500, 1.3), (-17500, 1500, 1.1),
             (-6500, 12500, 0.8), (-7200, -9800, 1.0), (-21000, 9000, 1.4), (-11000, 14000, 1.2)]
    for i, (tx, ty, s_) in enumerate(trees if not cut else []):
        tree(f'tree_{i}', tx, ty, s_, X)

    # ---------------- свет
    collection('lights')
    warm = (1.0, 0.84, 0.68)
    if not cut:
        for i, (x, y) in enumerate(spots_for_layout()):
            spot(f'spot_{i}', x, y, H_K - 8, 22.0, warm, 75)

        for i, sx in enumerate(LAY['sconces']):
            point(f'sconce_l{i}', sx, 3450, 1640, 7.0, warm, 25)
        if LAYOUT == 'K4':
            for i, px in enumerate(K4_PENDANTS):
                point(f'pendant_light_{i}', px, 2580, 1720, 28.0, warm, 70)
            for i, (bx_, by_) in enumerate(((-1500, 900), (-1500, 2200))):
                spot(f'balcony_spot_{i}', bx_, by_, H_B - 8, 14.0, warm, 80)
        else:
            point('pendant_light', TX, TY, 1650, 45.0, warm, 90)
        area('led_under', 2050, 50, 1540, 2780, 20, 14.0, warm)
    sun_and_sky(cut)

    # ---------------- камеры: (позиция, цель, фокус мм)
    for nm, (pos, tgt, lens) in LAY['cams'].items():
        camera('CAM_' + nm, pos, tgt, lens, level=(nm != 'V6'))
    render_settings()


def sofa_k2(X):
    """K2: диван 3000 в кухне (x 205..3195, y 1607..2611), сиденьем к ТВ."""
    collection('sofa')
    F = X['sofa']
    SX0, SX1, SY0, SY1 = 205, 3195, 1607, 2611
    box('sofa_base', SX0 + 10, SX1 - 10, SY0 + 10, SY1 - 10, 110, 400, F, bevel=25, seg=3)
    for i, lx in enumerate((SX0 + 60, SX1 - 60, (SX0 + SX1) / 2)):
        for j, ly in enumerate((SY0 + 60, SY1 - 60)):
            box(f'sofa_leg_{i}{j}', lx - 22, lx + 22, ly - 22, ly + 22, 0, 110, X['wood_dark'], bevel=4)
    box('sofa_arm_l', SX0, SX0 + 280, SY0, SY1, 110, 640, F, bevel=60, seg=4)
    box('sofa_arm_r', SX1 - 280, SX1, SY0, SY1, 110, 640, F, bevel=60, seg=4)
    box('sofa_back', SX0 + 200, SX1 - 200, SY0, SY0 + 230, 300, 780, F, bevel=50, seg=4)
    cw = (SX1 - SX0 - 560) / 3
    for i in range(3):
        x0 = SX0 + 280 + i * cw
        box(f'sofa_seat_{i}', x0 + 4, x0 + cw - 4, SY0 + 230, SY1 - 25, 400, 590, F, bevel=45, seg=4, subsurf=1)
        bc = box(f'sofa_backcush_{i}', x0 + 6, x0 + cw - 6, SY0 + 200, SY0 + 420, 570, 960, F, bevel=60, seg=4,
                 subsurf=1)
        bc.rotation_euler = (math.radians(9), 0, 0)
    for i, (px, mt, rz) in enumerate([(SX0 + 440, 'pillow_a', 10), (SX0 + 780, 'pillow_b', -5),
                                      (SX1 - 440, 'pillow_a', -10)]):
        p = box(f'pillow_{i}', -220, 220, -75, 75, -220, 220, X[mt], bevel=70, seg=4, subsurf=2)
        p.rotation_euler = (math.radians(16), 0, math.radians(rz))
        p.location = (M(px), M(SY0 + 500), M(800))


def glass_door_k2(X):
    """K2: раздвижная стеклянная дверь в портале O4, 3 полотна собраны у простенка."""
    BR = X['brass']
    collection('glass_door')
    BZ = X['bronze']
    box('door_track', 0, 120, 560, 2540, 2452, 2490, BZ)
    for i, (x0, y0, y1) in enumerate([(4, 1828, 2508), (40, 1787, 2421), (76, 1751, 2369)]):
        t = 30
        fw = 24
        box(f'leaf{i}_l', x0, x0 + t, y0, y0 + fw, 10, 2440, BZ)
        box(f'leaf{i}_r', x0, x0 + t, y1 - fw, y1, 10, 2440, BZ)
        box(f'leaf{i}_b', x0 + 1, x0 + t - 1, y0 + fw, y1 - fw, 10, 60, BZ)
        box(f'leaf{i}_t', x0 + 1, x0 + t - 1, y0 + fw, y1 - fw, 2390, 2440, BZ)
        box(f'leaf{i}_glass', x0 + 12, x0 + 18, y0 + fw, y1 - fw, 60, 2390, X['glass'])
    box('leaf_handle', 106, 128, 1801, 1813, 950, 1350, BR)


def dining(X, TX, TY, chairs, cut, ceil):
    """Круглый стол Ø1000 на тумбе, 4 кресла, подвес-шар над столом."""
    BR = X['brass']
    lathe('table_top', [(0, 728), (497, 728), (500, 733), (500, 755), (496, 760), (0, 760)], TX, TY, X['oak'], seg=96)
    lathe('table_pedestal', [(250, 0), (250, 18), (225, 30), (150, 45), (95, 70), (78, 120), (70, 300), (64, 520),
                             (72, 600), (86, 640), (120, 690), (160, 728)], TX, TY, X['oak_v'], seg=64)
    for i in range(16):
        a = 2 * math.pi * i / 16
        fl = box(f'table_flute_{i}', -5, 5, -4, 4, 150, 560, X['oak_v'], bevel=3)
        fl.rotation_euler = (0, 0, a)
        fl.location = (M(TX) + 0.069 * math.cos(a), M(TY) + 0.069 * math.sin(a), fl.location.z)
    for i, (cx, cy, rot) in enumerate(chairs):
        tub_chair(f'chair_{i}', cx, cy, rot, X['chair'], X['oak_v'])
    if not cut:
        cylinder('pendant_canopy', TX, TY, ceil - 20, ceil, 60, BR)
        cylinder('pendant_rod', TX, TY, 1830, ceil - 20, 4, BR)
        lathe('pendant_cap', [(0, 1790), (50, 1795), (60, 1815), (30, 1830), (0, 1832)], TX, TY, BR)
        prof = [(160 * math.cos(math.radians(a)), 1650 + 160 * math.sin(math.radians(a))) for a in range(-90, 76, 5)]
        prof[0] = (0.0, 1490.0)
        prof += [(48, 1805), (0, 1806)]
        g = lathe('pendant_globe', prof, TX, TY, X['opal'], seg=64)
        g.visible_shadow = False



def sofa_k3(X):
    """K3: угловой диван на балконе — длинная часть вдоль B1, короткая вдоль B2 через проём в кухню (оттоманка)."""
    collection('sofa')
    F, W = X['sofa'], X['wood_dark']
    XL0, XL1 = -2390, -1398        # длинная часть: глубина
    YL0, YL1 = 78, 3055            # длина вдоль B1
    YT0 = 2063                     # короткая часть: y 2063..3055
    XT1 = 587                      # конец оттоманки в кухне
    box('sofa_base_l', XL0 + 10, XL1 - 10, YL0 + 10, YL1 - 10, 110, 400, F, bevel=25, seg=3)
    box('sofa_base_t', XL1 - 10, XT1 - 10, YT0 + 10, YL1 - 10, 110, 400, F, bevel=25, seg=3)
    for i, (lx, ly) in enumerate([(XL0 + 60, YL0 + 60), (XL1 - 60, YL0 + 60), (XL0 + 60, YL1 - 60),
                                  (XT1 - 60, YT0 + 60), (XT1 - 60, YL1 - 60), (XL1 - 60, YT0 + 60)]):
        box(f'sofa_leg_{i}', lx - 22, lx + 22, ly - 22, ly + 22, 0, 110, W, bevel=4)
    box('sofa_back_l', XL0, XL0 + 230, YL0, YL1, 300, 780, F, bevel=50, seg=4)
    box('sofa_back_t', XL0 + 230, -406, YL1 - 230, YL1, 300, 780, F, bevel=50, seg=4)
    box('sofa_arm', XL0, XL1, YL0, YL0 + 280, 110, 640, F, bevel=60, seg=4)
    # сиденья
    seats = [(XL0 + 230, XL1, YL0 + 280, 1180), (XL0 + 230, XL1, 1180, 2063), (XL0 + 230, XL1, 2063, YL1 - 230),
             (XL1, -406, YT0, YL1 - 230), (-406, XT1, YT0, YL1)]
    for i, (x0, x1, y0, y1) in enumerate(seats):
        box(f'sofa_seat_{i}', x0 + 4, x1 - 4, y0 + 4, y1 - 4, 400, 590, F, bevel=45, seg=4, subsurf=1)
    for i, (y0, y1) in enumerate([(YL0 + 280, 1180), (1180, 2063), (2063, YL1 - 230)]):
        bc = box(f'sofa_back_cush_l{i}', XL0 + 200, XL0 + 420, y0 + 6, y1 - 6, 570, 960, F, bevel=60, seg=4, subsurf=1)
        bc.rotation_euler = (0, math.radians(-9), 0)
    for i, (x0, x1) in enumerate([(XL0 + 420, XL1), (XL1, -406)]):
        bc = box(f'sofa_back_cush_t{i}', x0 + 6, x1 - 6, YL1 - 420, YL1 - 200, 570, 960, F, bevel=60, seg=4, subsurf=1)
        bc.rotation_euler = (math.radians(-9), 0, 0)
    for i, (px, py, mt, rx, ry, rz) in enumerate([(XL0 + 470, 600, 'pillow_a', 0, -16, 90),
                                                  (XL0 + 480, 2600, 'pillow_b', 0, -16, 80),
                                                  (-1700, YL1 - 470, 'pillow_a', 16, 0, 5)]):
        p = box(f'pillow_{i}', -220, 220, -75, 75, -220, 220, X[mt], bevel=70, seg=4, subsurf=2)
        p.rotation_euler = (math.radians(rx), math.radians(ry), math.radians(rz))
        p.location = (M(px), M(py), M(800))


def tv_zone(X, S, BR):
    """Подвесная консоль вдоль W8 и ТВ на стене."""
    CY0, CY1 = LAY['console_y0'], 3580
    box('console_body', 30, 3500, CY0 + 19, CY1, 250, 650, S, bevel=2)
    for i, (x0, x1) in enumerate([(30, 396), (396, 762), (762, 1446), (1446, 2131), (2131, 2815), (2815, 3500)]):
        hx = x1 - 45 if i % 2 == 0 else x0 + 45
        front(f'console_f{i}', x0, x1, 252, 648, CY0 + 19, -1, S, handle=('knob', hx, 450), hm=BR)
    tvw, tvh, tvc, TVX = LAY['tv_w'], LAY['tv_w'] * 9 / 16, 1150, LAY['tv_x']
    box('tv_body', TVX - tvw / 2, TVX + tvw / 2, 3530, 3555, tvc - tvh / 2, tvc + tvh / 2, X['tv_body'], bevel=3)
    box('tv_screen', TVX - tvw / 2 + 6, TVX + tvw / 2 - 6, 3528, 3530, tvc - tvh / 2 + 6, tvc + tvh / 2 - 6,
        X['tv'])



K4_PENDANTS = (1300, 1900, 2500)
TABLE_STATE = 'compact'
CORNER = False   # угловая кухня (K4, D39): вторая ветка вдоль W10
TV_STATE = 'kitchen'
# ТВ-подъёмник K4 (D38): короб под потолком кухни у портала O4, ТВ 65″ опускается в проём экраном к балкону
LIFT = (0, 1150, 700, 2400)           # короб: x0, x1, y0, y1
LIFT_Z0 = 2490                        # низ короба (потолок кухни +2650)
LIFT_SPOTS = ((950, 1000), (950, 2100))
TV65 = (1440, 830)                    # ширина, высота корпуса 65″
TV_C = (1540, 1415)                   # центр по Y (ось П-дивана) и по высоте в опущенном положении
TV_X = 240                            # лицевая плоскость экрана в опущенном положении (смотрит в −X, на балкон)


def mat_projection():
    """Картинка проектора на матовом экране: «закат над морем», без бликов."""
    if 'projection' in MATS:
        return MATS['projection']
    m = _newmat('projection')
    N, L = m.node_tree.nodes, m.node_tree.links
    N.remove(N['Principled BSDF'])
    tc = N.new('ShaderNodeTexCoord')
    sep = N.new('ShaderNodeSeparateXYZ')
    L.new(tc.outputs['Generated'], sep.inputs['Vector'])
    ramp = N.new('ShaderNodeValToRGB')
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.0, lin('#2E5466')
    cr.elements[1].position, cr.elements[1].color = 1.0, lin('#6F93B8')
    for pos, col in ((0.34, '#4C7C86'), (0.40, '#E2A267'), (0.48, '#F2C28C'), (0.70, '#C7A7A0')):
        e = cr.elements.new(pos)
        e.color = lin(col)
    L.new(sep.outputs['Z'], ramp.inputs['Fac'])
    em = N.new('ShaderNodeEmission')
    em.inputs['Strength'].default_value = 1.6
    L.new(ramp.outputs['Color'], em.inputs['Color'])
    L.new(em.outputs['Emission'], N['Material Output'].inputs['Surface'])
    MATS['projection'] = m
    return m


def mat_screen_on():
    """Включённый экран: мягкий «закатный» кадр (вертикальный градиент), светится."""
    if 'screen_on' in MATS:
        return MATS['screen_on']
    m = _newmat('screen_on')
    N, L = m.node_tree.nodes, m.node_tree.links
    N.remove(N['Principled BSDF'])
    tc = N.new('ShaderNodeTexCoord')
    sep = N.new('ShaderNodeSeparateXYZ')
    L.new(tc.outputs['Generated'], sep.inputs['Vector'])
    ramp = N.new('ShaderNodeValToRGB')
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.0, lin('#1C232B')
    cr.elements[1].position, cr.elements[1].color = 1.0, lin('#4E6F93')
    e = cr.elements.new(0.42)
    e.color = lin('#D99A5E')
    e2 = cr.elements.new(0.36)
    e2.color = lin('#3A3530')
    L.new(sep.outputs['Z'], ramp.inputs['Fac'])
    em = N.new('ShaderNodeEmission')
    em.inputs['Strength'].default_value = 1.8
    L.new(ramp.outputs['Color'], em.inputs['Color'])
    gl = N.new('ShaderNodeBsdfGlossy')
    gl.inputs['Roughness'].default_value = 0.05
    mx = N.new('ShaderNodeMixShader')
    mx.inputs['Fac'].default_value = 0.05
    L.new(em.outputs['Emission'], mx.inputs[1])
    L.new(gl.outputs['BSDF'], mx.inputs[2])
    L.new(mx.outputs['Shader'], N['Material Output'].inputs['Surface'])
    MATS['screen_on'] = m
    return m


def spots_for_layout():
    if True:  # короб подъёмника заменён поворотным кронштейном (D40)
        return SPOTS
    x0, x1, y0, y1 = LIFT
    return [(x, y) for x, y in SPOTS if not (x0 - 60 <= x <= x1 + 60 and y0 - 60 <= y <= y1 + 60)]


def kitchen_w10_leg(X, cut):
    """Угловая кухня (D39): ветка вдоль W10 (x=4090). Строится в локальных осях (u — вдоль стены = Y мира,
    v — от стены = 4090 − X мира, фасады смотрят в +v) и поворачивается на 90°: база 600 с ящиками
    и пенал холодильника 600 + боковая панель 40 в торце у прихожей; навесные и фартук; угловая зона — «слепой» угол."""
    S, U, BR = X['sage'], X['upper'], X['brass']
    FY = 600
    before = set(bpy.data.objects.keys())
    collection('kitchen_w10')
    # угол: корпус за фасадами W3 и доборная планка
    box('corner_body', 3450, 4090, 40, FY, 120, 880, S)
    box('corner_filler', 3450, 3471, FY, FY + 19, 120, 880, S)
    box('corner_plinth', 3450, 3471, FY - 60, FY - 40, 0, 120, X['rubber'])
    # база с ящиками u 640..1240, доборная u 620..640
    box('W10_filler', 620, 640, 40, FY + 19, 120, 880, S)
    box('W10_B_body', 640, 1240, 40, FY, 120, 880, S)
    box('W10_B_plinth', 640, 1240, FY - 60, FY - 40, 0, 120, X['rubber'])
    for j, (z0, z1) in enumerate([(120, 340), (340, 610), (610, 880)]):
        front(f'W10_B_d{j}', 640, 1240, z0, z1, FY, +1, S, handle=('bar', 850, 1030, z1 - 55), hm=BR)
    # пенал холодильника u 1240..1840 + панель 40
    box('W10_T_body', 1240, 1840, 0, FY, 120, 2400, S)
    box('W10_T_plinth', 1242, 1838, 0, FY - 50, 0, 120, X['rubber'])
    front('W10_T_freezer', 1240, 1840, 120, 800, FY, +1, S, handle=('bar', 1450, 1630, 745), hm=BR)
    front('W10_T_fridge', 1240, 1840, 800, 1880, FY, +1, S, handle=('vbar', 1300, 950, 1450), hm=BR)
    front('W10_T_top', 1240, 1840, 1880, 2400, FY, +1, S, handle=('knob', 1300, 1950), hm=BR)
    box('W10_T_panel', 1840, 1880, 0, FY + 25, 0, 2400, S)
    # столешница и фартук
    box('W10_top', 640, 1240, 0, 640, 880, 900, X['quartz'], bevel=1.5, seg=2)
    for i, (a0, a1) in enumerate(((10, 640), (640, 1240))):
        box(f'W10_backsplash_{i}', a0 + 1, a1 - 1, 0, 10, 901, 1549, X['marble'])
    if not cut:
        UZ0, UZ1, UD = 1550, 2400, 330
        for i, (a0, a1) in enumerate(((330, 790), (790, 1240))):
            box(f'W10_U{i}_body', a0, a1, 0, UD, UZ0, UZ1, U)
            hx = a1 - 45 if i == 0 else a0 + 45
            front(f'W10_U{i}', a0, a1, UZ0, UZ1, UD, +1, U, handle=('knob', hx, UZ0 + 60), hm=BR)
        box('W10_led', 340, 1230, 40, 60, UZ0 - 4, UZ0 - 2, X['led'])
    # поворот ветки к стене W10: (u, v) → (4090 − v, u)
    T = Matrix.Translation((M(4090), 0, 0)) @ Matrix.Rotation(math.pi / 2, 4, 'Z')
    for name in set(bpy.data.objects.keys()) - before:
        if name in ('corner_body', 'corner_filler', 'corner_plinth'):
            continue
        o = bpy.data.objects[name]
        o.matrix_basis = T @ o.matrix_basis
    if not cut:
        area('led_under_w10', 4040, 785, 1540, 20, 890, 6.0, (1.0, 0.84, 0.68))
    collection('kitchen')


# ТВ на поворотном настенном кронштейне (D40): крепление на простенке W2 со стороны кухни у проёма O4
TV_MOUNT = (20, 2650, 1300)        # точка крепления (x, y, высота центра ТВ)
TV_POS = {  # центр плоскости экрана, нормаль экрана (куда смотрит), локоть кронштейна
    'kitchen': ((620, 3000), (0.7071, -0.7071), (53, 3208)),    # 1 — в углу кухни по диагонали, к столу и кухне
    'balcony': ((260, 1650), (-1.0, 0.0), (363, 2207)),         # 2 — в проёме перед П-диваном
}


def bar_between(name, p, q, z, w, h, m):
    """Брус между точками p и q (мм, план) на высоте z (центр), сечение w×h."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    L_ = math.hypot(dx, dy)
    o = box(name, -L_ / 2, L_ / 2, -w / 2, w / 2, z - h / 2, z + h / 2, m, bevel=4, seg=2)
    o.location = (M((p[0] + q[0]) / 2), M((p[1] + q[1]) / 2), M(z))
    o.rotation_euler = (0, 0, math.atan2(dy, dx))
    return o


def tv_swivel(X, cut):
    """ТВ 65″ на поворотном кронштейне с двумя звеньями: положение 1 — сложен в углу кухни (W2/W8),
    положение 2 — выдвинут в проём к дивану на балконе."""
    (cx, cy), (nx, ny), elbow = TV_POS['balcony' if TV_STATE in ('balcony', 'down') else 'kitchen']
    mx, my, zc = TV_MOUNT
    W_, H_ = TV65
    BZ = X['bronze']
    th = math.atan2(-nx, ny)  # поворот локальной +Y (лицо экрана) в направление нормали
    body = box('tv_body', -W_ / 2, W_ / 2, -45, -2, -H_ / 2, H_ / 2, X['tv_body'], bevel=3)
    on = TV_STATE in ('balcony', 'down')
    scr = box('tv_screen', -W_ / 2 + 6, W_ / 2 - 6, -2, 0, -H_ / 2 + 6, H_ / 2 - 6, mat_screen_on() if on else X['tv'])
    for o in (body, scr):
        loc = Vector(o.location)
        c, s_ = math.cos(th), math.sin(th)
        o.location = (M(cx) + loc.x * c - loc.y * s_, M(cy) + loc.x * s_ + loc.y * c, M(zc) + loc.z)
        o.rotation_euler = (0, 0, th)
    back = (cx - nx * 60, cy - ny * 60)
    box('tv_mount_plate', 0, 18, my - 70, my + 70, zc - 160, zc + 160, BZ, bevel=3)
    for k, dz in enumerate((-60, 60)):
        bar_between(f'tv_arm1_{k}', (mx, my), elbow, zc + dz, 40, 28, BZ)
        bar_between(f'tv_arm2_{k}', elbow, back, zc + dz, 40, 28, BZ)
    cylinder('tv_elbow', elbow[0], elbow[1], zc - 90, zc + 90, 26, BZ)
    tp = box('tv_back_plate', -200, 200, -15, 15, -150, 150, BZ, bevel=3)
    tp.location = (M(back[0]), M(back[1]), M(zc))
    tp.rotation_euler = (0, 0, th)


# Кинозона K4 (D41): проектор на потолке балкона над спинкой П-дивана, моторизованный экран 80″ 16:9
# в коробе-ламбрекене под потолком кухни над порталом O4; в режиме «Кино» экран опускается в проём к дивану
SCREEN_BOX = (0, 320, 520, 2520, 2530)   # x0, x1, y0, y1, низ короба
SCREEN = dict(x=155, yc=1520, w=1771, img=(1254, 2250), bottom=1190)
PROJ = (-2140, 1520, 2390)               # объектив: x, y, z (потолок балкона +2500)


def projector_cinema(X, cut):
    """Короб с экраном в кухне и проектор на потолке балкона. TV_STATE 'balcony' — экран опущен, идёт картинка."""
    x0, x1, y0, y1, zb = SCREEN_BOX
    on = TV_STATE == 'balcony'
    if not cut:
        box('screen_box', x0, x1, y0, y1, zb, 2650, X['ceil'])
        sweep('screen_box_mould', [(x1, y0, zb), (x1, y1, zb), (x0, y1, zb), (x0, y0, zb)], (0, 0, 1),
              [(0, 0), (0, -6), (6, -12), (14, -14), (20, -18), (24, -24)], X['ceil'])
        box('screen_slot', SCREEN['x'] - 12, SCREEN['x'] + 12, SCREEN['yc'] - 920, SCREEN['yc'] + 920, zb - 2, zb,
            X['rubber'] if on else X['trim_ring'])
        # проектор: корпус на штанге под потолком балкона, объектив к экрану (+X)
        px, py, pz = PROJ
        cylinder('proj_rod', px - 140, py, pz + 60, 2500, 12, X['bronze'])
        box('proj_plate', px - 200, px - 80, py - 60, py + 60, 2480, 2500, X['bronze'])
        box('proj_body', px - 320, px, py - 190, py + 190, pz - 70, pz + 60, mat('proj_white', '#E9E7E2', 0.4), bevel=12,
            seg=3)
        lens = cylinder('proj_lens', 0, 0, 0, 30, 42, X['black_glass'], seg=32)
        lens.rotation_euler = (0, math.pi / 2, 0)
        lens.location = (M(px), M(py + 60), M(pz))
        if on:
            ln = mat_emit('proj_lens_glow', (1.0, 0.95, 0.9, 1), 25.0)
            g = cylinder('proj_lens_glow', 0, 0, 0, 2, 30, ln, seg=32)
            g.rotation_euler = (0, math.pi / 2, 0)
            g.location = (M(px + 30), M(py + 60), M(pz))
    if on:
        sx, yc, w = SCREEN['x'], SCREEN['yc'], SCREEN['w']
        i0, i1 = SCREEN['img']
        black = mat('screen_black', '#141414', 0.8)
        box('screen_drop', sx - 1, sx + 1, yc - w / 2 - 40, yc + w / 2 + 40, i1, zb, black)
        box('screen_border', sx - 1, sx + 1, yc - w / 2 - 40, yc + w / 2 + 40, SCREEN['bottom'] + 20, i0, black)
        box('screen_image', sx - 2, sx, yc - w / 2, yc + w / 2, i0, i1, mat_projection())
        box('screen_bar', sx - 10, sx + 10, yc - w / 2 - 50, yc + w / 2 + 50, SCREEN['bottom'], SCREEN['bottom'] + 20,
            X['steel'])


def tv_lift(X, cut):
    """Моторизованный потолочный подъёмник: убран — ТВ лежит в коробе (снизу видна крышка-люк);
    опущен — ТВ висит в проёме O4 на телескопических штангах, низ +1000, экраном к П-дивану."""
    x0, x1, y0, y1 = LIFT
    W_, H_ = TV65
    yc, zc = TV_C
    if not cut:
        box('lift_box', x0, x1, y0, y1, LIFT_Z0, 2650, X['ceil'])
        sweep('lift_box_mould', [(x1, y0, LIFT_Z0), (x1, y1, LIFT_Z0), (x0, y1, LIFT_Z0), (x0, y0, LIFT_Z0)],
              (0, 0, 1), [(0, 0), (0, -6), (6, -12), (14, -14), (20, -18), (24, -24)], X['ceil'])
        for i, (sx, sy) in enumerate(LIFT_SPOTS):
            cylinder(f'lift_downlight_{i}', sx, sy, LIFT_Z0 - 4, LIFT_Z0, 40, X['trim_ring'], seg=24)
            cylinder(f'lift_downlight_lens_{i}', sx, sy, LIFT_Z0 - 6, LIFT_Z0 - 4, 28, X['led'], seg=24)
    if TV_STATE == 'down':
        # открытый проём в днище короба и ТВ в рабочем положении
        if not cut:
            box('lift_slot', 200, 300, yc - W_ / 2 - 20, yc + W_ / 2 + 20, LIFT_Z0 - 2, LIFT_Z0 + 2, X['rubber'])
        z0, z1 = zc - H_ / 2, zc + H_ / 2
        box('tv_lift_body', TV_X, TV_X + 45, yc - W_ / 2, yc + W_ / 2, z0, z1, X['tv_body'], bevel=3)
        box('tv_lift_screen', TV_X - 2, TV_X, yc - W_ / 2 + 6, yc + W_ / 2 - 6, z0 + 6, z1 - 6, mat_screen_on())
        for i, yy in enumerate((yc - 300, yc + 300)):
            box(f'tv_lift_arm_{i}', TV_X + 45, TV_X + 75, yy - 15, yy + 15, z1 - 120, LIFT_Z0, X['steel'])
        box('tv_lift_bar', TV_X + 45, TV_X + 75, yc - 330, yc + 330, z1 - 140, z1 - 100, X['steel'])
    elif not cut:
        # ТВ убран: снизу короба — крышка-люк с теневым швом
        box('lift_hatch', 60, 1090, yc - W_ / 2 - 30, yc + W_ / 2 + 30, LIFT_Z0 - 3, LIFT_Z0, X['ceil'], bevel=1)


def globe_pendant(name, x, y, ceil, r, zc, X):
    """Подвес: латунная штанга и опаловый шар радиуса r с центром на высоте zc."""
    BR = X['brass']
    cylinder(name + '_canopy', x, y, ceil - 20, ceil, 55, BR)
    cylinder(name + '_rod', x, y, zc + r + 25, ceil - 20, 4, BR)
    lathe(name + '_cap', [(0, zc + r - 12), (38, zc + r - 8), (45, zc + r + 10), (20, zc + r + 25), (0, zc + r + 27)],
          x, y, BR)
    prof = [(r * math.cos(math.radians(a)), zc + r * math.sin(math.radians(a))) for a in range(-90, 76, 5)]
    prof[0] = (0.0, zc - r)
    prof += [(r * 0.3, zc + r * 0.99), (0, zc + r)]
    g = lathe(name + '_globe', prof, x, y, X['opal'], seg=64)
    g.visible_shadow = False


def dining_long(X, cut):
    """K4: раздвижной овальный стол (полукруглые торцы R500, ширина 1000) на двух точёных тумбах.
    Сложен 1400 — на 4 персоны (по 2 кресла с длинных сторон); разложен 2400 (две вставки по 500) — на 10
    (по 4 кресла с длинных сторон и по одному в торцах)."""
    ext = TABLE_STATE == 'extended'
    TXC, TYC, R_ = 1900, 2585, 500
    L_ = 2400 if ext else 1400
    TX0, TX1 = TXC - L_ / 2, TXC + L_ / 2
    # столешница: две торцевые части (полукруг + 200 прямой) и в разложенном виде две вставки по 500
    def end_piece(nm, xa, xb, sign):
        cx = xa + R_ if sign < 0 else xb - R_
        arc = [(cx + sign * R_ * math.sin(math.radians(t)), TYC - R_ * math.cos(math.radians(t))) for t in range(0, 181, 6)]
        straight = [(xb, TYC + R_), (xb, TYC - R_)] if sign < 0 else [(xa, TYC + R_), (xa, TYC - R_)]
        if sign < 0:
            pts = [(xb, TYC - R_)] + [(cx - R_ * math.sin(math.radians(t)), TYC - R_ * math.cos(math.radians(t)))
                                    for t in range(0, 181, 6)] + [(xb, TYC + R_)]
        else:
            pts = [(xa, TYC - R_)] + [(cx + R_ * math.sin(math.radians(t)), TYC - R_ * math.cos(math.radians(t)))
                                    for t in range(0, 181, 6)] + [(xa, TYC + R_)]
        _ = arc, straight
        o = prism(nm, pts, 720, 760, X['oak'])
        md = o.modifiers.new('bevel', 'BEVEL')
        md.width = 0.004
        md.segments = 3
        md.limit_method = 'ANGLE'
    end_piece('table_end_w', TX0, TX0 + 700 - 1, -1)
    end_piece('table_end_e', TX1 - 700 + 1, TX1, +1)
    if ext:
        for i, x0 in enumerate((TX0 + 700, TX0 + 1200)):
            box(f'table_leaf_{i}', x0 + 1, x0 + 499, TYC - R_, TYC + R_, 720, 760, X['oak'], bevel=3, seg=2)
    # царга-рама под столешницей и две точёные тумбы с каннелюрами
    box('table_rail', TX0 + 350, TX1 - 350, TYC - 300, TYC + 300, 680, 720, X['oak'], bevel=2)
    for k, px in enumerate((TX0 + 450, TX1 - 450)):
        lathe(f'table_pedestal_{k}', [(230, 0), (230, 18), (205, 30), (140, 45), (90, 70), (74, 120), (66, 300),
                                     (60, 520), (68, 600), (82, 640), (115, 680), (150, 690)], px, TYC, X['oak_v'], seg=64)
        for i in range(16):
            a = 2 * math.pi * i / 16
            fl = box(f'table_flute_{k}_{i}', -5, 5, -4, 4, 150, 560, X['oak_v'], bevel=3)
            fl.rotation_euler = (0, 0, a)
            fl.location = (M(px) + 0.065 * math.cos(a), M(TYC) + 0.065 * math.sin(a), fl.location.z)
    # кресла с двух длинных сторон (+ торцы в разложенном виде)
    xs = (1000, 1600, 2200, 2800) if ext else (1550, 2250)
    chairs = [(x, 1935, math.pi / 2) for x in xs] + [(x, 3235, -math.pi / 2) for x in xs]
    if ext:
        chairs += [(TX0 - 300, TYC, 0.0), (TX1 + 300, TYC, math.pi)]
    for i, (cx, cy, rot) in enumerate(chairs):
        tub_chair(f'chair_{i}', cx, cy, rot, X['chair'], X['oak_v'])
    if not cut:
        for i, px in enumerate(K4_PENDANTS):
            globe_pendant(f'pendant_{i}', px, 2580, 2650, 130, 1720, X)


def sofa_k4(X):
    """K4: П-образный диван на балконе — спинка вдоль остекления B1, боковины вдоль B2/B3, открыт к проёму; пуф в центре."""
    collection('sofa')
    F, W = X['sofa'], X['wood_dark']
    X0, XS, XE = -2431, -2211, -520      # стена, лицо спинки B1, концы боковин
    YA, YB = 45, 3068                    # торцы балкона
    D = 850                              # глубина боковин
    for nm, a in (('base_b1', (X0 + 10, XS + 630, YA + 10, YB - 10)), ('base_b3', (XS + 630, XE, YA + 10, YA + D)),
                  ('base_b2', (XS + 630, XE, YB - D, YB - 10))):
        box('sofa_' + nm, *a, 110, 380, F, bevel=25, seg=3)
    for i, (lx, ly) in enumerate([(X0 + 60, YA + 60), (X0 + 60, YB - 60), (XE - 60, YA + 60), (XE - 60, YB - 60),
                                  (XE - 60, YA + D - 60), (XE - 60, YB - D + 60)]):
        box(f'sofa_leg_{i}', lx - 22, lx + 22, ly - 22, ly + 22, 0, 110, W, bevel=4)
    box('sofa_back_b1', X0, XS, YA, YB, 300, 760, F, bevel=50, seg=4)
    box('sofa_back_b3', XS, XE, YA, YA + 220, 300, 760, F, bevel=50, seg=4)
    box('sofa_back_b2', XS, XE, YB - 220, YB, 300, 760, F, bevel=50, seg=4)
    seats = [(XS, XS + 630, YA + 220, YA + D), (XS, XS + 630, YA + D, 1556), (XS, XS + 630, 1556, YB - D),
             (XS, XS + 630, YB - D, YB - 220),
             (XS + 630, -1050, YA + 220, YA + D), (-1050, XE, YA + 220, YA + D),
             (XS + 630, -1050, YB - D, YB - 220), (-1050, XE, YB - D, YB - 220)]
    for i, (x0, x1, y0, y1) in enumerate(seats):
        box(f'sofa_seat_{i}', x0 + 4, x1 - 4, y0 + 4, y1 - 4, 380, 560, F, bevel=45, seg=4, subsurf=1)
    for i, (y0, y1) in enumerate([(YA + 220, YA + D), (YA + D, 1556), (1556, YB - D), (YB - D, YB - 220)]):
        bc = box(f'sofa_bc_b1_{i}', XS - 20, XS + 190, y0 + 6, y1 - 6, 540, 920, F, bevel=60, seg=4, subsurf=1)
        bc.rotation_euler = (0, math.radians(-9), 0)
    for i, (x0, x1) in enumerate([(XS + 190, -1050), (-1050, XE)]):
        bc = box(f'sofa_bc_b3_{i}', x0 + 6, x1 - 6, YA + 200, YA + 410, 540, 920, F, bevel=60, seg=4, subsurf=1)
        bc.rotation_euler = (math.radians(9), 0, 0)
        bc = box(f'sofa_bc_b2_{i}', x0 + 6, x1 - 6, YB - 410, YB - 200, 540, 920, F, bevel=60, seg=4, subsurf=1)
        bc.rotation_euler = (math.radians(-9), 0, 0)
    for i, (px, py, mt, rx, ry, rz) in enumerate([(XS + 230, 700, 'pillow_a', 0, -15, 92), (XS + 230, 2380, 'pillow_b', 0, -15, 86),
                                                  (-900, YA + 450, 'pillow_b', 15, 0, 4), (-900, YB - 450, 'pillow_a', -15, 0, -4)]):
        p = box(f'pillow_{i}', -210, 210, -70, 70, -210, 210, X[mt], bevel=65, seg=4, subsurf=2)
        p.rotation_euler = (math.radians(rx), math.radians(ry), math.radians(rz))
        p.location = (M(px), M(py), M(770))
    # круглый пуф-столик в центре «П» с подносом
    lathe('pouf', [(0, 30), (300, 30), (335, 60), (350, 140), (350, 330), (335, 400), (300, 425), (0, 428)],
          -1150, 1556, X['chair'], seg=64)
    lathe('pouf_tray', [(0, 428), (230, 428), (232, 445), (226, 447), (0, 436)], -1150, 1556, X['brass'], seg=64)



LAYOUTS = {
    'K2': dict(
        sketch='kitchen-balcony-sketch-K2.png', open_top=2450, console_y0=3320, tv_w=1280, tv_x=1700,
        frames=[(200, 790), (940, 2460), (2610, 3200)], sconces=(495, 2905),
        table=(-1270, 1519), pendant_z0=2500,
        chairs=[(-2015, 1519, 0.0), (-795, 1519, math.pi), (-1270, 2280, -math.pi / 2), (-1270, 770, math.pi / 2)],
        cams={
            'V1': ((4300, 2750, 1600), (-1200, 1250, 1100), 20),   # общий вид из прихожей на балкон
            'V2': ((2250, 2350, 1500), (-1500, 1450, 950), 22),    # столовая на балконе через портал
            'V3': ((2650, 3240, 1600), (1700, 0, 1150), 19),       # кухонный фронт со стороны ТВ
            'V4': ((3650, 1050, 1500), (1200, 3580, 1300), 19),    # ТВ-стена и диван
            'V5': ((-2250, 2950, 1450), (-800, 300, 1050), 18),    # балкон: стол и вид в кухню
            'V6': ((770, 845, 11400), (770, 1745, 0), 48),         # 3D-план сверху (запуск с --cut)
        }),
    'K3': dict(
        sketch='kitchen-balcony-sketch-K3.png', open_top=3068, console_y0=3190, tv_w=1100, tv_x=2076,
        frames=[(250, 1200), (1376, 2776), (2950, 3400)], sconces=(725, 3175),
        table=(2054, 2019), pendant_z0=2650,
        chairs=[(1277, 2019, 0.0), (2787, 2019, math.pi), (2054, 2667, -math.pi / 2), (2054, 1372, math.pi / 2)],
        cams={
            'V1': ((4300, 2750, 1600), (-1500, 2000, 1000), 20),   # общий вид из прихожей: стол и диван на балконе
            'V2': ((3300, 700, 1550), (-1500, 2600, 900), 20),     # от кухни: столовая и угловой диван
            'V3': ((3250, 3120, 1350), (1500, 0, 1000), 19),       # кухонный фронт со стороны ТВ
            'V4': ((-1450, 1000, 1350), (2600, 2900, 1100), 19),    # с дивана на балконе в кухню и на ТВ
            'V5': ((-600, 600, 1450), (-2100, 2700, 650), 18),     # балкон-гостиная: угловой диван
            'V6': ((770, 845, 11400), (770, 1745, 0), 48),         # 3D-план сверху (запуск с --cut)
        }),
    'K4': dict(
        sketch=None, open_top=2450, tv=False, frames=[(300, 1150), (1300, 2500), (2650, 3450)],
        sconces=(725, 3050), table=(1900, 2580), pendant_z0=2650, chairs=[],
        cams={
            'V1': ((4300, 2750, 1600), (-1500, 1550, 900), 20),    # общий вид из прихожей: стол на 10 и балкон
            'V2': ((3300, 1000, 1550), (700, 3000, 950), 19),      # стол и ТВ в углу от угловой кухни
            'V3': ((2100, 3350, 1300), (3600, 250, 1050), 19),     # угловая кухня из-за стола
            'V4': ((-1300, 900, 1250), (2600, 2800, 950), 19),     # с балкона из «П» на кухню
            'V5': ((500, 1500, 1450), (-2100, 1556, 550), 20),     # П-образный диван через портал
            'V7': ((-2000, 1540, 1150), (600, 1520, 1650), 22),    # «Кино»: вид с дивана на экран в проёме
            'V6': ((770, 845, 11400), (770, 1745, 0), 48),         # 3D-план сверху (запуск с --cut)
        }),
}
LAYOUT = 'K2'
LAY = LAYOUTS[LAYOUT]


SPOTS = [(800, 800), (1600, 800), (2400, 800), (3200, 800), (700, 3150), (1700, 3150), (2700, 3150),
         (4400, 2700), (6000, 2700), (4170, 4400), (4170, 5500)]


def hall_and_doors(X):
    """Шкаф прихожей 2720×600 (C2 «шейкер») и закрытые филёнчатые двери D1–D4 (C1)."""
    box('hall_wardrobe', 4820, 7541, 3121, 3721, 0, 2650, X['upper'])
    for i in range(6):
        x0 = 4820 + i * 453
        front(f'hall_wd_{i}', x0, x0 + 453, 60, 2645, 3121, -1, X['upper'],
              handle=('vbar', x0 + (420 if i % 2 == 0 else 33), 900, 1250), hm=X['brass'])
    for nm, ax, c, sg, a0, a1 in (('D1', 'x', 3525, +1, 3721, 4621), ('D2', 'y', 5970, -1, 3720, 4600),
                                  ('D3', 'x', 4820, -1, 4150, 4930), ('D4', 'y', 2011, +1, 4240, 4960)):
        door(nm, ax, c, sg, a0, a1, X, False)


def glazing(prefix, axis, c0, c1, s_edges, inward, X, z0=1022, z1=2450, fw=62):
    """Тёплое остекление ПВХ (M32). axis='x' — рама в плоскости x∈[c0,c1] вдоль Y; 'y' — y∈[c0,c1] вдоль X."""
    PV, GL = X['pvc'], X['glass']

    def bx(nm, s0, s1, za, zb, mt, d0=c0, d1=c1):
        if axis == 'x':
            box(nm, d0, d1, s0, s1, za, zb, mt)
        else:
            box(nm, s0, s1, d0, d1, za, zb, mt)
    a, b = s_edges[0], s_edges[-1]
    bx(prefix + '_bot', a, b, z0, z0 + fw, PV)
    bx(prefix + '_top', a, b, z1 - fw, z1, PV)
    for k, s in enumerate(s_edges):
        bx(f'{prefix}_post{k}', s - fw / 2, s + fw / 2, z0 + fw, z1 - fw, PV, c0 + 1, c1 - 1)
    mid = (c0 + c1) / 2
    for k in range(len(s_edges) - 1):
        s0, s1 = s_edges[k] + fw / 2, s_edges[k + 1] - fw / 2
        bx(f'{prefix}_sash{k}_b', s0 + 40, s1 - 40, z0 + fw, z0 + fw + 40, PV, mid - 25, mid + 25)
        bx(f'{prefix}_sash{k}_t', s0 + 40, s1 - 40, z1 - fw - 40, z1 - fw, PV, mid - 25, mid + 25)
        bx(f'{prefix}_sash{k}_l', s0, s0 + 40, z0 + fw, z1 - fw, PV, mid - 25, mid + 25)
        bx(f'{prefix}_sash{k}_r', s1 - 40, s1, z0 + fw, z1 - fw, PV, mid - 25, mid + 25)
        bx(f'{prefix}_glass{k}', s0 + 40, s1 - 40, z0 + fw + 40, z1 - fw - 40, GL, mid - 3, mid + 3)
        hs = s1 - 70 if k % 2 == 0 else s0 + 70
        hd0, hd1 = sorted((mid + inward * 25, mid + inward * 55))
        bx(f'{prefix}_handle{k}', hs - 10, hs + 10, 1560, 1700, X['white'], hd0, hd1)


def curtain(nm, axis, c, s0, s1, X, z0=20, z1=2595, amp=32, wl=120):
    """Лёгкая штора на треке: волна по ширине полотна."""
    bm = bmesh.new()
    n = max(8, int(abs(s1 - s0) / (wl / 8)))
    cols = []
    for i in range(n + 1):
        s = s0 + (s1 - s0) * i / n
        off = amp * math.sin(2 * math.pi * (s - s0) / wl)
        p0 = (c + off, s, z0) if axis == 'x' else (s, c + off, z0)
        p1 = (c + off, s, z1) if axis == 'x' else (s, c + off, z1)
        cols.append((bm.verts.new(tuple(M(v) for v in p0)), bm.verts.new(tuple(M(v) for v in p1))))
    for i in range(n):
        bm.faces.new([cols[i][0], cols[i + 1][0], cols[i + 1][1], cols[i][1]])
    me = bpy.data.meshes.new(nm)
    bm.to_mesh(me)
    bm.free()
    o = link(nm, me, [X['sheer']], smooth=True)
    sd = o.modifiers.new('thick', 'SOLIDIFY')
    sd.thickness = 0.002


def door(nm, ax, c, sg, a0, a1, X, cut):
    """Филёнчатая дверь C1 в проёме: наличник, полотно с двумя филёнками, латунная ручка (закрыта)."""
    top = 2125
    if cut:
        top = min(top, 1600)
    lt = 40  # толщина полотна

    def bx(name, s0, s1, d0, d1, z0, z1, m):
        if ax == 'x':
            box(name, d0, d1, s0, s1, z0, z1, m)
        else:
            box(name, s0, s1, d0, d1, z0, z1, m)
    face = c
    lf = face - sg * 20  # лицевая плоскость полотна (полотно — в толще стены)
    bx(nm + '_leaf', a0 + 40, a1 - 40, face - sg * 60, lf, 15, min(top - 25, 2100), X['white'])
    if not cut:
        for k, (z0, z1) in enumerate(((220, 900), (1080, 1960))):
            frame_on_wall(f'{nm}_p{k}', (ax, lf, sg), a0 + 130, a1 - 130, z0, z1, X['white'], MOLD)
        # наличник с лицевой стороны
        pts_ax = [(a0 - 35, 0), (a0 - 35, top + 35), (a1 + 35, top + 35), (a1 + 35, 0)]
        pts = [(face, a, z) for a, z in pts_ax] if ax == 'x' else [(a, face, z) for a, z in pts_ax]
        sweep(nm + '_casing', pts, (sg, 0, 0) if ax == 'x' else (0, sg, 0), CASING, X['white'])
        hs = a1 - 110
        if ax == 'x':
            knob(nm + '_knob', lf, hs, 1000, sg, X['brass']).rotation_euler = (0, math.pi / 2 * sg, 0)
        else:
            knob(nm + '_knob', hs, lf, 1000, sg, X['brass'])
    # закрываем проём «стеной» за полотном (комната за дверью не моделируется)
    bx(nm + '_back', a0, a1, face - sg * 90, face - sg * 70, 0, top, X['wall'])


def tub_chair(name, cx, cy, rot, fab, wood):
    """Кресло-«корзина»: изогнутая спинка, мягкое сиденье, точёные ножки. Сиденье смотрит по +X, затем поворот rot."""
    parts = [box(name + '_seat', -225, 225, -215, 215, 400, 500, fab, bevel=40, seg=4, subsurf=1)]
    bm = bmesh.new()
    R0, R1, A = 255, 205, math.radians(230)
    n = 28
    rings = []
    for r in (R0, R1):
        for zt in (450, 790):
            ring = []
            for i in range(n + 1):
                a = math.pi - A / 2 + A * i / n
                z = zt if zt == 450 else zt - 80 * (abs(i - n / 2) / (n / 2)) ** 2
                ring.append(bm.verts.new((M(r * math.cos(a) - 40), M(r * math.sin(a)), M(z))))
            rings.append(ring)
    ob, ot, ib, it = rings
    for i in range(n):
        bm.faces.new([ob[i], ob[i + 1], ot[i + 1], ot[i]])
        bm.faces.new([ib[i + 1], ib[i], it[i], it[i + 1]])
        bm.faces.new([ot[i], ot[i + 1], it[i + 1], it[i]])
        bm.faces.new([ob[i + 1], ob[i], ib[i], ib[i + 1]])
    bm.faces.new([ob[0], ot[0], it[0], ib[0]])
    bm.faces.new([ib[n], it[n], ot[n], ob[n]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name + '_back')
    bm.to_mesh(me)
    bm.free()
    back = link(name + '_back', me, [fab], smooth=True)
    bv = back.modifiers.new('bevel', 'BEVEL')
    bv.width = 0.018
    bv.segments = 3
    sub = back.modifiers.new('sub', 'SUBSURF')
    sub.levels = sub.render_levels = 1
    parts.append(back)
    for i, (lx, ly) in enumerate([(-160, -150), (-160, 150), (160, -150), (160, 150)]):
        parts.append(lathe(f'{name}_leg{i}', [(15, 0), (17, 60), (21, 330), (20, 400), (0, 401)], lx, ly, wood, seg=16))
    c, s = math.cos(rot), math.sin(rot)
    for p in parts:
        x, y, z = p.location
        p.location = (M(cx) + x * c - y * s, M(cy) + x * s + y * c, z)
        p.rotation_euler.z += rot


def tree(name, x, y, s, X):
    """Дерево за окном: ствол + крона из нескольких сглаженных «облаков» (листва — бамп и просвет)."""
    h = 3000 * s
    cylinder(name + '_trunk', x, y, -1100, -1100 + h + 900 * s, 130 * s, X['trunk'], seg=12, r_top=70 * s)
    rnd = random.Random(int(abs(x) + abs(y)))
    bm = bmesh.new()
    for k in range(9):
        r = M(rnd.uniform(850, 1350) * s)
        off = Vector((rnd.uniform(-1.3, 1.3), rnd.uniform(-1.3, 1.3), rnd.uniform(-0.6, 1.4))) * s
        mtx = Matrix.Translation(off)
        res = bmesh.ops.create_icosphere(bm, subdivisions=3, radius=r, matrix=mtx)
        seed = Vector((x, y, k)) * 0.001
        for v in res['verts']:
            v.co += (v.co - off).normalized() * r * 0.12 * noise.fractal(v.co * 2.2 + seed, 0.6, 2.0, 3)
    me = bpy.data.meshes.new(name + '_crown')
    bm.to_mesh(me)
    bm.free()
    o = link(name + '_crown', me, [X['leaves']], smooth=True)
    sd = o.modifiers.new('sub', 'SUBSURF')
    sd.levels = sd.render_levels = 1
    o.location = (M(x), M(y), M(-1100 + h + 900 * s))


def spot(name, x, y, z, power, color, angle):
    ld = bpy.data.lights.new(name, 'SPOT')
    ld.energy = power
    ld.color = color
    ld.spot_size = math.radians(angle)
    ld.spot_blend = 0.6
    ld.shadow_soft_size = 0.02
    o = bpy.data.objects.new(name, ld)
    COL['cur'].objects.link(o)
    o.location = (M(x), M(y), M(z))
    return o


def point(name, x, y, z, power, color, radius):
    ld = bpy.data.lights.new(name, 'POINT')
    ld.energy = power
    ld.color = color
    ld.shadow_soft_size = M(radius)
    o = bpy.data.objects.new(name, ld)
    COL['cur'].objects.link(o)
    o.location = (M(x), M(y), M(z))
    return o


def area(name, x, y, z, sx, sy, power, color):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = power
    ld.color = color
    ld.shape = 'RECTANGLE'
    ld.size, ld.size_y = M(sx), M(sy)
    o = bpy.data.objects.new(name, ld)
    COL['cur'].objects.link(o)
    o.location = (M(x), M(y), M(z))
    return o


def sun_and_sky(cut):
    """Солнце: азимут 115° (ВЮВ), высота 28°; в осях проекта −X = СВ, +Y = ЮВ (D25)."""
    sc = bpy.context.scene
    az, el = (115.0, 50.0) if cut else (115.0, 28.0)
    phi = math.radians(225.0 - az)
    d = Vector((math.cos(el / 57.2958) * math.cos(phi), math.cos(el / 57.2958) * math.sin(phi), math.sin(el / 57.2958)))
    ld = bpy.data.lights.new('sun', 'SUN')
    ld.energy = 4.2
    ld.angle = math.radians(0.8)
    ld.color = (1.0, 0.93, 0.84)
    o = bpy.data.objects.new('sun', ld)
    COL['cur'].objects.link(o)
    o.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
    w = bpy.data.worlds.new('sky')
    sc.world = w
    N, L = w.node_tree.nodes, w.node_tree.links
    bg = N['Background']
    sky = N.new('ShaderNodeTexSky')
    for t in ('MULTIPLE_SCATTERING', 'SINGLE_SCATTERING', 'NISHITA', 'HOSEK_WILKIE'):
        try:
            sky.sky_type = t
            break
        except TypeError:
            continue
    for k, v in (('sun_disc', False), ('sun_elevation', math.radians(el)),
                 ('sun_rotation', math.atan2(d.x, d.y))):
        try:
            setattr(sky, k, v)
        except (AttributeError, TypeError):
            pass
    L.new(sky.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 0.22 if not cut else 0.3


def camera(name, pos, tgt, lens, level=True):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36
    cd.clip_start = 0.05
    o = bpy.data.objects.new(name, cd)
    COL['cur'].objects.link(o)
    p, t = Vector([M(v) for v in pos]), Vector([M(v) for v in tgt])
    d = t - p
    o.location = p
    if level:
        # горизонтальная камера + сдвиг объектива: вертикали остаются вертикальными
        yaw = math.atan2(d.y, d.x) - math.pi / 2
        o.rotation_euler = (math.pi / 2, 0, yaw)
        horiz = math.hypot(d.x, d.y)
        cd.shift_y = max(-0.25, min(0.25, (d.z / horiz) * lens / 36.0 * 0.9))
    else:
        o.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return o


def render_settings():
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    cy = sc.cycles
    cy.device = 'CPU'
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.02
    cy.use_denoising = True
    try:
        cy.denoiser = 'OPENIMAGEDENOISE'
    except TypeError:
        pass
    cy.max_bounces = 10
    cy.diffuse_bounces = 5
    cy.glossy_bounces = 4
    cy.transmission_bounces = 8
    cy.transparent_max_bounces = 16
    cy.sample_clamp_indirect = 8.0
    cy.blur_glossy = 1.0
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    sc.render.film_transparent = False
    sc.view_settings.view_transform = 'AgX'
    for look in ('AgX - Medium High Contrast', 'Medium High Contrast', 'AgX - Base Contrast'):
        try:
            sc.view_settings.look = look
            break
        except TypeError:
            continue
    sc.view_settings.exposure = 0.0
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_depth = '8'


def render(view, res, samples, out_dir, exposure=0.0, layout='K2'):
    sc = bpy.context.scene
    sc.camera = bpy.data.objects['CAM_' + view]
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.cycles.samples = samples
    sc.view_settings.exposure = exposure
    out = Path(out_dir) / (f'kitchen-balcony-{view}.png' if layout == 'K2' else f'kitchen-balcony-{layout}-{view}.png')
    sc.render.filepath = str(out)
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print(f'  {view}: {out} ({time.time() - t:.0f} c)')
    return out


EXPOSURE = {'V7': 0.3, 'V1': 0.35, 'V2': 0.3, 'V3': 0.45, 'V4': 0.45, 'V5': 0.0, 'V6': -0.2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--views', default='')
    ap.add_argument('--res', default='1920x1080')
    ap.add_argument('--samples', type=int, default=256)
    ap.add_argument('--out', default=str(OUT / 'renders'))
    ap.add_argument('--cut', action='store_true', help='сцена «кукольный домик» (для V6)')
    ap.add_argument('--cinema', action='store_true', help='K4: режим «Кино» — экран опущен, проектор работает')
    ap.add_argument('--table', default='compact', choices=('compact', 'extended'),
                    help='K4: раздвижной стол сложен (4 персоны) или разложен (10)')
    ap.add_argument('--layout', default='K2', choices=sorted(LAYOUTS), help='эскиз заказчика: K2 или K3')
    ap.add_argument('--blend', default='', help='сохранить .blend')
    ap.add_argument('--threads', type=int, default=0)
    a = ap.parse_args(sys.argv[1:])
    res = tuple(int(v) for v in a.res.lower().split('x'))
    Path(a.out).mkdir(parents=True, exist_ok=True)
    t = time.time()
    global LAYOUT, LAY, TABLE_STATE, TV_STATE, CORNER
    LAYOUT, LAY, TABLE_STATE, TV_STATE = a.layout, LAYOUTS[a.layout], a.table, ('balcony' if a.cinema else 'kitchen')
    CORNER = LAYOUT == 'K4'
    build(cut=a.cut)
    if a.threads:
        bpy.context.scene.render.threads_mode = 'FIXED'
        bpy.context.scene.render.threads = a.threads
    print(f'сцена собрана за {time.time() - t:.1f} c, объектов: {len(bpy.data.objects)}')
    if a.blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(a.blend).resolve()))
        print('  .blend:', a.blend)
    for v in [v for v in a.views.split(',') if v]:
        tag = a.layout + ('-ext' if a.layout == 'K4' and a.table == 'extended' else '') + \
            ('-cinema' if a.layout == 'K4' and a.cinema else '')
        render(v, res, a.samples, a.out, EXPOSURE.get(v, 0.0), tag)


if __name__ == '__main__':
    main()
