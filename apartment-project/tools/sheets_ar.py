"""Листы АР: обмерный план, планировка, демонтаж, монтаж, мебель, двери, потолки, полы."""
from __future__ import annotations

import re

from shapely.geometry import Polygon, box

import model as m
import plan as P
from draw import Sheet, View, text_w
from sheets_common import Flow, sym_fill, sym_line, sym_circle, sym_text

STAMP_TOP = 60.0


def plan_layout(fmt, scale=50, pad=(300, 300, 300, 300), side_min=110, bbox=P.PLAN_BBOX, side_cols=None,
                below=True):
    """Лист с планом слева-сверху и колонкой(ами) справа. Возвращает (sheet, view, flow)."""
    sh = Sheet(fmt, scale)
    W, H = sh.W, sh.H
    x0, ytop = 22.0, H - 6.0
    v = P.fit_view(sh, scale, x0, 7.0, W - 7, ytop, bbox=bbox, pad=pad)
    px0, py0, px1, py1 = v.extent
    right_x0 = px1 + 4
    width = W - 7 - right_x0
    cols = []
    ncols = side_cols or max(1, int(width // 125))
    cw = (width - (ncols - 1) * 4) / ncols
    for i in range(ncols):
        cx0 = right_x0 + i * (cw + 4)
        cx1 = cx0 + cw
        # нижняя граница: над штампом, если колонка над ним
        yb = STAMP_TOP + 3 if cx1 > W - 5 - 185 else 8.0
        cols.append((cx0, cx1, ytop, yb))
    if below and py0 - 8 > 30:
        cols.append((x0, min(px1, W - 5 - 185 - 4), py0 - 4, 8.0))
    fl = Flow(sh, cols)
    return sh, v, fl


# ---------------------------------------------------------------- АР-01 Обмерный план
def ar01(ctx):
    sh, v, fl = plan_layout("A3", 50, pad=(1350, 780, 800, 1200), side_cols=1)
    P.draw_existing_walls(v)
    P.draw_windows(v, final=False)
    P.draw_existing_doors(v)
    # существующие приборы застройщика — условно, серым пунктиром
    for f in m.M["fixtures"]:
        (x0, y0), (x1, y1) = f["rect"]
        v.rect(x0, y0, x1, y1, layer="FURN", ec="#8a8a8a", lw=0.13, ls="dashed", z=2.5)
    P.draw_utilities(v)
    # помещения (обмер)
    pos = {"R1": (1690, 6000), "R2": (5600, 7500), "R3": (1800, 2300), "R4": (6200, 2950), "R5": (6000, 5250),
           "R6": (5200, 1300), "R7": (-1480, 1600)}
    for r in m.M["rooms"]:
        nm = re.sub(r"\s*[\d,]+.*$", "", r["name"]).strip() or r["name"]
        P.room_tag(v, r["id"], nm, r["bti_area"], h=2.2, pos=pos.get(r["id"]))
    # размерные цепочки из measurement.json
    lev = {"top": [9332 + 500, 9332 + 800, 9332 + 1100], "left": [-2631 - 550, -2631 - 900, -2631 - 1250],
           "right": [7830 + 550], "bottom": [-180 - 400, -180 - 700]}
    used = {"top": 0, "left": 0, "right": 0, "bottom": 0}
    for dc in m.MS["dimension_chains"]:
        if dc.get("inner"):
            if dc["axis"] == "X":
                v.dim_chain(dc["points"], "x", dc["ref_y"], labels=dc.get("labels"), h=1.8)
            else:
                v.dim_chain(dc["points"], "y", dc["ref_x"], labels=dc.get("labels"), h=1.8)
            continue
        side = dc["side"]
        at = lev[side][min(used[side], len(lev[side]) - 1)]
        used[side] += 1
        if side in ("top", "bottom"):
            ef = dc["ref_y"]
            v.dim_chain(dc["points"], "x", at, ext_from=ef, labels=dc.get("labels"), h=1.8,
                        text_side=1)
        else:
            ef = dc["ref_x"]
            v.dim_chain(dc["points"], "y", at, ext_from=ef, labels=dc.get("labels"), h=1.8,
                        text_side=1 if side == "left" else -1)
    # отметки уровня
    for em in m.MS["elevation_marks"]:
        if "pos" not in em:
            continue
        x, y = em["pos"]
        v.level_mark((x - 350, y - 650), f"{em['floor']}", h=1.8)
    # подписи инженерных точек
    for u in m.M["utilities"]:
        if u["id"] in ("U25", "U26"):
            continue
        p = u["pos"]
        v.label(p, u["id"], 1.6, color=P.UT_STYLE.get(u["type"], ("", "black"))[1],
                radius=(3, 5, 8, 11, 15), lcolor="#666666")
    # правая колонка
    fl.legend([
        (sym_fill(P.C_EXT), "Несущие и наружные стены (по плану застройщика)"),
        (sym_fill(P.C_PART), "Перегородки застройщика 80"),
        (sym_fill("#d9d9d9", hatch="xx", hc="#333"), "Ж/б колонна C1 (не трогать)"),
        (sym_circle("#6b3d1f", "white", inner="#6b3d1f"), "Стояк канализации К1"),
        (sym_circle("#1f6fd6", "white"), "Стояк водоснабжения (В1/Т3/Т4 — уточнить)"),
        (sym_fill("white", "#8a8a8a", ls="dashed", lw=0.25), "Короб стояков"),
        (sym_fill("white", "#d35400", hatch="xx", hc="#d35400"), "Вентканал / решётка"),
        (sym_fill("white", "#2e8b57", hatch="///", hc="#2e8b57"), "Коллектор водяного ТП (h≈400)"),
        (sym_fill("#c0392b", "#c0392b"), "Щит ЭЩ (U15), [допущение]"),
        (sym_fill("white", "#8a8a8a", ls="dashed", lw=0.13), "Приборы застройщика (условно)"),
    ], h=1.7)
    rows = []
    for u in m.M["utilities"]:
        rows.append([u["id"], u["type"], m.binding_existing_text(u["pos"])])
    fl.table([11, 27, 52], rows, header=["Марка", "Тип", "Привязка к граням стен, мм"], h=1.5,
             title="Привязки инженерных точек (центр)")
    orows = []
    for o in m.M["openings"]:
        s0, s1 = m.opening_span(o)
        orows.append([o["id"], o["wall"], f"{int(s0)}..{int(s1)}", o["width"], o["sill"], o["head"]])
    fl.table([11, 9, 24, 11, 13, 13], orows, header=["Проём", "Стена", "Участок", "Ш", "Низ", "Верх"], h=1.5,
             title="Проёмы (низ/верх от УЧП)")
    notes = ("1. Размеры — по векторному PDF застройщика (14,9745 мм/pt), без фактического обмера: все размеры "
             "уточнить по месту.\n2. ±0.000 = УЧП = верх плиты +100; низ плиты перекрытия +2.750.\n"
             "3. Отметки пола и верх проёмов — [ДОПУЩЕНИЯ] measurement.json.")
    fl.text(notes, h=1.6, title="Примечания", title_h=2.2)
    return sh



def origin_mark(v, h=1.6):
    q = v.P((0, 0))
    v.sh.line((q[0] - 3, q[1]), (q[0] + 3, q[1]), layer="DIM", lw=0.18, ec="#c0392b", z=8)
    v.sh.line((q[0], q[1] - 3), (q[0], q[1] + 3), layer="DIM", lw=0.18, ec="#c0392b", z=8)
    v.sh.text((q[0] + 0.8, q[1] + 0.8), "0,0", h, color="#c0392b", z=8)


def main_dims(v, h=1.8):
    """Габаритные цепочки (по measurement.json DC2, DC5, DC7, DC8)."""
    dcs = {d["id"]: d for d in m.MS["dimension_chains"]}
    d = dcs["DC2"]
    v.dim_chain(d["points"], "x", 9332 + 450, ext_from=9332, labels=d["labels"], h=h)
    d = dcs["DC5"]
    v.dim_chain(d["points"], "y", -2631 - 450, ext_from=-2631, labels=d["labels"], h=h)
    d = dcs["DC7"]
    v.dim_chain(d["points"], "y", 7830 + 450, ext_from=7830, labels=d["labels"], h=h)
    d = dcs["DC8"]
    v.dim_chain(d["points"], "x", -180 - 420, ext_from=-180, labels=d["labels"], h=h)


def rooms_tags_final(v, h=2.2):
    for r in m.PL["rooms"]:
        P.room_tag(v, r["id"], r["name"], r["area"], h=h)


# ---------------------------------------------------------------- АР-02 Планировка D1 + экспликация
def ar02(ctx):
    sh, v, fl = plan_layout("A3", 50, pad=(800, 750, 750, 850), side_cols=1)
    P.draw_plan_final(v, marks=True)
    P.draw_furniture(v, base=True)
    rooms_tags_final(v)
    main_dims(v)
    origin_mark(v)
    rows = []
    tot = 0
    for r in m.PL["rooms"]:
        rows.append([m.ROOM_NO[r["id"]], r["name"], m.fmt_num(r["area"]), r.get("category", "")])
    rows.sort(key=lambda x: x[0])
    a = m.PL["areas"]
    rows.append(["", "Итого без балкона", m.fmt_num(a["sum_without_balcony"]), ""])
    rows.append(["", "в т.ч. жилая", m.fmt_num(a["living"]), ""])
    rows.append(["", "Балкон (БТИ) / после утепления, оценка", f"{m.fmt_num(a['balcony_bti'])} / "
                 f"{m.fmt_num(a['balcony_after_insulation_est'])}", "к=0,3"])
    fl.table([8, 52, 22, 38], rows, header=["№", "Наименование", "Площадь, м²", "Категория"], h=1.7,
             title="Экспликация помещений (вариант D1)")
    fl.text(a.get("note", ""), h=1.5)
    fl.legend([
        (sym_fill(P.C_EXT), "Несущие и наружные стены (сохраняются)"),
        (sym_fill(P.C_PART), "Перегородки застройщика (сохраняются)"),
        (sym_fill(P.MAT_STYLE["pgp"]["fc"], P.C_NEW, hatch="////", hc=P.C_NEW), "Новые перегородки (см. АР-06)"),
        (sym_fill(P.MAT_STYLE["infill"]["fc"], P.C_NEW, hatch="---", hc="#8a6d3b"), "Зашивка окна O1 изнутри"),
        (sym_fill("white", P.C_BASE_F, lw=0.13), "Мебель (см. АР-07)"),
    ], h=1.6)
    txt = m.PL["status"] + "\n" + "\n".join("— " + x for x in m.PL["assumptions"] if "РИСК" in x)
    fl.text(txt, h=1.5, title="Статус варианта", title_h=2.2)
    return sh


# ---------------------------------------------------------------- варианты 1:100
def draw_option(v, opt, h=1.6, furn=True):
    hints = opt.get("drawing_hints") or {}
    ex = m.existing_wall_polys()
    holes = {}
    for oid, wid, s0, s1, typ in m.existing_openings():
        holes.setdefault(wid, []).append(m.opening_rect(m.WALLS[wid], s0, s1))
    for c in hints.get("cut_openings", []):
        w = m.WALLS.get(c["wall"])
        if w:
            base = min(w["a"][0], w["b"][0]) if m.is_horizontal(w) else min(w["a"][1], w["b"][1])
            holes.setdefault(c["wall"], []).append(m.opening_rect(w, base + c["offset"], base + c["offset"] + c["width"]))
    for wid, g in ex.items():
        if wid in hints.get("demolished_walls", []):
            v.shape(g, layer="AR-DEMO", ec=P.C_DEMO, lw=0.2, ls="dashed", z=3)
            continue
        for hh in holes.get(wid, []):
            g = g.difference(hh)
        v.shape(g, layer="AR-WALLS", fc=P.C_EXT if P._is_ext(wid) else P.C_PART, ec="black", lw=0.2, z=3)
    P.draw_glazing(v)
    newp = []
    for w in opt.get("new_walls", []):
        g = m.wall_rect(w["a"], w["b"], w["thickness"])
        for o in opt.get("new_openings", []):
            if o["wall"].split("/")[0] == w["id"]:
                sp = m.parse_span(o["span"])
                if sp:
                    g = g.difference(m.opening_rect(w, sp[1], sp[2]))
        st = P.MAT_STYLE[P.wall_material(w["id"], w.get("material", ""))]
        v.shape(g, layer="AR-NEW", fc=st["fc"], hatch="////", hc=P.C_NEW, ec=P.C_NEW, lw=0.25, z=3.2)
        newp.append(g)
    for oid in hints.get("closed_openings", []):
        o = m.OPEN[oid]
        s0, s1 = m.opening_span(o)
        g = m.opening_rect(m.WALLS[o["wall"]], s0, s1, extra=0)
        for o2 in opt.get("new_openings", []):
            sp = m.parse_span(o2["span"])
            if sp and o2["wall"].split("/")[0] == o["wall"]:
                g = g.difference(m.opening_rect(m.WALLS[o["wall"]], sp[1], sp[2]))
        v.shape(g, layer="AR-NEW", fc="white", hatch="////", hc=P.C_NEW, ec=P.C_NEW, lw=0.25, z=3.2)
    infill = {w["opening"] for w in (opt.get("window_infill") or [])}
    for o in m.M["openings"]:
        if o["type"] == "window":
            s0, s1 = m.opening_span(o)
            P._window_symbol(v, m.WALLS[o["wall"]], s0, s1, lw=0.13, infill=o["id"] in infill)
    if furn:
        for f in opt.get("furniture", []):
            (x0, y0), (x1, y1) = f["rect"]
            v.rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), layer="FURN", ec=P.C_BASE_F, lw=0.1, z=2.5)
    for r in opt.get("rooms", []):
        try:
            pt = P.room_point(r["id"], {r["id"]: r})
        except Exception:
            continue
        q = v.P(pt)
        s = f"{r['name']}\n{m.fmt_num(r.get('area', 0))}"
        v.sh.text(q, s, h, ha="center", va="center", z=7, bg="white")


