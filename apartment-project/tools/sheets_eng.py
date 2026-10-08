"""Инженерные листы: ЭО, ЭМ, ВК, ОВ. Подложка — план D1 с мебелью серым."""
from __future__ import annotations

import math

from shapely.geometry import Polygon, box

import model as m
import plan as P
from draw import Sheet, View, text_w
from sheets_ar import plan_layout, main_dims, origin_mark
from sheets_common import Flow, sym_fill, sym_line, sym_circle, sym_text

GCOL = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b", "#e377c2", "#17becf", "#bcbd22",
        "#7f7f7f", "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173", "#3182bd", "#e6550d", "#31a354",
        "#756bb1", "#636363", "#6baed6", "#fd8d3c"]
EL_C = "#b8860b"
SO_C = "#8e44ad"
LV_C = "#1e7d32"
VK_C = {"cold": "#1f6fd6", "hot": "#d62728", "drain": "#6b3d1f"}
OV_C = "#e67e22"


def eng_layout(fmt, side_cols=None):
    return plan_layout(fmt, 50, pad=(550, 700, 650, 850), side_cols=side_cols)


def eng_base(v, furniture=True, occupy_walls=True):
    """Подложка: стены, проёмы, мебель — серым."""
    P.draw_final_walls(v, base=True, occupy=occupy_walls)
    P.draw_windows(v, final=True, base=True)
    P.draw_new_doors(v, col=P.C_BASE)
    P.draw_existing_doors(v, col=P.C_BASE, only=("O5",))
    if furniture:
        P.draw_furniture(v, base=True)


def rooms_small(v, h=1.8):
    for r in m.PL["rooms"]:
        pt = TAG.get(r["id"]) or P.room_point(r["id"])
        q = v.P(pt)
        s = f"{m.ROOM_NO[r['id']]}. {r['name']}"
        v.sh.text(q, s, h, ha="center", va="center", color="#555555", z=6.5, bg="white")
        w = text_w(s, h)
        v.sh.occupy((q[0] - w / 2, q[1] - h, q[0] + w / 2, q[1] + h))


TAG = {"R1": (1690, 7300), "R2": (5900, 7700), "R3": (2900, 2350), "R4": (6200, 2500), "R5": (5800, 4250),
       "R6": (5050, 1500), "R7": (-1480, 1900)}


# ---------------------------------------------------------------- УГО
def _dir(pt):
    n = m.wall_normal(pt)
    return n


def sym_spot(sh, q, col):
    sh.circle(q, 1.0, layer="EL-LIGHT", ec=col, lw=0.25, fc="white", z=6)
    sh.circle(q, 0.35, layer="EL-LIGHT", ec=col, fc=col, lw=0.1, z=6.1)


def sym_ceiling(sh, q, col, pend=False):
    r = 2.0
    sh.circle(q, r, layer="EL-LIGHT", ec=col, lw=0.3, fc="white", z=6)
    d = r * 0.707
    sh.line((q[0] - d, q[1] - d), (q[0] + d, q[1] + d), layer="EL-LIGHT", ec=col, lw=0.2, z=6.1)
    sh.line((q[0] - d, q[1] + d), (q[0] + d, q[1] - d), layer="EL-LIGHT", ec=col, lw=0.2, z=6.1)
    if pend:
        sh.circle(q, 0.6, layer="EL-LIGHT", ec=col, fc=col, lw=0.1, z=6.2)


def sym_half(sh, q, n, col, r=1.6, fill=None, layer="EL-LIGHT"):
    """Полукруг плоской стороной к стене; n — нормаль в помещение."""
    if n is None:
        n = (0, 1)
    ang = math.degrees(math.atan2(n[1], n[0]))
    pts = [(q[0] + r * math.cos(math.radians(ang + a)), q[1] + r * math.sin(math.radians(ang + a)))
           for a in range(-90, 91, 15)]
    sh.poly(pts, closed=True, layer=layer, ec=col, lw=0.3, fc=fill or "white", z=6)
    return ang


def sym_socket(sh, q, n, typ, col=SO_C):
    if n is None:
        n = (0, 1)
    fill = col if typ == "IP44" else None
    if typ == "2P+PE×2":
        t = (-n[1], n[0])
        for k in (-1, 1):
            qq = (q[0] + t[0] * 1.5 * k, q[1] + t[1] * 1.5 * k)
            _sock(sh, qq, n, col, fill, pe=True)
    elif typ == "wire_out":
        a = (q[0] + n[0] * 2.4, q[1] + n[1] * 2.4)
        t = (-n[1] * 1.1, n[0] * 1.1)
        sh.poly([a, (q[0] + t[0], q[1] + t[1]), (q[0] - t[0], q[1] - t[1])], layer="EL-SOCKET", ec=col, fc=col,
                lw=0.2, z=6)
    else:
        _sock(sh, q, n, col, fill, pe=typ != "USB")
        if typ == "USB":
            sh.text((q[0] + n[0] * 0.6, q[1] + n[1] * 0.6 - 0.5), "U", 1.0, ha="center", color=col, z=6.3)


def _sock(sh, q, n, col, fill, pe=True, r=1.3):
    ang = sym_half(sh, q, n, col, r=r, fill=fill, layer="EL-SOCKET")
    tip = (q[0] + n[0] * r, q[1] + n[1] * r)
    sh.line(tip, (tip[0] + n[0] * 1.0, tip[1] + n[1] * 1.0), layer="EL-SOCKET", ec=col, lw=0.3, z=6.1)
    if pe:
        t = (-n[1] * 0.9, n[0] * 0.9)
        e = (tip[0] + n[0] * 1.0, tip[1] + n[1] * 1.0)
        sh.line((e[0] - t[0], e[1] - t[1]), (e[0] + t[0], e[1] + t[1]), layer="EL-SOCKET", ec=col, lw=0.3, z=6.1)


