"""Общие элементы планов: стены (существующие / демонтаж / новые), проёмы, двери, мебель, помещения."""
from __future__ import annotations

import math
import re

from shapely.geometry import box, Polygon
from shapely.ops import unary_union, polylabel

import model as m
from draw import View, Sheet, text_w

# bbox плана квартиры с балконом (модельные мм)
PLAN_BBOX = (-2640, -190, 7835, 9340)

C_EXT = "#262626"       # несущие/наружные
C_PART = "#6e6e6e"      # перегородки застройщика
C_BASE = "#9a9a9a"      # подложка (стены)
C_BASE_F = "#b8b8b8"    # подложка (мебель)
C_NEW = "#1f4e9c"
C_DEMO = "#c0392b"

# штриховки новых конструкций по материалу (ГОСТ 2.306 — условно)
MAT_STYLE = {
    "pgp": dict(hatch="////", fc="white", hc=C_NEW, label="ПГП 80 полнотелые (гипсовые) — новая перегородка"),
    "pgp_w": dict(hatch="\\\\\\\\", fc="#e3eefb", hc=C_NEW, label="ПГП-Г 80 гидрофобизированные (мокрые зоны)"),
    "pgp_gkl": dict(hatch="///", fc="#fbf3df", hc=C_NEW, label="ПГП 100 + ГКЛ 12,5 (закладка проёма в плоскости несущей стены)"),
    "gkl": dict(hatch="....", fc="white", hc=C_NEW, label="Облицовка/короб ГКЛВ/ГВЛВ на каркасе"),
    "infill": dict(hatch="---", fc="#f3ead8", hc="#8a6d3b", label="Зашивка окна изнутри: каркас + утеплитель + пароизоляция + 2×ГКЛ"),
    "pgp_d": dict(hatch="////", fc="#fff6f6", hc=C_NEW, label="Добор ПГП в проёме O8 (по doors.json)"),
}


def wall_material(wid, mat_text=""):
    t = (mat_text or "").lower()
    if wid == "D1-доб":
        return "pgp_d"
    if "гкл" in t and "пгп 100" in t:
        return "pgp_gkl"
    if "пгп-г" in t or "гидрофоб" in t:
        return "pgp_w"
    if "пгп" in t:
        return "pgp"
    return "gkl"


def fit_view(sh: Sheet, scale, x0, y0, x1, y1, bbox=PLAN_BBOX, align="top-left", pad=(0, 0, 0, 0)):
    """Вид плана в прямоугольнике бумаги (x0,y0)-(x1,y1); pad — модельные поля (лево, низ, право, верх)."""
    bx0, by0, bx1, by1 = bbox
    bx0 -= pad[0]
    by0 -= pad[1]
    bx1 += pad[2]
    by1 += pad[3]
    wpap = (bx1 - bx0) / scale
    hpap = (by1 - by0) / scale
    if align == "center":
        px = x0 + (x1 - x0 - wpap) / 2
        py = y0 + (y1 - y0 - hpap) / 2
    else:
        px = x0
        py = y1 - hpap
    v = View(sh, scale, (bx0, by0), (px, py))
    v.extent = (px, py, px + wpap, py + hpap)
    return v


# ---------------------------------------------------------------- стены
def _is_ext(wid):
    w = m.WALLS.get(wid)
    return (w and w["type"] in m.EXT_TYPES) or wid == "C1"


def draw_existing_walls(v: View, base=False, lw=0.35, with_openings=True, occupy=False):
    """Существующие стены (обмер): сплошная заливка; base=True — серая подложка."""
    ex = m.existing_wall_polys()
    holes = {}
    for oid, wid, s0, s1, typ in m.existing_openings():
        holes.setdefault(wid, []).append(m.opening_rect(m.WALLS[wid], s0, s1))
    for wid, g in ex.items():
        if with_openings:
            for h in holes.get(wid, []):
                g = g.difference(h)
        if base:
            v.shape(g, layer="AR-WALLS", fc=C_BASE, ec="#7f7f7f", lw=0.13, z=3)
        elif wid == "C1":
            v.shape(g, layer="AR-WALLS", fc="#d9d9d9", hatch="xx", hc="#333333", ec="black", lw=lw, z=3)
        else:
            v.shape(g, layer="AR-WALLS", fc=C_EXT if _is_ext(wid) else C_PART, ec="black", lw=lw, z=3)
        if occupy:
            _occupy_geom(v, g)
    draw_glazing(v, base=base)