def options_sheet(keys, scale, title_fn):
    sh = Sheet("A3", scale)
    n = len(keys)
    W = sh.W
    avail = W - 22 - 7
    bw = (P.PLAN_BBOX[2] - P.PLAN_BBOX[0] + 200) / scale
    gap = (avail - n * bw) / max(1, n)
    for i, k in enumerate(keys):
        opt = m.OPTIONS[k]
        x0 = 22 + gap / 2 + i * (bw + gap)
        v = P.fit_view(sh, scale, x0, 150, x0 + bw, 275, pad=(100, 100, 100, 100))
        draw_option(v, opt, h=1.5 if scale >= 100 else 2.0)
        from draw import wrap as _wrap
        for li, ln in enumerate(_wrap(title_fn(k, opt), bw, 2.3, True)[:3]):
            sh.text((x0, 286 - li * 3.3), ln, 2.3, bold=True)
        ex = v.extent
        y = ex[1] - 4
        txt = []
        if opt.get("idea"):
            txt.append(opt["idea"])
        if opt.get("pros"):
            txt.append("Плюсы: " + "; ".join(opt["pros"]))
        if opt.get("cons"):
            txt.append("Минусы: " + "; ".join(opt["cons"]))
        ylim = 64 if x0 + bw > W - 190 else 8
        yy = y
        for t in txt:
            from draw import wrap
            for ln in wrap(t, bw, 1.45):
                if yy < ylim + 2:
                    break
                sh.text((x0, yy), ln, 1.45)
                yy -= 2.1
            yy -= 1.0
    return sh