def sym_switch(sh, q, n, typ, col=EL_C):
    if n is None:
        n = (0, 1)
    sh.circle(q, 0.9, layer="EL-LIGHT", ec=col, fc=col, lw=0.2, z=6)
    ang = math.atan2(n[1], n[0]) + math.radians(45)
    d = (math.cos(ang), math.sin(ang))
    e = (q[0] + d[0] * 3.2, q[1] + d[1] * 3.2)
    sh.line(q, e, layer="EL-LIGHT", ec=col, lw=0.3, z=6)
    t = (d[1], -d[0])
    nt = {"1kl": 1, "2kl": 2, "pass": 1, "cross": 1, "dimmer": 1}.get(typ, 1)
    for i in range(nt):
        b = (e[0] - d[0] * i * 0.9, e[1] - d[1] * i * 0.9)
        sh.line(b, (b[0] + t[0] * 1.0, b[1] + t[1] * 1.0), layer="EL-LIGHT", ec=col, lw=0.3, z=6)
    if typ in ("pass", "cross"):
        e2 = (q[0] - d[0] * 3.2, q[1] - d[1] * 3.2)
        sh.line(q, e2, layer="EL-LIGHT", ec=col, lw=0.3, z=6)
        sh.line(e2, (e2[0] - t[0], e2[1] - t[1]), layer="EL-LIGHT", ec=col, lw=0.3, z=6)
    if typ == "cross":
        a2 = ang + math.radians(90)
        d2 = (math.cos(a2) * 2.4, math.sin(a2) * 2.4)
        sh.line((q[0] - d2[0], q[1] - d2[1]), (q[0] + d2[0], q[1] + d2[1]), layer="EL-LIGHT", ec=col, lw=0.25, z=6)
    if typ == "dimmer":
        sh.poly([(q[0] - 1.6, q[1] - 1.6), (q[0] + 1.6, q[1] - 1.6), (q[0] + 1.6, q[1] - 0.6)], closed=True,
                layer="EL-LIGHT", ec=col, fc=col, lw=0.1, z=6)


LV_ABBR = {"RJ45": "LAN", "TV_coax": "TV", "conduit": "Гф", "AV_conduit": "AV", "speaker": "АС",
           "trigger_zigbee": "Тр", "zigbee": "Zb", "AP_PoE": "AP", "leak_sensor": "ДП", "valve": "КЭ",
           "intercom": "Дф", "zigbee_gateway": "ШЛ", "motion_sensor": "ДД", "floor_sensor": "ДТ",
           "provider_input": "Вв", "lowcurrent_panel": "СС"}


def sym_box(sh, q, s, col, h=1.3):
    w = text_w(s, h) + 1.0
    sh.rect(q[0] - w / 2, q[1] - h / 2 - 0.6, q[0] + w / 2, q[1] + h / 2 + 0.6, layer="EL-LOW", ec=col, lw=0.25,
            fc="white", z=6)
    sh.text((q[0], q[1] - h / 2), s, h, ha="center", color=col, z=6.2, layer="EL-LOW")
    return (q[0] - w / 2, q[1] - h / 2 - 0.6, q[0] + w / 2, q[1] + h / 2 + 0.6)


def _occ_sym(sh, q, r=1.8):
    sh.occupy((q[0] - r, q[1] - r, q[0] + r, q[1] + r))


def _hstr(pt_room, h):
    if h is None:
        return ""
    return f"h{int(h)}" + ("*" if pt_room == "R5" else "")


NOTE_R5 = "* В ванной R5 высоты — от чистого пола ванной (+80 к УЧП квартиры)."
NOTE_H = "Высоты h — до центра изделия от УЧП ±0.000; привязки — до грани ближайшей стены по X и по Y, мм."


# ---------------------------------------------------------------- ЭО-01 Освещение
def eo01(ctx, fmt="A2"):
    sh, v, fl = eng_layout(fmt, side_cols=2)
    eng_base(v)
    rooms_small(v)
    groups = {g["id"]: g for g in m.EL["light_groups"]}
    gidx = {gid: i for i, gid in enumerate(groups)}
    # связи группы — тонкой линией по ближайшему соседу
    by = {}
    for l in m.EL["lights"]:
        by.setdefault(l["group"], []).append(l)
    for gid, ls in by.items():
        col = GCOL[gidx[gid] % len(GCOL)]
        pts = [tuple(l["pos"]) for l in ls if l["type"] in ("spot", "ceiling", "pendant", "wall")]
        if len(pts) > 1:
            rest = pts[1:]
            cur = pts[0]
            chain = [cur]
            while rest:
                nxt = min(rest, key=lambda p: (p[0] - cur[0]) ** 2 + (p[1] - cur[1]) ** 2)
                rest.remove(nxt)
                chain.append(nxt)
                cur = nxt
            v.poly(chain, closed=False, layer="EL-LIGHT", ec=col, lw=0.13, ls="dashed", z=5)
    for l in m.EL["lights"]:
        col = GCOL[gidx[l["group"]] % len(GCOL)]
        q = v.P(l["pos"])
        if l["type"] == "spot":
            sym_spot(sh, q, col)
        elif l["type"] in ("ceiling", "pendant"):
            sym_ceiling(sh, q, col, pend=l["type"] == "pendant")
        elif l["type"] == "wall":
            sym_half(sh, q, m.wall_normal(l["pos"]), col, r=1.6, fill=col)
        elif l["type"] == "led_strip":
            e = l.get("end") or l["pos"]
            v.line(l["pos"], e, layer="EL-LIGHT", ec=col, lw=0.7, ls="dashed", z=5.5)
        _occ_sym(sh, q, 2.0)
    for l in m.EL["lights"]:
        col = GCOL[gidx[l["group"]] % len(GCOL)]
        pos = l["pos"]
        if l["type"] == "led_strip" and l.get("end"):
            pos = ((l["pos"][0] + l["end"][0]) / 2, (l["pos"][1] + l["end"][1]) / 2)
        v.label(pos, l["id"], 1.5, color=col, radius=(2.5, 4.5, 7, 10, 14, 19), lcolor=col)
    main_dims(v, h=1.6)
    fl.legend([
        (lambda s, x, y: sym_spot(s, (x + 5, y), "black"), "Светильник встраиваемый точечный (спот)"),
        (lambda s, x, y: sym_ceiling(s, (x + 5, y), "black"), "Светильник потолочный (люстра, плафон)"),
        (lambda s, x, y: sym_ceiling(s, (x + 5, y), "black", pend=True), "Светильник подвесной"),
        (lambda s, x, y: sym_half(s, (x + 5, y - 0.8), (0, 1), "black", fill="black"), "Светильник настенный (бра)"),
        (sym_line("black", "dashed", 0.7), "Светодиодная лента (начало–конец по electrical.json)"),
        (sym_line("black", "dashed", 0.13), "Связь светильников одной группы управления"),
    ], title="Условные обозначения (ГОСТ 21.614, ГОСТ 21.607)", h=1.6)
    rows = [[g["id"], g["name"], g["circuit"], g["power_w"]] for g in m.EL["light_groups"]]
    fills = {i: None for i in range(len(rows))}
    fl.table([10, 62, 12, 12], rows, header=["Группа", "Назначение", "Линия", "P, Вт"], h=1.5,
             title="Группы освещения")
    rows = []
    for l in m.EL["lights"]:
        b = m.binding_text(l["pos"]) if l["type"] != "led_strip" else (
            f"{int(l['pos'][0])},{int(l['pos'][1])} → {int(l['end'][0])},{int(l['end'][1])}" if l.get("end") else "")
        rows.append([l["id"], l["room"], l["type"], l["power_w"], _hstr(l["room"], l["height"])[1:], l["ip"],
                     l["cct_k"], b, m.short(l.get("note", ""), 120)])
    fl.split_table([11, 7, 13, 8, 9, 9, 9, 34, 60], rows,
                   header=["Марка", "Пом.", "Тип", "P,Вт", "h", "IP", "K", "Привязка, мм", "Примечание"], h=1.35,
                   title="Ведомость светильников", max_lines=3)
    fl.text(NOTE_H + "\n" + NOTE_R5 + "\n" + m.EL["accepted"]["routing"], h=1.4, title="Примечания", title_h=2.2)
    return sh