def _occupy_geom(v, g):
    gg = v.geom(g)
    for p in getattr(gg, "geoms", [gg]):
        if not p.is_empty:
            v.sh.occupy(p.bounds)


def draw_glazing(v: View, base=False):
    col = C_BASE if base else "black"
    for wid, poly in m.glazing_polys().items():
        x0, y0, x1, y1 = poly.bounds
        v.rect(x0, y0, x1, y1, layer="AR-WALLS", ec=col, lw=0.18, fc="white", z=3)
        if (x1 - x0) > (y1 - y0):
            v.line((x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2), layer="AR-WALLS", ec=col, lw=0.13, z=3.1)
        else:
            v.line(((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1), layer="AR-WALLS", ec=col, lw=0.13, z=3.1)


def draw_final_walls(v: View, base=False, show_new_hatch=True, show_constructions=True, occupy=False, lw=0.35):
    """Стены после перепланировки D1: сохраняемые + новые (по материалу)."""
    g = m.final_geometry()
    for wid, poly in g["kept"].items():
        if base:
            v.shape(poly, layer="AR-WALLS", fc=C_BASE, ec="#7f7f7f", lw=0.13, z=3)
        elif wid == "C1":
            v.shape(poly, layer="AR-WALLS", fc="#d9d9d9", hatch="xx", hc="#333333", ec="black", lw=lw, z=3)
        else:
            v.shape(poly, layer="AR-WALLS", fc=C_EXT if _is_ext(wid) else C_PART, ec="black", lw=lw, z=3)
        if occupy:
            _occupy_geom(v, poly)
    for wid, poly in g["new"].items():
        mt = m.NEW_WALLS.get(wid, {}).get("material", "")
        st = MAT_STYLE[wall_material(wid, mt)]
        if base:
            v.shape(poly, layer="AR-NEW", fc="#c4c4c4", ec="#7f7f7f", lw=0.13, z=3)
        elif show_new_hatch:
            v.shape(poly, layer="AR-NEW", fc=st["fc"], hatch=st["hatch"], hc=st["hc"], ec=C_NEW, lw=0.4, z=3.2)
        else:
            v.shape(poly, layer="AR-NEW", fc=C_PART, ec="black", lw=lw, z=3)
        if occupy:
            _occupy_geom(v, poly)
    if show_constructions:
        for cid, (poly, c) in m.construction_polys().items():
            st = MAT_STYLE["gkl"]
            if base:
                v.shape(poly, layer="AR-NEW", fc="#d4d4d4", ec="#8f8f8f", lw=0.1, z=3)
            else:
                v.shape(poly, layer="AR-NEW", fc=st["fc"], hatch=st["hatch"], hc=st["hc"], ec=C_NEW, lw=0.25, z=3.2)
    draw_glazing(v, base=base)


# ---------------------------------------------------------------- окна/двери
def _window_symbol(v, wall, s0, s1, col="black", infill=False, lw=0.18):
    t = wall["thickness"]
    hor = m.is_horizontal(wall)
    if hor:
        y = wall["a"][1]
        y0, y1 = y - t / 2, y + t / 2
        v.rect(s0, y0, s1, y1, layer="AR-WALLS", ec=col, lw=lw, fc="white", z=3.3)
        for f in (0.42, 0.58):
            yy = y0 + t * f
            v.line((s0, yy), (s1, yy), layer="AR-WALLS", ec=col, lw=0.13, z=3.4)
    else:
        x = wall["a"][0]
        x0, x1 = x - t / 2, x + t / 2
        v.rect(x0, s0, x1, s1, layer="AR-WALLS", ec=col, lw=lw, fc="white", z=3.3)
        for f in (0.42, 0.58):
            xx = x0 + t * f
            v.line((xx, s0), (xx, s1), layer="AR-WALLS", ec=col, lw=0.13, z=3.4)
    if infill:
        st = MAT_STYLE["infill"]
        # зашивка изнутри: полоса у внутренней грани (W2: x 0..-150)
        if hor:
            g = box(s0, wall["a"][1] - t / 2, s1, wall["a"][1] - t / 2 + 150)
        else:
            g = box(wall["a"][0] + t / 2 - 160, s0, wall["a"][0] + t / 2, s1)
        v.shape(g, layer="AR-NEW", fc=st["fc"], hatch=st["hatch"], hc=st["hc"], ec=C_NEW, lw=0.3, z=3.5)


def draw_windows(v: View, final=True, base=False):
    col = C_BASE if base else "black"
    for o in m.M["openings"]:
        if o["type"] != "window":
            continue
        s0, s1 = m.opening_span(o)
        infill = final and o["id"] == "O1" and not base
        _window_symbol(v, m.WALLS[o["wall"]], s0, s1, col=col, infill=infill)


def _door(v, wall, s0, s1, hinge_s, leaf, side, col="black", lw=0.25, layer="AR-WALLS", double=False, ls="solid"):
    """Дверь: полотно (линия) + дуга открывания. side = +1/−1 — направление открывания по нормали к стене."""
    t = wall["thickness"]
    hor = m.is_horizontal(wall)
    if hor:
        y = wall["a"][1]
        face = y + side * t / 2
        hinges = [(s0, 1), (s1, -1)] if double else [(hinge_s, 1 if abs(hinge_s - s0) < abs(hinge_s - s1) else -1)]
        for hs, dirn in hinges:
            L = leaf if not double else (s1 - s0) / 2
            hp = (hs, face)
            ep = (hs, face + side * L)
            v.line(hp, ep, layer=layer, ec=col, lw=lw * 1.4, ls=ls, z=3.6)
            # дуга от полотна к закрытому положению
            a_leaf = 90 if side > 0 else 270
            a_closed = 0 if dirn > 0 else 180
            a0, a1 = sorted([a_leaf, a_closed])
            if a1 - a0 > 180:
                a0, a1 = a1, a0 + 360
            v.arc(hp, L, a0, a1, layer=layer, ec=col, lw=0.13, ls=ls, z=3.6)
    else:
        x = wall["a"][0]
        face = x + side * t / 2
        hinges = [(s0, 1), (s1, -1)] if double else [(hinge_s, 1 if abs(hinge_s - s0) < abs(hinge_s - s1) else -1)]
        for hs, dirn in hinges:
            L = leaf if not double else (s1 - s0) / 2
            hp = (face, hs)
            ep = (face + side * L, hs)
            v.line(hp, ep, layer=layer, ec=col, lw=lw * 1.4, ls=ls, z=3.6)
            a_leaf = 0 if side > 0 else 180
            a_closed = 90 if dirn > 0 else 270
            a0, a1 = sorted([a_leaf, a_closed])
            if a1 - a0 > 180:
                a0, a1 = a1, a0 + 360
            v.arc(hp, L, a0, a1, layer=layer, ec=col, lw=0.13, ls=ls, z=3.6)


# существующие двери (из примечаний measurements.json: O4 двустворчатая в кухню; O5 петли x 6220, наружу;
# O6 петли x 5910, в прихожую; O7 петли y 4531, в коридор)
EXISTING_DOORS = {
    "O4": dict(double=True, side=+1, leaf=930),
    "O5": dict(hinge=6220, side=-1, leaf=1040),
    "O6": dict(hinge=5910, side=+1, leaf=900),
    "O7": dict(hinge=4531, side=-1, leaf=900),
}


def draw_existing_doors(v: View, col="black", ls="solid", layer="AR-WALLS", only=None):
    for oid, d in EXISTING_DOORS.items():
        if only and oid not in only:
            continue
        o = m.OPEN[oid]
        s0, s1 = m.opening_span(o)
        _door(v, m.WALLS[o["wall"]], s0, s1, d.get("hinge", s0), d["leaf"], d["side"], col=col,
              double=d.get("double", False), ls=ls, layer=layer)


ROOM_WORDS = [("спальн", "R1"), ("детск", "R2"), ("коридор", "R4"), ("прихож", "R4"), ("кухн", "R3")]


def new_doors():
    """Двери D1..D4 (planning.json + doors.json) с петлями и стороной открывания."""
    res = []
    dmap = {d["id"]: d for d in m.DO["doors"]}
    for o in m.new_opening_list():
        if not o.get("leaf"):
            continue
        wall = m.wall_by_id(o["wall_id"])
        mm = re.search(r"петли у ([xy])\s*=\s*(\d+)", o["swing"])
        hinge = float(mm.group(2)) if mm else o["s0"]
        target = None
        for w, r in ROOM_WORDS:
            if w in o["swing"]:
                target = r
                break
        # сторона: пробная точка по нормали
        side = 1
        if target:
            poly = Polygon(m.ROOMS[target]["polygon"])
            sm = (o["s0"] + o["s1"]) / 2
            t = wall["thickness"]
            for sd in (1, -1):
                if m.is_horizontal(wall):
                    pt = (sm, wall["a"][1] + sd * (t / 2 + 200))
                else:
                    pt = (wall["a"][0] + sd * (t / 2 + 200), sm)
                from shapely.geometry import Point
                if poly.contains(Point(pt)):
                    side = sd
                    break
        no = dmap.get(o["id"], {}).get("no", o["id"])
        res.append(dict(o, wall=wall, hinge=hinge, side=side, mark=no, target=target))
    return res


def draw_new_doors(v: View, col="black", layer="AR-WALLS", marks=False, h=2.2):
    for d in new_doors():
        _door(v, d["wall"], d["s0"], d["s1"], d["hinge"], d["leaf"], d["side"], col=col, layer=layer)
        if marks:
            door_mark(v, d)


def door_mark(v, d, h=2.0):
    """Маркировка двери в кружке у проёма."""
    wall = d["wall"]
    sm = (d["s0"] + d["s1"]) / 2
    t = wall["thickness"]
    off = -(d["side"]) * (t / 2 + 260)
    pt = (sm, wall["a"][1] + off) if m.is_horizontal(wall) else (wall["a"][0] + off, sm)
    q = v.P(pt)
    s = d["mark"]
    r = max(2.6, text_w(s, h) / 2 + 0.8)
    v.sh.circle(q, r, layer="TEXT", ec="black", lw=0.25, fc="white", z=7)
    v.sh.text((q[0], q[1] - h / 2), s, h, ha="center", z=7.5)
    v.sh.occupy((q[0] - r, q[1] - r, q[0] + r, q[1] + r))


def portal(v: View, col="black"):
    """Портал O4 без заполнения — штрихпунктир по граням (линия проёма)."""
    o = m.OPEN["O4"]
    s0, s1 = m.opening_span(o)
    for x in (-420, 0):
        v.line((x, s0), (x, s1), layer="AR-WALLS", ec=col, lw=0.13, ls="dashdot", z=3.4)


def draw_entrance(v: View, col="black"):
    draw_existing_doors(v, col=col, only=("O5",))


def draw_plan_final(v: View, base=False, marks=False, occupy=False):
    draw_final_walls(v, base=base, occupy=occupy)
    draw_windows(v, final=True, base=base)
    col = C_BASE if base else "black"
    draw_new_doors(v, col=col, marks=marks)
    draw_existing_doors(v, col=col, only=("O5",))
    portal(v, col=col)


# ---------------------------------------------------------------- мебель
def _rot_pts(it):
    return m.frect(it)


def draw_furniture(v: View, base=False, ids=None, label=False, h=1.8, skip_types=(), lw=None):
    col = C_BASE_F if base else "#3a3a3a"
    lw0 = lw or (0.13 if base else 0.18)
    for it in m.FU["items"]:
        if ids and it["id"] not in ids:
            continue
        if it["type"] in skip_types:
            continue
        x0, y0, x1, y1 = m.frect(it)
        if x1 - x0 < 1 or y1 - y0 < 1:
            # нулевая толщина (душ без поддона) — пунктирный контур
            pass
        ls = "dashed" if it.get("layer") == "wall" else "solid"
        typ = it["type"]
        fc = None if base else {"bed": "#f4efe6", "sofa": "#ece7dc", "sanitary": "white", "wardrobe": "#f2efe9",
                                "kitchen_base": "#f2efe9", "table": "#f6f2ea"}.get(typ)
        if typ == "other" and it.get("size", [0, 0, 0])[2] <= 20:
            ls = "dotted"
        v.rect(x0, y0, x1, y1, layer="FURN", ec=col, lw=lw0, ls=ls, fc=fc, z=2.5)
        _furn_detail(v, it, (x0, y0, x1, y1), col)
    if label:
        for it in m.FU["items"]:
            if ids and it["id"] not in ids:
                continue
            x0, y0, x1, y1 = m.frect(it)
            v.label(((x0 + x1) / 2, (y0 + y1) / 2), it["id"], h, layer="FURN", color="#1a1a1a",
                    radius=(0, 2.5, 4.5, 7, 10, 14, 19), lcolor="#555555")


def _furn_detail(v, it, r, col):
    x0, y0, x1, y1 = r
    typ = it["type"]
    rot = it.get("rotation", 0)
    lw = 0.1
    w, d = x1 - x0, y1 - y0
    if typ == "bed":
        # подушки у изголовья (спинка — сторона «к стене» по rotation)
        if rot in (90, 270):
            hx = x0 if rot == 270 else x1 - 250
            n = 2 if d > 1200 else 1
            for i in range(n):
                py0 = y0 + 80 + i * (d - 160) / n
                v.rect(hx + 40 if rot == 270 else hx, py0, hx + 250 if rot == 270 else hx + 210,
                       py0 + (d - 160) / n - 60, layer="FURN", ec=col, lw=lw, z=2.6)
        else:
            hy = y1 - 250 if rot == 180 else y0
            n = 2 if w > 1200 else 1
            for i in range(n):
                px0 = x0 + 80 + i * (w - 160) / n
                v.rect(px0, hy + 40, px0 + (w - 160) / n - 60, hy + 210, layer="FURN", ec=col, lw=lw, z=2.6)
    elif typ == "wardrobe":
        v.line((x0, y0), (x1, y1), layer="FURN", ec=col, lw=lw, z=2.6)
    elif typ == "sanitary":
        nm = it["name"].lower()
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if "унитаз" in nm:
            v.circle((cx, cy), min(w, d) * 0.38, layer="FURN", ec=col, lw=lw, z=2.6)
        elif "ванна" in nm:
            v.rect(x0 + 60, y0 + 60, x1 - 60, y1 - 60, layer="FURN", ec=col, lw=lw, z=2.6)
            v.circle((x1 - 150 if w > d else cx, cy if w > d else y1 - 150), 30, layer="FURN", ec=col, lw=lw, z=2.6)
        elif "мойк" in nm or "раковин" in nm:
            v.circle((cx, cy), min(w, d) * 0.3, layer="FURN", ec=col, lw=lw, z=2.6)
    elif typ == "appliance":
        nm = it["name"].lower()
        if "варочн" in nm:
            for fx in (0.3, 0.7):
                for fy in (0.3, 0.7):
                    v.circle((x0 + w * fx, y0 + d * fy), min(w, d) * 0.14, layer="FURN", ec=col, lw=lw, z=2.6)
        elif "колонна" in nm or "стиральн" in nm:
            v.circle(((x0 + x1) / 2, (y0 + y1) / 2), min(w, d) * 0.33, layer="FURN", ec=col, lw=lw, z=2.6)
    elif typ == "chair":
        v.rect(x0 + 40, y0 + 40, x1 - 40, y1 - 40, layer="FURN", ec=col, lw=lw, z=2.6)
    elif typ == "sofa":
        pass


# ---------------------------------------------------------------- помещения
def room_point(rid, rooms=None):
    r = (rooms or m.ROOMS)[rid]
    p = Polygon(r["polygon"])
    c = polylabel(p, 10)
    return (c.x, c.y)


ROOM_TAG_POS = {"R4": (6100, 2700), "R6": (5000, 950), "R5": (6050, 5150), "R3": (2000, 2500),
                "R7": (-1480, 1700), "R1": (1690, 5800), "R2": (5600, 7700)}


def room_tag(v: View, rid, name, area, h=2.5, number=True, pos=None, extra=None, color="black"):
    pt = pos or ROOM_TAG_POS.get(rid) or room_point(rid)
    no = m.ROOM_NO.get(rid, "")
    q = v.P(pt)
    s1 = f"{no}. {name}" if number else name
    s2 = f"{m.fmt_num(area)} м²" if area is not None else ""
    w = max(text_w(s1, h, True), text_w(s2, h)) + 1.6
    lines = [s1] + ([s2] if s2 else []) + ([extra] if extra else [])
    hh = len(lines) * h * 1.5 + 0.8
    x0 = q[0] - w / 2
    y1 = q[1] + hh / 2
    for i, ln in enumerate(lines):
        v.sh.text((q[0], y1 - (i + 1) * h * 1.5 + 0.3), ln, h if i < 2 else h * 0.85, ha="center", bold=(i == 0),
                  color=color, z=7, bg="white")
    if s2:
        yl = y1 - h * 1.5 + 0.3 - 0.5 * h
        v.sh.line((x0 + 0.8, yl), (x0 + w - 0.8, yl), layer="TEXT", lw=0.13, ec=color, z=7.2)
    v.sh.occupy((x0, y1 - hh, x0 + w, y1))


# ---------------------------------------------------------------- инженерные точки обмера
UT_STYLE = {
    "riser_sewer": ("К1", "#6b3d1f"), "riser_water": ("В", "#1f6fd6"), "riser_box": ("", "#8a8a8a"),
    "vent_shaft": ("ВК", "#d35400"), "vent_grille": ("Р", "#d35400"), "ufh_manifold": ("КТП", "#2e8b57"),
    "el_panel": ("ЩК", "#c0392b"), "lowcurrent_panel": ("СС", "#2c7a2c"), "balcony_post_or_drain": ("?", "#4a6fa5"),
}


def draw_utilities(v: View, labels=True, h=1.8, base=False):
    for u in m.M["utilities"]:
        lab, col = UT_STYLE.get(u["type"], ("", "black"))
        if base:
            col = "#8a8a8a"
        if "rect" in u:
            (x0, y0), (x1, y1) = u["rect"]
            if u["type"] == "riser_box":
                v.rect(x0, y0, x1, y1, layer="VK", ec=col, lw=0.25, ls="dashed", z=3.8)
            elif u["type"] == "vent_shaft" and u["id"] in ("U25", "U26"):
                continue  # условно в коробе стояков — показывается текстом
            else:
                v.rect(x0, y0, x1, y1, layer="OV" if "vent" in u["type"] else "VK", ec=col, lw=0.25,
                       fc="#ffffff", hatch="xx" if u["type"] == "vent_shaft" else "///", hc=col, z=3.8)
        elif u["type"] in ("riser_sewer", "riser_water"):
            r = u.get("dia", 50) / 2
            v.circle(u["pos"], r_mm=max(r, 30), layer="VK", ec=col, lw=0.3, fc="white", z=4)
            if u["type"] == "riser_sewer":
                v.circle(u["pos"], r_mm=max(r, 30) * 0.45, layer="VK", ec=col, lw=0.1, fc=col, z=4.1)
        elif u["type"] in ("el_panel", "lowcurrent_panel"):
            x, y = u["pos"]
            hh = 155 if u["type"] == "el_panel" else 200
            v.rect(x - 110, y - hh, x, y + hh, layer="EL-SOCKET" if u["type"] == "el_panel" else "EL-LOW",
                   ec=col, lw=0.3, fc=col if u["type"] == "el_panel" else "white", hatch=None, z=4)
        elif u["type"] == "vent_grille":
            x, y = u["pos"]
            v.rect(x - 40, y - 50, x + 40, y + 50, layer="OV", ec=col, lw=0.25, fc="white", hatch="||", hc=col, z=4)
        elif u["type"] == "balcony_post_or_drain":
            v.circle(u["pos"], r_mm=u.get("dia", 200) / 2, layer="AR-WALLS", ec=col, lw=0.2, ls="dashed", z=4)