def ar03(ctx):
    return options_sheet(["A", "B", "C"], 100, lambda k, o: f"{o.get('title', k)} — М 1:100")


def ar04(ctx):
    return options_sheet(["D1", "D2"], 75, lambda k, o: (("ПРИНЯТ: " if k == m.PL["selected_option"] else
                                                          "Альтернатива: ") + m.short(o.get("title", k), 80)
                                                         + " — М 1:75"))


# ---------------------------------------------------------------- АР-05 Демонтаж
def ar05(ctx):
    sh, v, fl = plan_layout("A3", 50, pad=(800, 750, 750, 850), side_cols=1)
    P.draw_existing_walls(v, with_openings=True)
    P.draw_windows(v, final=False)
    P.draw_existing_doors(v, only=("O5",))
    P.draw_existing_doors(v, only=("O6", "O7"), col="#777777", ls="dashed")
    P.draw_utilities(v, base=True)
    g = m.final_geometry()
    pos = {}
    for cid, poly, text in g["demolished"]:
        v.shape(poly, layer="AR-DEMO", fc="white", hatch="xxxx", hc=P.C_DEMO, ec=P.C_DEMO, lw=0.35, ls="dashed", z=4)
        c = poly.centroid
        pos[cid] = (c.x, c.y)
    # заполнение O4 (двустворчатый блок) — демонтаж
    P.draw_existing_doors(v, only=("O4",), col=P.C_DEMO, ls="dashed", layer="AR-DEMO")
    s0, s1 = m.opening_span(m.OPEN["O4"])
    v.rect(-420, s0, 0, s1, layer="AR-DEMO", ec=P.C_DEMO, lw=0.3, ls="dashed", hatch="xx", hc=P.C_DEMO, z=4)
    pos["O4-fill"] = (-210, (s0 + s1) / 2)
    for f in m.M["fixtures"]:
        (x0, y0), (x1, y1) = f["rect"]
        v.rect(x0, y0, x1, y1, layer="AR-DEMO", ec=P.C_DEMO, lw=0.2, ls="dashed", z=4)
        v.line((x0, y0), (x1, y1), layer="AR-DEMO", ec=P.C_DEMO, lw=0.13, ls="dashed", z=4)
        v.line((x0, y1), (x1, y0), layer="AR-DEMO", ec=P.C_DEMO, lw=0.13, ls="dashed", z=4)
    fx = {f["id"]: f for f in m.M["fixtures"]}
    (a, b), (c, d) = fx["F1"]["rect"]
    pos["F1"] = ((a + c) / 2, (b + d) / 2)
    (a, b), (c, d) = fx["F8"]["rect"]
    pos["F-all"] = ((a + c) / 2, (b + d) / 2)
    s0, s1 = m.opening_span(m.OPEN["O1"])
    pos["O1-infill"] = (-100, (s0 + s1) / 2)
    pos["O7-part"] = (4860, 5290)
    pos["O6-part"] = (5640, 1971)
    for i, d in enumerate(m.PL["demolition"], start=1):
        if d["id"] in pos:
            v.label(pos[d["id"]], f"{i}", 2.2, color=P.C_DEMO, bold=True, radius=(4, 7, 10, 14),
                    lcolor=P.C_DEMO)
    rooms_tags_final(v, h=2.0)
    main_dims(v)
    rows = [[i, d["id"], d["what"]] for i, d in enumerate(m.PL["demolition"], start=1)]
    fl.table([7, 16, 97], rows, header=["Поз.", "Элемент", "Состав работ (planning.json)"], h=1.5,
             title="Ведомость демонтажа", max_lines=8)
    fl.legend([
        (sym_fill(P.C_EXT), "Сохраняемые несущие/наружные стены"),
        (sym_fill(P.C_PART), "Сохраняемые перегородки"),
        (sym_fill("white", P.C_DEMO, hatch="xxxx", hc=P.C_DEMO, ls="dashed"), "Демонтируемые участки стен / заполнения проёмов"),
        (sym_line(P.C_DEMO, "dashed", 0.3), "Демонтируемые приборы и блоки (если установлены)"),
        (sym_line("#777777", "dashed", 0.3), "Существующие дверные блоки O6/O7 (проёмы изменяются, см. АР-06)"),
    ], h=1.6)
    return sh