# ---------------------------------------------------------------- ЭО-02 Выключатели
def eo02(ctx, fmt="A3"):
    sh, v, fl = eng_layout(fmt, side_cols=1 if fmt == "A3" else 2)
    eng_base(v)
    rooms_small(v)
    groups = {g["id"]: g for g in m.EL["light_groups"]}
    gidx = {gid: i for i, gid in enumerate(groups)}
    lights_by = {}
    for l in m.EL["lights"]:
        lights_by.setdefault(l["group"], []).append(l)
    for l in m.EL["lights"]:
        q = v.P(l["pos"])
        col = "#9a9a9a"
        if l["type"] == "spot":
            sym_spot(sh, q, col)
        elif l["type"] in ("ceiling", "pendant"):
            sym_ceiling(sh, q, col, pend=l["type"] == "pendant")
        elif l["type"] == "wall":
            sym_half(sh, q, m.wall_normal(l["pos"]), col, r=1.6, fill=col)
        elif l["type"] == "led_strip":
            v.line(l["pos"], l.get("end") or l["pos"], layer="EL-LIGHT", ec=col, lw=0.6, ls="dashed", z=5)
    for s in m.EL["switches"]:
        for gg in s["controls"]:
            for gid in gg.split("+"):
                ls = lights_by.get(gid, [])
                if not ls:
                    continue
                col = GCOL[gidx[gid] % len(GCOL)]
                tgt = min(ls, key=lambda l: (l["pos"][0] - s["pos"][0]) ** 2 + (l["pos"][1] - s["pos"][1]) ** 2)
                tp = tgt["pos"] if tgt["type"] != "led_strip" else tgt["pos"]
                v.line(s["pos"], tp, layer="EL-LIGHT", ec=col, lw=0.18, ls="dashed", z=5.2)
    for s in m.EL["switches"]:
        q = v.P(s["pos"])
        sym_switch(sh, q, m.wall_normal(s["pos"]), s["type"])
        _occ_sym(sh, q, 2.2)
    for s in m.EL["switches"]:
        v.label(s["pos"], f"{s['id']} h{s['height']}\n→{','.join(s['controls'])}", 1.45, color=EL_C,
                radius=(3, 5, 8, 11, 15, 20), lcolor=EL_C)
    for l in m.EL["lights"]:
        if l["id"].endswith("-1"):
            col = GCOL[gidx[l["group"]] % len(GCOL)]
            pos = l["pos"]
            if l["type"] == "led_strip" and l.get("end"):
                pos = ((l["pos"][0] + l["end"][0]) / 2, (l["pos"][1] + l["end"][1]) / 2)
            v.label(pos, l["group"], 1.4, color=col, radius=(2.5, 4.5, 7, 10), lcolor=col)
    main_dims(v, h=1.6)
    fl.legend([
        (lambda s, x, y: sym_switch(s, (x + 4, y - 1), (0, 1), "1kl"), "Выключатель одноклавишный, скрытой установки"),
        (lambda s, x, y: sym_switch(s, (x + 4, y - 1), (0, 1), "2kl"), "Выключатель двухклавишный"),
        (lambda s, x, y: sym_switch(s, (x + 5, y), (0, 1), "pass"), "Выключатель проходной"),
        (lambda s, x, y: sym_switch(s, (x + 5, y), (0, 1), "cross"), "Выключатель перекрёстный"),
        (lambda s, x, y: sym_switch(s, (x + 4, y), (0, 1), "dimmer"), "Светорегулятор (диммер, Zigbee)"),
        (sym_line("black", "dashed", 0.18), "Связь выключателя с группой (цвет — группа)"),
    ], title="Условные обозначения (ГОСТ 21.614)", h=1.6)
    rows = []
    for s in m.EL["switches"]:
        names = "; ".join(f"{g}: " + " + ".join(groups[x]["name"] for x in g.split("+") if x in groups)
                          for g in s["controls"])
        rows.append([s["id"], s["room"], s["type"], s["height"], names, s["wall"], m.binding_text(s["pos"]),
                     m.short(s.get("note", ""), 90)])
    fl.split_table([8, 7, 10, 8, 36, 22, 26, 30], rows,
                   header=["Марка", "Пом.", "Тип", "h", "Управляет", "Стена", "Привязка, мм", "Примечание"],
                   h=1.3, title="Ведомость выключателей", max_lines=4)
    sc = "\n".join(f"{k}: {v_}" for k, v_ in m.EL["scenes"].items())
    fl.text(m.EL["accepted"]["lighting_control"] + "\nСцены:\n" + sc + "\n" + NOTE_H, h=1.35, title="Управление",
            title_h=2.2)
    return sh


