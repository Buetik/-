"""Единая модель данных для рабочих чертежей (pib-cad).

Только чтение слоёв данных: 01-input/measurements.json, 03-drawings/*.json, 02-concept/*.json.
Ничего не меняет в исходных данных. Геометрия — в мм, система measurements.json
(0,0 — внутренний угол W2×W3, X вправо, Y вверх).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
DRAW = ROOT / "03-drawings"


def jload(rel):
    p = ROOT / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------------------------------------------------------------- слои данных
M = jload("01-input/measurements.json")
MS = jload("03-drawings/measurement.json")
PL = jload("03-drawings/planning.json")
FU = jload("03-drawings/furniture.json")
DO = jload("03-drawings/doors.json")
EL = jload("03-drawings/electrical.json")
PN = jload("03-drawings/panel.json")
VK = jload("03-drawings/plumbing.json")
HT = jload("03-drawings/heating.json")
HV = jload("03-drawings/hvac.json")
CE = jload("03-drawings/ceilings.json")
FL = jload("03-drawings/floors.json")
EV = jload("03-drawings/elevations.json")
PAL = jload("02-concept/palette.json")
MAT = jload("02-concept/materials.json")
FQ = jload("04-specs/finish-quantities.json")
OPTIONS = {k: jload(f"03-drawings/planning-option-{k}.json") for k in ("A", "B", "C", "D1", "D2")}
REGISTER_PATH = DRAW / "sheet-register.json"

WALLS = {w["id"]: w for w in M["walls"]}
OPEN = {o["id"]: o for o in M["openings"]}
UT = {u["id"]: u for u in M["utilities"]}
ROOMS_M = {r["id"]: r for r in M["rooms"]}
ROOMS = {r["id"]: r for r in PL["rooms"]}
FI = {f["id"]: f for f in FU["items"]}
NEW_WALLS = {w["id"]: w for w in PL["new_walls"]}

ROOM_NO = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5, "R6": 6, "R7": 7}

OBJECT = "Квартира №108, СПб, дизайн-проект"
AUTHOR = "pib-агенты"
DATE = "10.2026"
STAGE = "Р"
CIPHER = "КВ108-ДП"


# ---------------------------------------------------------------- геометрия
def wall_rect(a, b, t):
    (x1, y1), (x2, y2) = a, b
    if abs(y1 - y2) < 1e-6:
        return box(min(x1, x2), y1 - t / 2, max(x1, x2), y1 + t / 2)
    return box(x1 - t / 2, min(y1, y2), x1 + t / 2, max(y1, y2))


def is_horizontal(w):
    return abs(w["a"][1] - w["b"][1]) < 1e-6


def parse_span(s):
    """'y 5686..7546 по внутр. грани' -> ('y', 5686, 7546)."""
    m = re.search(r"([xy])\s*(-?\d+(?:\.\d+)?)\s*\.\.\s*(-?\d+(?:\.\d+)?)", s)
    if not m:
        return None
    return m.group(1), float(m.group(2)), float(m.group(3))


def opening_rect(wall, s0, s1, extra=2):
    """Прямоугольник проёма в стене wall на участке s0..s1 (вдоль оси стены)."""
    t = wall["thickness"]
    if is_horizontal(wall):
        y = wall["a"][1]
        return box(s0, y - t / 2 - extra, s1, y + t / 2 + extra)
    x = wall["a"][0]
    return box(x - t / 2 - extra, s0, x + t / 2 + extra, s1)


def opening_span(o):
    sp = parse_span(o.get("span", ""))
    if sp:
        return sp[1], sp[2]
    w = WALLS[o["wall"]]
    base = min(w["a"][0], w["b"][0]) if is_horizontal(w) else min(w["a"][1], w["b"][1])
    return base + o["offset"], base + o["offset"] + o["width"]


EXT_TYPES = ("exterior", "bearing")


def existing_wall_polys():
    """{wall_id: Polygon} — существующие стены (без балконного остекления)."""
    out = {}
    for w in M["walls"]:
        if w["id"].startswith("B"):
            continue
        out[w["id"]] = wall_rect(w["a"], w["b"], w["thickness"])
    for s in M.get("structural", []):
        (x0, y0), (x1, y1) = s["rect"]
        out[s["id"]] = box(x0, y0, x1, y1)
    return out


def glazing_polys():
    return {w["id"]: wall_rect(w["a"], w["b"], w["thickness"]) for w in M["walls"] if w["id"].startswith("B")}


def existing_openings():
    """[(id, wall_id, s0, s1, type)]"""
    res = []
    for o in M["openings"]:
        s0, s1 = opening_span(o)
        res.append((o["id"], o["wall"], s0, s1, o["type"]))
    return res


# демонтаж (planning.demolition): участки стен, пробиваемые под новые двери
def demolition_cuts():
    """[(id, wall_id, s0, s1, text)] — пробивки в стенах по planning.json."""
    cuts = []
    for d in PL["demolition"]:
        m = re.match(r"(W\d+)-cut", d["id"])
        if m:
            sp = parse_span(d["what"])
            if sp:
                cuts.append((d["id"], m.group(1), sp[1], sp[2], d["what"]))
    return cuts


def new_opening_list():
    """Новые проёмы/двери D1..D4, P1 из planning.json + doors.json."""
    res = []
    for o in PL["new_openings"]:
        sp = parse_span(o["span"])
        wall = o["wall"].split("/")[0]
        res.append(dict(o, s0=sp[1], s1=sp[2], wall_id=wall))
    return res


def wall_by_id(wid):
    if wid in WALLS:
        return WALLS[wid]
    if wid in NEW_WALLS:
        return NEW_WALLS[wid]
    raise KeyError(wid)


def d1_infill():
    """Добор ПГП в проёме O8 рядом с дверью D1 (только doors.json: «добор ПГП 199 у y 4621..4820»)."""
    for d in DO["doors"]:
        if d["id"] == "D1":
            m = re.search(r"добор\s+ПГП\s+(\d+)\s+у\s+y\s+(\d+)\.\.(\d+)", d["opening_clear"])
            if m:
                w = WALLS["W7"]
                return opening_rect(w, float(m.group(2)), float(m.group(3)), extra=0)
    return None


def construction_polys():
    """Новые облицовки/короба ВК (plumbing.new_constructions) — rect."""
    out = {}
    for c in VK.get("new_constructions", []):
        (x0, y0), (x1, y1) = c["rect"]
        out[c["id"]] = (box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), c)
    return out


@lru_cache(None)
def final_geometry():
    """Стены после перепланировки (вариант D1).

    Возвращает dict: kept (существующие сохраняемые, по id), new (новые стены по id, с вычетом проёмов),
    openings_final (проёмы: list), demolished (участки демонтажа: list of (id, poly, text)).
    """
    ex = existing_wall_polys()
    ops = existing_openings()
    cuts = demolition_cuts()
    newo = new_opening_list()
    # вычитаем существующие проёмы и пробивки из существующих стен
    holes = {}
    for oid, wid, s0, s1, typ in ops:
        holes.setdefault(wid, []).append(opening_rect(WALLS[wid], s0, s1))
    for cid, wid, s0, s1, _ in cuts:
        holes.setdefault(wid, []).append(opening_rect(WALLS[wid], s0, s1))
    kept = {}
    for wid, poly in ex.items():
        g = poly
        for h in holes.get(wid, []):
            g = g.difference(h)
        kept[wid] = g
    new = {}
    for w in PL["new_walls"]:
        g = wall_rect(w["a"], w["b"], w["thickness"])
        for o in newo:
            if o["wall_id"] == w["id"]:
                g = g.difference(opening_rect(w, o["s0"], o["s1"]))
        new[w["id"]] = g
    inf = d1_infill()
    if inf is not None:
        new["D1-доб"] = inf
    demolished = []
    for cid, wid, s0, s1, text in cuts:
        demolished.append((cid, opening_rect(WALLS[wid], s0, s1, extra=0), text))
    return dict(kept=kept, new=new, demolished=demolished, existing=ex)


@lru_cache(None)
def solid_for_binding():
    """Сплошное тело стен для расчёта привязок: стены D1 + все проёмы заполнены (привязка к граням стен)."""
    g = final_geometry()
    parts = list(g["existing"].values()) + list(g["new"].values())
    parts += [wall_rect(w["a"], w["b"], w["thickness"]) for w in PL["new_walls"]]
    parts += list(glazing_polys().values())
    for cid, (poly, c) in construction_polys().items():
        parts.append(poly)
    return unary_union(parts)


def _wall_name_at(pt):
    """id стены, на грани которой лежит точка pt (с допуском)."""
    p = Point(pt)
    g = final_geometry()
    cands = []
    for cid, (poly, c) in construction_polys().items():
        cands.append((cid, poly))
    for wid, poly in list(g["new"].items()):
        cands.append((wid, poly))
    for w in PL["new_walls"]:
        cands.append((w["id"], wall_rect(w["a"], w["b"], w["thickness"])))
    for wid, poly in g["existing"].items():
        cands.append((wid, poly))
    for wid, poly in glazing_polys().items():
        cands.append((wid, poly))
    best = None
    for wid, poly in cands:
        d = poly.distance(p)
        if d < 3 and (best is None or d < best[1]):
            best = (wid, d)
    return best[0] if best else "?"


def binding(pt, max_len=12000):
    """Привязка точки к граням стен: {'x': (dist, wall, side), 'y': (...)} — до ближайшей грани по X и по Y."""
    solid = solid_for_binding()
    x, y = pt
    p = Point(x, y)
    # если точка на грани или в теле стены — выводим её в помещение на 3 мм
    if solid.distance(p) < 1.0 or solid.contains(p):
        for dx, dy in ((3, 0), (-3, 0), (0, 3), (0, -3), (3, 3), (-3, 3), (3, -3), (-3, -3)):
            q = Point(x + dx * 2, y + dy * 2)
            if not solid.contains(q) and solid.distance(q) > 0.5:
                x, y = x + dx * 2, y + dy * 2
                break
    res = {}
    for axis, dirs in (("x", ((-1, 0), (1, 0))), ("y", ((0, -1), (0, 1)))):
        best = None
        for dx, dy in dirs:
            ray = LineString([(x, y), (x + dx * max_len, y + dy * max_len)])
            inter = ray.intersection(solid)
            if inter.is_empty:
                continue
            d = Point(x, y).distance(inter)
            hit = (x + dx * d, y + dy * d)
            wid = _wall_name_at((hit[0] + dx * 1.5, hit[1] + dy * 1.5))
            # расстояние от исходной точки (не сдвинутой)
            dd = abs((hit[0] - pt[0]) if axis == "x" else (hit[1] - pt[1]))
            cand = (round(dd), wid, ("слева" if dx < 0 else "справа") if axis == "x" else ("снизу" if dy < 0 else "сверху"))
            if best is None or cand[0] < best[0]:
                best = cand
        res[axis] = best
    return res


def binding_text(pt):
    b = binding(pt)
    parts = []
    for ax in ("x", "y"):
        v = b.get(ax)
        if v:
            parts.append(f"{v[0]} от {v[1]}")
    return "; ".join(parts)


# ---------------------------------------------------------------- мебель
def frect(it):
    x, y = it["pos"]
    w, d = it["size"][0], it["size"][1]
    if it.get("rotation", 0) in (90, 270):
        w, d = d, w
    return (x, y, x + w, y + d)


def poly_area_m2(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2e6


def fmt_num(v, nd=2):
    return f"{v:.{nd}f}".replace(".", ",")


def short(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def load_register():
    return json.loads(REGISTER_PATH.read_text(encoding="utf-8"))


def save_register(reg):
    REGISTER_PATH.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@lru_cache(None)
def solid_existing():
    """Тело существующих стен (обмер), проёмы заполнены — для привязок на обмерном плане."""
    parts = list(existing_wall_polys().values()) + list(glazing_polys().values())
    return unary_union(parts)


def binding_existing_text(pt):
    return _binding_text_solid(pt, solid_existing(), existing=True)


def _binding_text_solid(pt, solid, existing=False, max_len=12000):
    x, y = pt
    p = Point(x, y)
    if solid.distance(p) < 1.0 or solid.contains(p):
        for dx, dy in ((3, 0), (-3, 0), (0, 3), (0, -3), (3, 3), (-3, 3), (3, -3), (-3, -3)):
            q = Point(x + dx * 2, y + dy * 2)
            if not solid.contains(q) and solid.distance(q) > 0.5:
                x, y = x + dx * 2, y + dy * 2
                break
    cands = list(existing_wall_polys().items()) + list(glazing_polys().items())
    parts = []
    for axis, dirs in (("x", ((-1, 0), (1, 0))), ("y", ((0, -1), (0, 1)))):
        best = None
        for dx, dy in dirs:
            ray = LineString([(x, y), (x + dx * max_len, y + dy * max_len)])
            inter = ray.intersection(solid)
            if inter.is_empty:
                continue
            d = Point(x, y).distance(inter)
            hit = Point(x + dx * (d + 1.5), y + dy * (d + 1.5))
            wid = "?"
            for cid, poly in cands:
                if poly.distance(hit) < 1:
                    wid = cid
                    break
            dd = abs((x + dx * d - pt[0]) if axis == "x" else (y + dy * d - pt[1]))
            if best is None or dd < best[0]:
                best = (round(dd), wid)
        if best:
            parts.append(f"{best[0]} от {best[1]}")
    return "; ".join(parts)


def wall_normal(pt, tol=60):
    """Единичная нормаль от грани стены в помещение для настенной точки; None — точка не на стене."""
    solid = solid_for_binding()
    p = Point(pt)
    if solid.distance(p) > tol and not solid.contains(p):
        return None
    best = None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        q_in = Point(pt[0] - dx * 55, pt[1] - dy * 55)
        q_out = Point(pt[0] + dx * 60, pt[1] + dy * 60)
        if solid.contains(q_out) or solid.distance(q_out) < 5:
            continue
        score = (1 if (solid.contains(q_in) or solid.distance(q_in) < 1) else 0)
        if best is None or score > best[0]:
            best = (score, (dx, dy))
    return best[1] if best and best[0] > 0 else None