# ---------------------------------------------------------------- АР-06 Монтаж перегородок
def ar06(ctx):
    sh, v, fl = plan_layout("A3", 50, pad=(800, 750, 750, 850), side_cols=1)
    P.draw_plan_final(v, marks=True)
    rooms_tags_final(v, h=2.0)
    main_dims(v)
    origin_mark(v)
    # привязки новых стен и проёмов
    v.dim_chain([0, 760, 2530, 3380], "x", 3580 - 380, ext_from=3580, h=1.8)
    v.dim_chain([3520, 3600, 4480, 4820], "x", 6051 + 330, ext_from=6051, h=1.8)
    v.dim_chain([4170, 4570, 5370, 5910], "x", 2011 + 330, ext_from=2011, h=1.8)
    v.dim_chain([3721, 4250, 5050, 5531, 5970], "y", 4820 - 330, ext_from=4820, h=1.8)
    v.dim_chain([3721, 4621, 4820], "y", 3380 - 330, ext_from=3380, h=1.8)
    for wid, poly in m.final_geometry()["new"].items():
        c = poly.representative_point()
        v.label((c.x, c.y), wid, 1.8, color=P.C_NEW, bold=True, radius=(5, 8, 12, 16), lcolor=P.C_NEW)
    for cid, (poly, c) in m.construction_polys().items():
        cc = poly.representative_point()
        v.label((cc.x, cc.y), cid, 1.6, color=P.C_NEW, radius=(5, 8, 12, 16), lcolor=P.C_NEW)
    v.label((-150, 6616), "O1: зашивка", 1.6, color="#8a6d3b", radius=(6, 10), lcolor="#8a6d3b")
    rows = []
    for w in m.PL["new_walls"]:
        L = abs(w["b"][0] - w["a"][0]) + abs(w["b"][1] - w["a"][1])
        net = m.final_geometry()["new"][w["id"]].area / w["thickness"]
        rows.append([w["id"], w["thickness"], int(round(L)), int(round(net)), w["material"], w.get("purpose", "")])
    inf = m.d1_infill()
    if inf is not None:
        b = inf.bounds
        rows.append(["D1-доб", 140, int(b[3] - b[1]), int(b[3] - b[1]), "ПГП (doors.json: «добор ПГП 199»)",
                     "добор в проёме O8 у двери Д-1"])
    for cid, (poly, c) in m.construction_polys().items():
        b = poly.bounds
        rows.append([cid, int(min(b[2] - b[0], b[3] - b[1])), int(max(b[2] - b[0], b[3] - b[1])), "—",
                     c.get("build", ""), c.get("what", "")])
    fl.table([11, 9, 10, 10, 50, 30], rows, header=["Марка", "t", "L", "L нетто", "Материал", "Назначение"], h=1.4,
             title="Ведомость перегородок и облицовок (мм)", max_lines=7)
    leg = [(sym_fill(P.C_EXT), "Сохраняемые несущие/наружные стены"), (sym_fill(P.C_PART), "Сохраняемые перегородки")]
    for k in ("pgp", "pgp_w", "pgp_gkl", "gkl", "infill", "pgp_d"):
        st = P.MAT_STYLE[k]
        leg.append((sym_fill(st["fc"], P.C_NEW, hatch=st["hatch"], hc=st["hc"]), st["label"]))
    fl.legend(leg, h=1.5)
    fl.text("\n".join(f"{i}. {t}" for i, t in enumerate(m.PL["new_walls_general"], 1)), h=1.4,
            title="Указания по монтажу", title_h=2.2)
    return sh