# ---------------------------------------------------------------- ЭМ-01 Розетки
def em01(ctx, fmt="A2"):
    sh, v, fl = eng_layout(fmt, side_cols=2)
    eng_base(v)
    rooms_small(v)
    for u in ("U15",):
        x, y = m.UT[u]["pos"]
        v.rect(x - 110, y - 155, x, y + 155, layer="EL-SOCKET", ec=SO_C, fc=SO_C, lw=0.3, z=5)
        v.label((x - 55, y), "ЭЩ U15", 1.6, color=SO_C, radius=(4, 7, 10), lcolor=SO_C)
    pts = []
    for s in m.EL["sockets"]:
        q = v.P(s["pos"])
        n = m.wall_normal(s["pos"])
        sym_socket(sh, q, n, s["type"])
        _occ_sym(sh, q, 2.0)
        pts.append(s)
    for s in pts:
        v.label(s["pos"], f"{s['id'][2:]} {_hstr(s['room'], s['height'])}", 1.4, color=SO_C,
                radius=(3, 5, 7.5, 10, 13, 17, 22), lcolor=SO_C)
    main_dims(v, h=1.6)
    fl.legend([
        (lambda s, x, y: _sock(s, (x + 4, y - 0.8), (0, 1), SO_C, None), "Розетка 2П+З 16 А, скрытой установки"),
        (lambda s, x, y: sym_socket(s, (x + 4, y - 0.8), (0, 1), "2P+PE×2"), "Розетка двойная 2П+З"),
        (lambda s, x, y: _sock(s, (x + 4, y - 0.8), (0, 1), SO_C, SO_C), "Розетка 2П+З IP44 с крышкой"),
        (lambda s, x, y: sym_socket(s, (x + 4, y - 0.8), (0, 1), "USB"), "Розетка 2П+З с USB-A/C"),
        (lambda s, x, y: sym_socket(s, (x + 4, y - 0.8), (0, 1), "wire_out"), "Вывод кабеля (клеммная коробка/БП/оборудование)"),
        (sym_fill(SO_C, SO_C), "Щит квартирный ЭЩ U15 (ЩРН-48)"),
    ], title="Условные обозначения (ГОСТ 21.614)", h=1.6)
    fl.text("Марка на плане — без префикса «P-»; hNNN — высота центра от УЧП.\n" + NOTE_R5, h=1.4)
    rows = []
    for s in m.EL["sockets"]:
        kw = s.get("power_kw")
        rows.append([s["id"], s["room"], s["type"], s["height"], s["circuit"], kw if kw is not None else "",
                     s.get("ip", ""), s["wall"], m.binding_text(s["pos"]), m.short(s.get("note", ""), 90)])
    fl.split_table([11, 7, 13, 8, 8, 8, 8, 30, 26, 47], rows,
                   header=["Марка", "Пом.", "Тип", "h", "Линия", "кВт", "IP", "Стена / место", "Привязка, мм",
                           "Назначение"], h=1.3, title="Ведомость розеток и силовых выводов", max_lines=3)
    fl.text(m.EL["accepted"]["routing"] + "\n" + m.EL["accepted"]["bath_zones"] + "\n" + NOTE_H, h=1.35,
            title="Примечания", title_h=2.2)
    return sh


# ---------------------------------------------------------------- ЭМ-02 Слаботочка
def em02(ctx, fmt="A2"):
    sh, v, fl = eng_layout(fmt, side_cols=2)
    eng_base(v)
    rooms_small(v)
    nopos = []
    for lv in m.EL["low_voltage"]:
        if lv["pos"] == [0, 0] or lv["room"] == "—":
            nopos.append(lv)
            continue
        q = v.P(lv["pos"])
        bb = sym_box(sh, q, LV_ABBR.get(lv["kind"], lv["kind"][:2]), LV_C)
        sh.occupy(bb)
    for t in m.EL["floor_heating"]["thermostats"]:
        q = v.P(t["pos"])
        bb = sym_box(sh, (q[0], q[1] - 3.2), "Т", "#c0392b")
        sh.occupy(bb)
    for lv in m.EL["low_voltage"]:
        if lv in nopos:
            continue
        v.label(lv["pos"], f"{lv['id']} h{lv['height']}", 1.4, color=LV_C, radius=(3.5, 6, 9, 12, 16, 21),
                lcolor=LV_C)
    # трасса EV-кранов и датчиков — схематично к U16
    u16 = m.UT["U16"]["pos"]
    for lv in m.EL["low_voltage"]:
        if lv["kind"] in ("leak_sensor", "valve") and lv not in nopos:
            v.poly([lv["pos"], (lv["pos"][0], 6000 if lv["pos"][1] > 3700 else 2300), (u16[0] - 200,
                    6000 if lv["pos"][1] > 3700 else 2300), (u16[0] - 200, u16[1])], closed=False, layer="EL-LOW",
                   ec="#7fbf7f", lw=0.13, ls="dotted", z=4.5)
    main_dims(v, h=1.6)
    leg = [(sym_text(a, 1.3, LV_C), k) for k, a in [
        ("Розетка RJ45 (Cat6)", "LAN"), ("ТВ-розетка (RG-6)", "TV"), ("Гофра HDMI/AV", "AV"),
        ("Акустика", "АС"), ("Точка доступа Wi-Fi PoE", "AP"), ("Датчик протечки", "ДП"),
        ("Кран с электроприводом (EV)", "КЭ"), ("Датчик движения", "ДД"), ("Датчик температуры пола", "ДТ"),
        ("Шлюз Zigbee / СС-щит / ввод", "ШЛ"), ("Домофон", "Дф"), ("Триггер/модуль Zigbee", "Тр")]]
    leg.append((sym_text("Т", 1.3, "#c0392b"), "Терморегулятор электро-ТП (ОВ-01)"))
    leg.append((sym_line("#7fbf7f", "dotted", 0.2), "Линии датчиков/кранов к контроллеру в U16 (схематично)"))
    fl.legend(leg, title="Условные обозначения", h=1.5)
    rows = []
    for lv in m.EL["low_voltage"]:
        b = m.binding_text(lv["pos"]) if lv not in nopos else "без привязки"
        rows.append([lv["id"], lv["room"], lv["kind"], lv["height"], lv.get("from", ""), m.short(lv["cable"], 70), b,
                     m.short(lv.get("note", ""), 90)])
    fl.split_table([10, 7, 18, 8, 12, 34, 24, 45], rows,
                   header=["Марка", "Пом.", "Вид", "h", "От", "Кабель", "Привязка, мм", "Примечание"], h=1.3,
                   title="Ведомость слаботочных точек и умного дома", max_lines=3)
    p = m.PN["lowcurrent_panel"]
    fl.text(f"СС-щит {p['id']}: {p['location']}; питание {p['power']}; состав: {p['content']}.\n"
            "Логика защиты от протечек: " + m.VK["leak_protection"]["logic"] + "\n" + NOTE_H + "\n" + NOTE_R5,
            h=1.35, title="Примечания", title_h=2.2)
    return sh