# ---------------------------------------------------------------- АР-07 Мебель
def ar07(ctx):
    sh, v, fl = plan_layout("A2", 50, pad=(550, 700, 650, 850), side_cols=2)
    P.draw_plan_final(v)
    P.draw_furniture(v, label=True, h=1.7)
    P.draw_utilities(v, labels=False, base=True)
    for r in m.PL["rooms"]:
        P.room_tag(v, r["id"], r["name"], r["area"], h=2.2, pos=FURN_TAG.get(r["id"]))
    main_dims(v)
    origin_mark(v)
    rows = []
    for it in m.FU["items"]:
        x0, y0, x1, y1 = m.frect(it)
        z = it.get("z")
        size = "×".join(str(int(s)) for s in it["size"])
        rows.append([it["id"], it["room"], it["name"], size, f"x {int(x0)}..{int(x1)}; y {int(y0)}..{int(y1)}"
                     + (f"; низ +{int(z)}" if z else ""), "да" if it.get("custom") else ""])
    fl.split_table([10, 8, 88, 22, 40, 9], rows, header=["Марка", "Пом.", "Наименование", "Ш×Г×В",
                                                         "Положение (от 0,0), мм", "Изг."], h=1.45,
                   title="Экспликация мебели и оборудования (furniture.json)", max_lines=3)
    fl.text("\n".join(f"{i}. {t}" for i, t in enumerate(m.FU["general_rules"], 1)), h=1.5,
            title="Общие указания", title_h=2.2)
    return sh