# ---------------------------------------------------------------- ЭМ-03 Однолинейная схема
def em03(ctx, fmt="A2"):
    sh = Sheet(fmt, 1)
    W, H = sh.W, sh.H
    pn = m.PN
    groups = [g for g in pn["groups"]]
    x0, x1 = 40, W - 20
    ybus = H - 70
    # ввод
    sh.text((26, H - 14), f"Щит {pn['panel']['id']}: {pn['panel']['enclosure']}", 2.5, bold=True)
    sh.text((26, H - 19), f"Место: {pn['panel']['location']}", 1.8)
    sh.text((26, H - 23), "Ввод: " + pn["input"]["supply_cable"] + "; " + pn["input"]["allocated_power_kw"] + "; "
            + pn["input"]["metering"], 1.8)
    xin = 30
    y = H - 30
    sh.line((xin, y), (xin, ybus), lw=0.5)
    for d in pn["input"]["devices"]:
        sh.rect(xin - 2.5, y - 6, xin + 2.5, y - 1, lw=0.35, fc="white", z=5)
        sh.text((xin + 4, y - 4.5), f"{d['pos']} — {m.short(d['item'], 120)}", 1.6)
        y -= 7
    ybus = min(ybus, y - 4)
    sh.line((xin, ybus), (x1, ybus), lw=0.9)
    sh.text((xin + 3, ybus + 1.2), "Шины L / N / PE (раздельные N и PE, " + pn["panel"]["earthing"] + ")", 1.6)
    n = len(groups)
    step = (x1 - x0 - 10) / n
    ytop = ybus
    for i, g in enumerate(groups):
        x = x0 + 10 + i * step + step / 2
        sh.line((x, ytop), (x, ytop - 34), lw=0.35)
        # аппарат: автомат — крест на линии, АВДТ — прямоугольник
        if "АВДТ" in g["device"]:
            sh.rect(x - 2.6, ytop - 16, x + 2.6, ytop - 6, lw=0.35, fc="white", z=5)
            sh.text((x, ytop - 12), "АВДТ", 1.2, ha="center", z=6)
            sh.text((x, ytop - 14.6), g["rcd"].split(",")[0], 1.1, ha="center", z=6)
        elif g["breaker"] != "—":
            sh.line((x - 1.4, ytop - 10), (x + 1.4, ytop - 7.2), lw=0.35)
            sh.line((x - 1.4, ytop - 7.2), (x + 1.4, ytop - 10), lw=0.35)
        sh.text((x, ytop - 5), g["breaker"], 1.3, ha="center", bg="white")
        sh.circle((x, ytop - 34), 0.6, fc="black", ec="black")
        sh.text((x, ytop - 37), g["id"], 2.0, ha="center", va="top", bold=True)
        txt = f"{g['cable']}, {g.get('length_m', 0)} м | {g.get('p_inst_kw', 0)} кВт | {m.short(g['name'], 70)}"
        sh.text((x + 0.8, ytop - 41), txt, 1.4, rot=-90, ha="left", va="center")
    ytab = ytop - 41 - 75
    fl = Flow(sh, [(22, W - 7, ytab, 8)] if False else [(22, W - 5 - 185 - 4, ytab, 8), (W - 5 - 185, W - 7, ytab, 63)])
    rows = []
    for g in groups:
        rows.append([g["id"], m.short(g["name"], 80), g["breaker"], g["device"], g["rcd"], g["cable"],
                     g.get("length_m", ""), g.get("points", ""), g.get("p_inst_kw", ""), g.get("kc", ""),
                     g.get("p_calc_kw", "")])
    cols = [9, 70, 14, 34, 28, 24, 10, 9, 11, 8, 11]
    fl.split_table(cols, rows, header=["Гр.", "Назначение", "Аппарат", "Тип", "УЗО", "Кабель", "L, м", "Точ.",
                                       "Pу, кВт", "Кс", "Pр, кВт"], h=1.4, title="Таблица групп (panel.json)",
                   max_lines=2)
    t = pn["totals"]
    fl.text(f"Групп: {t['groups_count']}; Pуст = {t['p_installed_kw']} кВт; ΣPу·Кс = {t['p_sum_kc_kw']} кВт; "
            f"Ко = {t['k_simultaneity_groups']}; Pр = {t['p_calc_kw']} кВт; Iр = {t['i_calc_a']} А; cos φ = "
            f"{t['cos_phi']}.\n{t['check_allocated']}\n" + "\n".join("— " + r for r in pn["rcd_policy"]),
            h=1.4, title="Расчётная нагрузка и защита", title_h=2.2)
    sh.meta = {"scale": "—"}
    return sh


# ---------------------------------------------------------------- ВК
def vk_points(v, sh, h=1.4, labels=True, radius=(3, 5, 7.5, 10, 13, 17)):
    for f in m.VK["fixtures"]:
        for kind in ("cold", "hot", "drain"):
            o = f.get(kind)
            if not o or not o.get("pos"):
                continue
            q = v.P(o["pos"])
            col = VK_C[kind]
            if kind == "drain":
                sh.circle(q, 1.1, layer="VK", ec=col, fc="white", lw=0.35, z=6.4)
                sh.circle(q, 0.45, layer="VK", ec=col, fc=col, lw=0.1, z=6.5)
            else:
                sh.circle(q, 0.85, layer="VK", ec=col, fc=col if kind == "hot" else "white", lw=0.35, z=6.6)
            _occ_sym(sh, q, 1.3)
    if labels:
        for f in m.VK["fixtures"]:
            for kind, ab in (("cold", "В1"), ("hot", "Т3"), ("drain", "К1")):
                o = f.get(kind)
                if not o or not o.get("pos"):
                    continue
                hh = o.get("h")
                s = f"{f['id']} {ab} " + (f"h{hh:g}" if hh is not None else "загл.")
                if f["room"] == "R5" and hh is not None:
                    s += "*"
                v.label(o["pos"], s, h, color=VK_C[kind], radius=radius, lcolor=VK_C[kind])


def vk_pipes(v, sh, slope_labels=True, h=1.4):
    for wln in m.VK["pipes"]["water"]:
        pts = wln["path"]
        sysn = wln["sys"]
        if "ГВС" in sysn:
            v.poly(pts, closed=False, layer="VK", ec=VK_C["cold"], lw=0.3, z=5.5)
            v.poly([(x + 25, y + 25) for x, y in pts], closed=False, layer="VK", ec=VK_C["hot"], lw=0.3, z=5.5)
        else:
            v.poly(pts, closed=False, layer="VK", ec=VK_C["cold"], lw=0.3, z=5.5)
    for s in m.VK["pipes"]["sewer"]:
        v.poly(s["path"], closed=False, layer="VK", ec=VK_C["drain"], lw=0.5, ls="dashed", z=5.4)
        if slope_labels:
            pts = s["path"]
            seg = max(range(len(pts) - 1), key=lambda i: abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1]))
            mid = ((pts[seg][0] + pts[seg + 1][0]) / 2, (pts[seg][1] + pts[seg + 1][1]) / 2)
            v.label(mid, f"{s['id']} Ø{s['dn']} i={s['i']}", h, color=VK_C["drain"], radius=(2.5, 4.5, 7, 10, 14),
                    lcolor=VK_C["drain"])


def vk_nodes(v, sh, h=1.5):
    for n in m.VK["nodes"]:
        q = v.P(n["pos"])
        sh.rect(q[0] - 1.6, q[1] - 1.6, q[0] + 1.6, q[1] + 1.6, layer="VK", ec="black", fc="#ffe9a8", lw=0.3, z=6.6)
        v.label(n["pos"], n["id"], h, bold=True, radius=(3, 5, 8))
    for c in m.VK.get("new_constructions", []):
        (x0, y0), (x1, y1) = c["rect"]
        v.label(((x0 + x1) / 2, (y0 + y1) / 2), c["id"], h * 0.9, color=P.C_NEW, radius=(3, 6, 9, 12),
                lcolor=P.C_NEW)
    for s in m.VK["leak_protection"]["sensors"]:
        q = v.P(s["pos"])
        sym_box(sh, q, "ДП", LV_C, h=1.1)


def vk01(ctx, fmt="A2"):
    sh, v, fl = eng_layout(fmt, side_cols=2)
    eng_base(v)
    P.draw_utilities(v, labels=False)
    rooms_small(v)
    vk_pipes(v, sh, slope_labels=False)
    vk_points(v, sh, h=1.35, labels=False)
    vk_nodes(v, sh)
    for f in m.VK["fixtures"]:
        pts = [f[k]["pos"] for k in ("cold", "hot", "drain") if f.get(k) and f[k].get("pos")]
        if pts:
            c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            v.label(c, f["id"], 1.6, bold=True, radius=(4, 7, 10, 14, 19))
    main_dims(v, h=1.6)
    fl.legend([
        (sym_circle(VK_C["cold"], "white", r=0.85), "Вывод ХВС (В1)"),
        (sym_circle(VK_C["hot"], VK_C["hot"], r=0.85), "Вывод ГВС (Т3)"),
        (sym_circle(VK_C["drain"], "white", r=1.1, inner=VK_C["drain"]), "Выпуск канализации (К1)"),
        (sym_line(VK_C["cold"], "solid", 0.3), "Трубопровод ХВС PEX-a"),
        (sym_line(VK_C["hot"], "solid", 0.3), "Трубопровод ГВС PEX-a (в изоляции)"),
        (sym_line(VK_C["drain"], "dashed", 0.5), "Канализация ПП (уклоны — ВК-02)"),
        (sym_fill("#ffe9a8", "black"), "Узел ввода N1/N2 (краны, фильтры-редукторы, счётчики, EV)"),
        (sym_text("ДП", 1.1, LV_C), "Датчик протечки"),
        (sym_circle("#6b3d1f", "white", inner="#6b3d1f"), "Стояк К1 (существующий)"),
        (sym_circle("#1f6fd6", "white"), "Стояк водоснабжения (существующий)"),
    ], title="Условные обозначения", h=1.5)
    rows = []
    for f in m.VK["fixtures"]:
        for kind, ab in (("cold", "В1"), ("hot", "Т3"), ("drain", "К1")):
            o = f.get(kind)
            if not o:
                continue
            hh = o.get("h")
            z = o.get("z")
            rows.append([f["id"], f["room"], m.short(f["name"], 60), ab, str(o.get("dn", "")),
                         "" if hh is None else f"{hh:g}", "" if z is None else f"{z:g}",
                         m.binding_text(o["pos"]) if o.get("pos") else "", m.short(o.get("note", ""), 80)])
    fl.split_table([9, 7, 44, 8, 13, 9, 9, 28, 44], rows,
                   header=["Прибор", "Пом.", "Наименование", "Сист.", "DN", "h", "z абс.", "Привязка, мм",
                           "Примечание"], h=1.3, title="Ведомость выводов водопровода и канализации", max_lines=3)
    rows = [[h_["id"], h_["where"], h_["size"], h_["h"], h_["access"]] for h_ in m.VK["hatches"]]
    fl.table([8, 40, 14, 20, 38], rows, header=["Люк", "Где", "Размер", "Отметки", "Доступ"], h=1.3,
             title="Люки и ревизии", max_lines=4)
    fl.text(m.VK["datum"]["zero"] + "\n" + m.VK["datum"]["bath_floor"] + "\n" + m.VK["pipes"]["water_material"] +
            "\n" + "\n".join("— " + x for x in m.VK["works_uk"]), h=1.35, title="Примечания", title_h=2.2)
    return sh


def vk02(ctx, fmt="A3"):
    sh = Sheet(fmt, 25)
    W, H = sh.W, sh.H
    frags = [("Фрагмент 1. Ванная R5 (1:25)", (4750, 3650, 7700, 6000)),
             ("Фрагмент 2. Постирочная R6 и мойка кухни (1:25)", (2150, -150, 6000, 2100))]
    y = H - 8
    views = []
    for title, bb in frags:
        hh = (bb[3] - bb[1]) / 25
        sh.text((24, y - 3), title, 2.5, bold=True)
        v = View(sh, 25, (bb[0], bb[1]), (24, y - 6 - hh))
        views.append((v, bb))
        y -= hh + 12
    for v, bb in views:
        clip = box(*bb)
        g = m.final_geometry()
        for wid, poly in list(g["kept"].items()) + list(g["new"].items()):
            pp = poly.intersection(clip)
            if not pp.is_empty:
                v.shape(pp, layer="AR-WALLS", fc=P.C_BASE, ec="#7f7f7f", lw=0.18, z=3)
                for gg in getattr(v.geom(pp), "geoms", [v.geom(pp)]):
                    if not gg.is_empty:
                        sh.occupy(gg.bounds)
        for cid, (poly, c) in m.construction_polys().items():
            pp = poly.intersection(clip)
            if not pp.is_empty:
                v.shape(pp, layer="AR-NEW", fc="white", hatch="....", hc=P.C_NEW, ec=P.C_NEW, lw=0.2, z=3.1)
        for it in m.FU["items"]:
            x0, y0, x1, y1 = m.frect(it)
            r = box(x0, y0, x1, y1).intersection(clip)
            if not r.is_empty and r.area > 0:
                v.shape(r, layer="FURN", ec=P.C_BASE_F, lw=0.13, ls="dashed" if it.get("layer") == "wall" else "solid",
                        z=2.5)
        for u in m.M["utilities"]:
            pass
        P.draw_utilities(v, labels=False)
        vk_pipes(v, sh, slope_labels=True, h=1.6)
        vk_points(v, sh, h=1.5, radius=(3, 5, 7.5, 10, 13, 17, 22))
        vk_nodes(v, sh, h=1.6)
        # рамка фрагмента
        p0, p1 = v.P((bb[0], bb[1])), v.P((bb[2], bb[3]))
        sh.rect(p0[0], p0[1], p1[0], p1[1], lw=0.13, ec="#999999", ls="dashdot", z=1)
    fx0 = max(v.P((bb[2], bb[3]))[0] for v, bb in views) + 6
    fl = Flow(sh, [(fx0, W - 7, H - 8, 63)])
    rows = []
    for s in m.VK["pipes"]["sewer"]:
        rows.append([s["id"], m.short(s["fixture"], 60), s["riser"], s["dn"], s["i"], s["L"], s["drop"], s["z_start"],
                     s["z_end"], "да" if s["ok"] else "НЕТ"])
    fl.table([8, 46, 9, 8, 9, 9, 9, 11, 10, 8], rows,
             header=["Уч.", "Прибор / трасса", "Стояк", "Ø", "i", "L, м", "Δh", "z нач.", "z кон.", "OK"], h=1.3,
             title="Канализация: уклоны и отметки лотка (мм от УЧП)", max_lines=3)
    fl.text("\n".join("— " + r for r in m.VK["pipes"]["sewer_rules"]) + "\n" + m.VK["summary"]["podium"], h=1.35,
            title="Указания", title_h=2.2)
    sens = m.VK["pipes"]["sewer_calc"]["sensitivity_tee_vs_podium"]
    fl.table([30, 30, 30], [[s["tee_invert"], s["ffl_bath_required"], "да" if s["laundry_kitchen_ok"] else "нет"]
                            for s in sens], header=["Лоток тройника U6", "Пол ванной треб.", "Кухня/постир. OK"],
             h=1.3, title="Чувствительность подиума к отметке врезки")
    fl.text("\n".join("— " + q for q in m.VK["questions"]) + "\n" + NOTE_R5, h=1.3, title="Требует обмера",
            title_h=2.2)
    sh.meta = {"scale": "1:25"}
    return sh