FURN_TAG = {"R1": (2300, 7300), "R2": (5900, 7350), "R3": (2900, 2250), "R4": (6300, 2550), "R5": (5650, 4700),
            "R6": (5000, 1650), "R7": (-1200, 1700)}


# ---------------------------------------------------------------- АР-08 Двери
def ar08(ctx):
    sh, v, fl = plan_layout("A3", 50, pad=(800, 750, 750, 850), side_cols=1)
    P.draw_plan_final(v, marks=True)
    P.draw_furniture(v, base=True)
    rooms_tags_final(v, h=2.0)
    main_dims(v)
    # марка входной двери и портала
    for did, pt in (("ДВ-1", (6790, 1700)), ("П-1", (-650, 1520))):
        q = v.P(pt)
        r = max(2.6, text_w(did, 2.0) / 2 + 0.8)
        sh.circle(q, r, ec="black", lw=0.25, fc="white", z=7)
        sh.text((q[0], q[1] - 1.0), did, 2.0, ha="center", z=7.5)
    rows = []
    for d in m.DO["doors"]:
        rows.append([d["no"], d["room"], d["opening_clear"], d["leaf"], d["type"], d["swing"] + "; " + d["hand"],
                     d["threshold"]])
    fl.table([9, 16, 19, 16, 22, 22, 18], rows, header=["Марка", "Помещение", "Проём в чистоте", "Полотно", "Тип",
                                                       "Открывание", "Порог"], h=1.35, title="Ведомость дверей",
             max_lines=9)
    rows = [[d["no"], d["hardware"], d.get("note", "")] for d in m.DO["doors"] if d["hardware"] != "—"]
    fl.table([10, 70, 42], rows, header=["Марка", "Фурнитура", "Примечание"], h=1.3, max_lines=8)
    fl.text("\n".join(f"{i}. {t}" for i, t in enumerate(m.DO["general"], 1)), h=1.4, title="Общие указания",
            title_h=2.2)
    return sh


# ---------------------------------------------------------------- АР-09 Потолки
LEVEL_C = {2700: "#ffffff", 2650: "#e3eefa", 2550: "#c9dcf2", 2500: "#dcefd6", 2450: "#bfe0b8", 2400: "#f6dfbe",
           2290: "#efb88f"}


def _lev(v):
    return f"+{v / 1000:.3f}".replace(".", ",") if v else "±0,000"