# ---------------------------------------------------------------- ОВ-01 Тёплые полы
def ov01(ctx, fmt="A3"):
    sh, v, fl = eng_layout(fmt, side_cols=1 if fmt == "A3" else 2)
    nofix = []
    for r in m.PL["rooms"]:
        if r["id"] != "R7":
            nofix.append(Polygon(r["polygon"]))
    from shapely.ops import unary_union
    v.shape(unary_union(nofix), layer="OV", fc="#fdecec", hatch="\\\\", hc="#e3a3a3", ec=None, lw=0, z=1)
    eng_base(v, occupy_walls=True)
    rooms_small(v)
    for mt in m.HT["water_ufh"]["manifolds"]:
        (x0, y0), (x1, y1) = mt["rect"]
        v.rect(x0, y0, x1, y1, layer="OV", ec="#2e8b57", fc="#2e8b57", lw=0.3, z=6)
        v.label(((x0 + x1) / 2, (y0 + y1) / 2), f"{mt['id']} коллектор ТП h{mt['h']}", 1.5, color="#2e8b57",
                radius=(4, 7, 10, 14), lcolor="#2e8b57")
    for e in m.HT["electric_ufh"]:
        for rr in e["rects_accepted"]:
            v.rect(rr[0], rr[1], rr[2], rr[3], layer="OV", ec="#d35400", fc="#fbd7b5", hatch="||", hc="#d35400",
                   lw=0.3, z=4)
        rr = e["rects_accepted"][0]
        v.label(((rr[0] + rr[2]) / 2, (rr[1] + rr[3]) / 2), f"{e['id']} {e['area_m2']} м² {e['power_w']} Вт",
                1.5, color="#a04000", radius=(0, 4, 7, 10), lcolor="#a04000")
    for t in m.HT["thermostats"]:
        q = v.P(t["pos"])
        sh.occupy(sym_box(sh, q, t["id"], "#c0392b", h=1.4))
        v.label(t["pos"], f"h{t['height']}", 1.4, color="#c0392b", radius=(3.5, 6, 9))
    for c in m.HT["balcony"]["heaters"]["convectors"]:
        x0, y0, x1, y1 = c["rect"]
        v.rect(x0, y0, x1, y1, layer="OV", ec="#c0392b", fc="#f5b7b1", lw=0.3, z=5)
        v.label(((x0 + x1) / 2, (y0 + y1) / 2), f"{c['id']} {c['power_kw']} кВт", 1.5, color="#c0392b",
                radius=(3, 6, 9))
    main_dims(v, h=1.6)
    fl.legend([
        (sym_fill("#fdecec", None, hatch="\\\\", hc="#e3a3a3", lw=0), "Водяной ТП застройщика в стяжке — КРЕПИТЬ В ПОЛ, ШТРОБИТЬ, СВЕРЛИТЬ ЗАПРЕЩЕНО (D3); схема контуров неизвестна"),
        (sym_fill("#2e8b57", "#2e8b57"), "Коллектор водяного ТП (доступ сохранить)"),
        (sym_fill("#fbd7b5", "#d35400", hatch="||", hc="#d35400"), "Электрический ТП — мат в клее/смеси (зона укладки)"),
        (sym_text("T1", 1.4, "#c0392b"), "Терморегулятор с датчиком пола"),
        (sym_fill("#f5b7b1", "#c0392b"), "Электроконвектор низкий (крепление к стене)"),
    ], h=1.5)
    rows = [[e["id"], e["room"], m.short(e["type"], 60), e["area_m2"], e["power_w"], e.get("thermostat", ""),
             e.get("circuit", "")] for e in m.HT["electric_ufh"]]
    fl.table([9, 8, 52, 11, 12, 10, 10], rows, header=["Марка", "Пом.", "Тип", "S, м²", "P, Вт", "Терм.", "Линия"],
             h=1.35, title="Электрический тёплый пол", max_lines=3)
    rows = [[t["id"], t["room"], t["height"], t["for"], m.binding_text(t["pos"]), t.get("note", "")]
            for t in m.HT["thermostats"]]
    rows += [[c["id"], c["room"], "—", f"{c['power_kw']} кВт, {c['outlet']}/{c['circuit']}", "", m.short(c["note"], 90)]
             for c in m.HT["balcony"]["heaters"]["convectors"]]
    fl.table([9, 8, 8, 25, 28, 34], rows, header=["Марка", "Пом.", "h", "Назначение", "Привязка, мм", "Примечание"],
             h=1.3, title="Терморегуляторы и конвекторы", max_lines=4)
    hl = m.HT["balcony"]["heat_loss"]
    fl.text("Водяной ТП: " + m.HT["water_ufh"]["status"] + "\n" + "\n".join(
        f"{i}. {t}" for i, t in enumerate(m.HT["water_ufh"]["requirements"], 1)) +
        f"\nБалкон: теплопотери {hl['q_design_w']} Вт (−24 °C); установлено {m.HT['balcony']['heaters']['total_installed_w']} Вт. "
        + m.HT["balcony"]["decision"], h=1.3, title="Указания", title_h=2.2)
    return sh


# ---------------------------------------------------------------- ОВ-02 Вентиляция
def ov02(ctx, fmt="A3"):
    sh, v, fl = eng_layout(fmt, side_cols=1 if fmt == "A3" else 2)
    eng_base(v)
    rooms_small(v)
    for b in m.CE["boxes"]:
        if b["id"] in ("CB-1", "CB-2"):
            x0, y0, x1, y1 = b["rect"]
            v.rect(x0, y0, x1, y1, layer="OV", ec="#8a5a2b", lw=0.2, ls="dashed", hatch="\\\\", hc="#d9b48f", z=2.8)
    for u in m.M["utilities"]:
        if u["type"] in ("vent_shaft",):
            (x0, y0), (x1, y1) = u["rect"]
            dashed = u["id"] in ("U25", "U26")
            v.rect(x0, y0, x1, y1, layer="OV", ec=OV_C, lw=0.35, ls="dashed" if dashed else "solid",
                   fc=None if dashed else "white", hatch=None if dashed else "xx", hc=OV_C, z=5)
            v.label(((x0 + x1) / 2, (y0 + y1) / 2), u["id"] + (" [доп.]" if dashed else ""), 1.5, color=OV_C,
                    radius=(4, 7, 10, 14), lcolor=OV_C)
        if u["type"] == "vent_grille":
            v.rect(u["pos"][0] - 40, u["pos"][1] - 50, u["pos"][0] + 40, u["pos"][1] + 50, layer="OV", ec=OV_C,
                   hatch="||", hc=OV_C, lw=0.3, z=5)
    for e in m.HV["exhaust"]:
        pts = e["route"]
        d = 125 if e["id"] == "KH1" else 100
        v.poly(pts, closed=False, layer="OV", ec=OV_C, lw=0.6, z=5.5)
        v.poly(pts, closed=False, layer="OV", ec="white", lw=0.25, z=5.6)
        if e.get("pos"):
            q = v.P(e["pos"])
            sh.circle(q, 2.0, layer="OV", ec=OV_C, fc="white", lw=0.35, z=6)
            for a in (0, 120, 240):
                sh.line(q, (q[0] + 1.6 * math.cos(math.radians(a)), q[1] + 1.6 * math.sin(math.radians(a))),
                        layer="OV", ec=OV_C, lw=0.3, z=6.1)
            _occ_sym(sh, q, 2.2)
        anchor = e.get("pos") or pts[0]
        v.label(anchor, f"{e['id']} Ø{d}" + (f" {e.get('design_m3h', '')} м³/ч" if e.get("design_m3h") else ""), 1.5,
                color="#a04000", radius=(3, 6, 9, 12, 16), lcolor="#a04000")
    for s in m.HV["supply"]:
        q = v.P(s["pos"])
        n = (0, -1) if s["id"].startswith("BR") else (1, 0)
        sh.rect(q[0] - 2, q[1] - 2, q[0] + 2, q[1] + 2, layer="OV", ec="#2471a3", fc="#d6eaf8", lw=0.3, z=6)
        e = (q[0] + n[0] * 6, q[1] + n[1] * 6)
        sh.line(q, e, layer="OV", ec="#2471a3", lw=0.35, z=6)
        sh.poly([e, (e[0] - n[0] * 1.6 - n[1] * 0.8, e[1] - n[1] * 1.6 + n[0] * 0.8),
                 (e[0] - n[0] * 1.6 + n[1] * 0.8, e[1] - n[1] * 1.6 - n[0] * 0.8)], layer="OV", ec="#2471a3",
                fc="#2471a3", lw=0.1, z=6)
        _occ_sym(sh, q, 2.5)
        v.label(s["pos"], f"{s['id']} {s['design_m3h']} м³/ч", 1.5, color="#2471a3", radius=(4, 7, 10, 14),
                lcolor="#2471a3")
    main_dims(v, h=1.6)
    fl.legend([
        (sym_fill("white", OV_C, hatch="xx", hc=OV_C), "Вентканал (существующий)"),
        (sym_fill(None, OV_C, ls="dashed"), "Вентканал в коробе стояков [допущение D10]"),
        (lambda s, x, y: (s.circle((x + 5, y), 2.0, ec=OV_C, fc="white", lw=0.35)), "Вентилятор вытяжной с обратным клапаном"),
        (sym_line(OV_C, "solid", 0.6), "Воздуховод (Ø по подписи)"),
        (sym_fill("#d6eaf8", "#2471a3"), "Бризер / приточный клапан, стрелка — приток"),
        (sym_fill(None, "#8a5a2b", hatch="\\\\", hc="#d9b48f", ls="dashed"), "Короб-опуск потолка под воздуховод"),
    ], h=1.5)
    rows = [[x["room"], x["norm"], x["design_m3h"], x["device"]] for x in m.HV["air_balance"]["supply"]]
    rows += [[x["room"], x.get("norm_m3h", ""), x.get("design_m3h", ""), x["device"]] for x in m.HV["air_balance"]["exhaust"]]
    fl.table([24, 36, 22, 38], rows, header=["Помещение", "Норма", "Расчёт, м³/ч", "Устройство"], h=1.3,
             title="Воздушный баланс", max_lines=4)
    rows = [[e["id"], m.short(e["name"], 60), m.short(e.get("duct", ""), 70), m.short(e.get("connection", e.get("route_desc", "")), 90)]
            for e in m.HV["exhaust"]]
    fl.table([9, 34, 37, 40], rows, header=["Марка", "Оборудование", "Воздуховод", "Подключение"], h=1.3,
             title="Вытяжка", max_lines=5)
    fl.text(m.HV["concept"] + "\nПереток: " + m.HV["air_balance"]["transfer"] + "\nКондиционирование: "
            + m.HV["ac"]["decision"], h=1.3, title="Указания", title_h=2.2)
    return sh


SHEETS = {"ЭО-01": eo01, "ЭО-02": eo02, "ЭМ-01": em01, "ЭМ-02": em02, "ЭМ-03": em03, "ВК-01": vk01, "ВК-02": vk02,
          "ОВ-01": ov01, "ОВ-02": ov02}