def ar09(ctx, fmt="A3"):
    sh, v, fl = plan_layout(fmt, 50, pad=(550, 700, 650, 850), side_cols=1 if fmt == "A3" else 2)
    for z in m.CE["zones"]:
        if "rect" in z:
            x0, y0, x1, y1 = z["rect"]
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        else:
            pts = z["poly"]
        v.poly(pts, layer="AR-FIN", fc=LEVEL_C.get(z["level"], "#eeeeee"), ec=None, lw=0, z=1)
    for b in m.CE["boxes"]:
        x0, y0, x1, y1 = b["rect"]
        v.rect(x0, y0, x1, y1, layer="AR-FIN", fc=LEVEL_C.get(b["bottom"], "#f2d0b0"), ec="#8a5a2b", lw=0.25,
               hatch="\\\\", hc="#8a5a2b", z=1.5)
    for c in m.CE["curtain_niches"]:
        if "rect" in c:
            x0, y0, x1, y1 = c["rect"]
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        else:
            pts = c["poly"]
        v.poly(pts, layer="AR-FIN", fc="#f7f7f7", ec="#555555", lw=0.2, ls="dashed", hatch="..", hc="#777777", z=1.6)
    for hc in m.CE["hatches"]:
        x0, y0, x1, y1 = hc["rect"]
        v.rect(x0, y0, x1, y1, layer="AR-FIN", ec="#b03a2e", lw=0.3, z=4)
        v.line((x0, y0), (x1, y1), layer="AR-FIN", ec="#b03a2e", lw=0.13, z=4)
    P.draw_plan_final(v, occupy=False)
    # светильники (подложка)
    for l in m.EL["lights"]:
        if l["type"] in ("spot", "ceiling", "pendant"):
            v.circle(l["pos"], r_paper=0.9 if l["type"] == "spot" else 1.6, layer="EL-LIGHT", ec="#7a6a00", lw=0.18,
                     z=5)
    for z in m.CE["zones"]:
        if "rect" in z:
            x0, y0, x1, y1 = z["rect"]
            c = ((x0 + x1) / 2, (y0 + y1) / 2)
        else:
            c = P.room_point(z["room"])
        cpos = {"CZ-R3": (2200, 2700), "CZ-R4": (6300, 2700), "CZ-R5": (5900, 4600), "CZ-R6": (5000, 1350),
                "CZ-R7": (-1480, 1450), "CZ-R1": (1690, 6600), "CZ-R2": (5600, 7400)}.get(z["id"], c)
        q = v.P(cpos)
        s = f"{z['id']}  {_lev(z['level'])}"
        v.level_mark((cpos[0] - 600, cpos[1]), _lev(z["level"]), h=2.0)
        v.label((cpos[0], cpos[1] - 250), z["id"], 1.8, radius=(0, 3), leader=False)
    for b in m.CE["boxes"]:
        x0, y0, x1, y1 = b["rect"]
        v.label(((x0 + x1) / 2, (y0 + y1) / 2), f"{b['id']} низ {_lev(b['bottom'])}", 1.6, color="#8a5a2b",
                radius=(4, 7, 10, 14, 19), lcolor="#8a5a2b")
    for c in m.CE["curtain_niches"]:
        if "rect" in c:
            x0, y0, x1, y1 = c["rect"]
            pt = ((x0 + x1) / 2, (y0 + y1) / 2)
        else:
            pt = tuple(c["poly"][2])
        v.label(pt, c["id"], 1.6, radius=(4, 7, 10), lcolor="#555")
    for hc in m.CE["hatches"]:
        x0, y0, x1, y1 = hc["rect"]
        v.label(((x0 + x1) / 2, (y0 + y1) / 2), hc["id"], 1.6, color="#b03a2e", radius=(4, 7, 10, 14),
                lcolor="#b03a2e")
    main_dims(v)
    leg = [(sym_fill(LEVEL_C[k], "#777", lw=0.13), f"Потолок {_lev(k)}") for k in sorted(
        {z["level"] for z in m.CE["zones"]}, reverse=True)]
    leg += [(sym_fill("#f6dfbe", "#8a5a2b", hatch="\\\\", hc="#8a5a2b"), "Короб/опуск ГКЛ (низ — по подписи)"),
            (sym_fill("#f7f7f7", "#555", hatch="..", hc="#777", ls="dashed"), "Ниша под карниз штор"),
            (sym_fill("white", "#b03a2e"), "Люк / ревизия в потолке"),
            (sym_circle("#7a6a00", r=0.9), "Встроенный светильник (по ЭО-01)")]
    fl.legend(leg, h=1.6)
    rows = [[z["id"], z["room"], _lev(z["level"]), z["type"], z.get("finish", "")] for z in m.CE["zones"]]
    fl.table([12, 8, 13, 50, 37], rows, header=["Зона", "Пом.", "Отметка", "Конструкция", "Отделка"], h=1.35,
             title="Типы потолков", max_lines=6)
    rows = [[b["id"], f"{_lev(b['bottom'])}", b["name"]] for b in m.CE["boxes"]]
    rows += [[c["id"], str(c["width"]), c.get("track", "")] for c in m.CE["curtain_niches"]]
    rows += [[h["id"], h["size"], h["type"] + "; " + h.get("access", "")] for h in m.CE["hatches"]]
    fl.table([12, 14, 94], rows, header=["Марка", "Низ / размер", "Описание"], h=1.35,
             title="Короба, ниши штор, люки", max_lines=4)
    fl.text("\n".join(f"{i}. {t}" for i, t in enumerate(m.CE["principles"], 1)) + "\n" + m.CE["datum"], h=1.35,
            title="Указания", title_h=2.2)
    return sh


# ---------------------------------------------------------------- АР-10 Полы
FLOOR_ST = {
    "oak": dict(fc="#efe2c8", hatch="////", hc="#a8865a", label="M01 инж. доска дуб «ёлочка» (P-OAK)"),
    "tile_hall": dict(fc="#ecebe6", hatch="++", hc="#8f8f8f", label="M16 керамогранит 600×600 у входа (P-TILE-HALL)"),
    "bath": dict(fc="#e2edf3", hatch="++", hc="#6b8fa6", label="M20 керамогранит, подиум +80 (P-BATH)"),
    "laundry": dict(fc="#e9f0e4", hatch="++", hc="#6f8f6b", label="M25 керамогранит 600×600 (P-LAUNDRY)"),
    "lvt": dict(fc="#e7d8c0", hatch="\\\\\\\\", hc="#8a6d3b", label="M28 LVT «ёлочка» (P-BALC)"),
}
FLOOR_TAG = {"R7": (-1480, 2550), "R2": (5900, 7000), "R6": (5050, 1450)}
JUNCTION_POS = {"J1": (-210, 1520), "J2": (5910, 2700), "J3": (4170, 3721), "J4": (3450, 4171), "J5": (4860, 4650),
                "J6": (4970, 1971), "J7": (5600, 5666)}


def ar10(ctx, fmt="A3"):
    sh, v, fl = plan_layout(fmt, 50, pad=(550, 700, 650, 850), side_cols=1 if fmt == "A3" else 2)
    th = m.FL["tile_hall"]["zone"]
    for r in m.PL["rooms"]:
        rid = r["id"]
        key = {"R5": "bath", "R6": "laundry", "R7": "lvt"}.get(rid, "oak")
        st = FLOOR_ST[key]
        g = Polygon(r["polygon"])
        if rid == "R4":
            g = g.difference(box(*th))
        v.shape(g, layer="AR-FIN", fc=st["fc"], hatch=st["hatch"], hc=st["hc"], ec=None, lw=0, z=1)
    st = FLOOR_ST["tile_hall"]
    v.shape(box(*th), layer="AR-FIN", fc=st["fc"], hatch=st["hatch"], hc=st["hc"], ec="#555", lw=0.2, z=1.2)
    P.draw_plan_final(v)
    P.draw_furniture(v, base=True, ids=[i for i in m.FI if m.FI[i].get("layer") == "floor"])
    for r in m.PL["rooms"]:
        P.room_tag(v, r["id"], r["name"], r["area"], h=1.9, pos=FLOOR_TAG.get(r["id"], FURN_TAG.get(r["id"])))
    # направление ёлочки (ось) — стрелки
    for key, hb in m.FL["herringbone"].items():
        ax = hb["axis"][0]
        pos = {"R3+R4 прихожая": (1500, 1520), "R4 коридор": (4170, 4700), "R1": (1690, 6900), "R2": (5900, 7481),
               "R7 LVT": (-1480, 1520)}.get(key)
        if not pos:
            continue
        L = 900
        a = (pos[0] - L / 2, pos[1]) if ax == "X" else (pos[0], pos[1] - L / 2)
        b = (pos[0] + L / 2, pos[1]) if ax == "X" else (pos[0], pos[1] + L / 2)
        v.line(a, b, layer="AR-FIN", ec="#5a3d1a", lw=0.5, z=6)
        for e, s0 in ((b, a), (a, b)):
            q, q0 = v.P(e), v.P(s0)
            dx, dy = q[0] - q0[0], q[1] - q0[1]
            n = (dx * dx + dy * dy) ** 0.5
            ux, uy = dx / n, dy / n
            sh.poly([q, (q[0] - 2 * ux - 0.8 * uy, q[1] - 2 * uy + 0.8 * ux),
                     (q[0] - 2 * ux + 0.8 * uy, q[1] - 2 * uy - 0.8 * ux)], layer="AR-FIN", fc="#5a3d1a",
                    ec="#5a3d1a", lw=0.1, z=6)
        v.label(pos, f"ось ёлочки {hb['axis'].split(' ')[0]}", 1.5, color="#5a3d1a", radius=(3, 5, 8))
    for rid, lv in m.FL["levels"].items():
        if rid == "note":
            continue
        pt = {"R5": (5300, 4400), "R1": (900, 6000), "R2": (4600, 7900), "R3": (900, 2900), "R4": (6800, 2300),
              "R6": (4650, 350), "R7": (-2300, 700)}.get(rid, P.room_point(rid))
        v.level_mark(pt, _lev(lv) if lv else "±0,000", h=1.8)
    for j in m.FL["junctions"]:
        pt = JUNCTION_POS.get(j["id"])
        if pt:
            v.label(pt, j["id"], 1.8, color="#b03a2e", bold=True, radius=(4, 7, 10, 14), lcolor="#b03a2e")
    main_dims(v)
    fl.legend([(sym_fill(s["fc"], "#555", hatch=s["hatch"], hc=s["hc"], lw=0.13), s["label"]) for s in FLOOR_ST.values()]
              + [(sym_text("J1", color="#b03a2e"), "Стык покрытий / порог (таблица ниже, узлы АР-17/18)")], h=1.6)
    rows = [[r["room"], r["covering"], r["pie"], _lev(r["level"]) if r["level"] else "±0,000", r.get("ufh", ""),
             r.get("plinth", "")] for r in m.FL["rooms"]]
    fl.table([9, 30, 18, 12, 28, 23], rows, header=["Пом.", "Покрытие", "Пирог", "Отм.", "Обогрев", "Плинтус"],
             h=1.35, title="Ведомость покрытий", max_lines=4)
    prow = []
    bold = []
    for pid, pie in m.FL["pies"].items():
        bold.append(len(prow))
        prow.append([pid, pie["name"], f"верх {pie['top']}"])
        for nm, t in pie["layers"]:
            prow.append(["", nm, str(t)])
    fl.split_table([20, 85, 15], prow, header=["Пирог", "Слой (снизу вверх)", "мм / отм."], h=1.3,
                   title="Пироги полов (floors.json)", max_lines=3, bold_rows=bold)
    rows = [[j["id"], j["where"], j["detail"]] for j in m.FL["junctions"]]
    fl.split_table([9, 45, 66], rows, header=["Стык", "Где", "Решение"], h=1.3, title="Стыки и пороги",
                   max_lines=5)
    return sh


SHEETS = {"АР-01": ar01, "АР-02": ar02, "АР-03": ar03, "АР-04": ar04, "АР-05": ar05, "АР-06": ar06, "АР-07": ar07,
          "АР-08": ar08, "АР-09": ar09, "АР-10": ar10}
