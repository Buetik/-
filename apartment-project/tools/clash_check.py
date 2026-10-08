#!/usr/bin/env python3
"""pib-norm-control: сквозная проверка комплекта (нормоконтроль, 9 групп регламента).

Только чтение. Ничего в слоях данных не меняет и не пересобирает.

Группы:
  1. Полнота — sheet-register.json ↔ 03-drawings/pdf (файлы, страницы, шифр/«Формат» в штампе, заглушки,
     незаполненные графы штампа).
  2. Геометрия — мебель ↔ стены, мебель ↔ мебель (частичные пересечения), двери ↔ мебель (дуга 90° и
     положение 180°), проходы.
  3. Мебель ↔ электрика — запуск tools/check_electrical_needs.py (needs ≤ 1 м, зоны ванной, УЗО, мощность)
     + розетки, закрытые мебелью, выключатели за открытой дверью / со стороны петель.
  4. Мебель ↔ ВК — выводы у мокрых приборов (plumbing.fixtures), уклоны (tools/calc_sewer_slopes.py)
     при проектном уклоне и при нормальном 0,03 для Ø50, отметки подиума/порога.
  5. ЭО ↔ потолки — встроенные светильники только в зонах с пленумом ≥ 80, высоты = отметке потолка.
  6. ОВ ↔ потолки/мебель — короба и опуски из hvac.json есть в ceilings.json; мебель не выше потолка;
     вентканалы/решётки не перекрыты.
  7. Отделка — у каждого помещения пол/стены/потолок в СП-01; мокрые зоны — ГИ; пороги/двери ↔ полы.
  8. Нормы — ванная: зоны ГОСТ Р 50571.7.701 от фактической точки выхода воды (верхний душ на VK-C1),
     АВДТ 10/30 мА, ДУП; электро-ТП; мокрые зоны в существующих границах.
  9. Смета — количества в 04-specs/*.md ↔ слои чертежей; бюджет (estimate.md, раздел 2).

Переиспользует tools/model.py (геометрия стен D1), check_electrical_needs.py (подпроцесс),
calc_sewer_slopes.py (импорт lines/evaluate). gen_furniture.py НЕ импортируется: при импорте он
перезаписывает furniture.json/doors.json — его проверки (контур помещения, пересечения, коллекторы, щиты,
U22, окна) воспроизведены здесь в режиме только-чтение.

Запуск:  python3 tools/clash_check.py [--json OUT.json]
Код возврата: 0 — блокеров по данным нет; 1 — есть позиции уровня «Блокер».
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import model as g  # noqa: E402  (только чтение)
import calc_sewer_slopes as sew  # noqa: E402

from shapely.geometry import Point, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

FINDINGS: list[dict] = []


def add(group, level, obj, text, ref="", who=""):
    FINDINGS.append(dict(group=group, level=level, obj=obj, text=text, ref=ref, who=who))


def rect(it):
    x, y = it["pos"]
    w, d = it["size"][0], it["size"][1]
    if it.get("rotation", 0) in (90, 270):
        w, d = d, w
    return (x, y, x + w, y + d)


def zr(it):
    z = it.get("z") or 0
    return z, z + it["size"][2]


def ov2(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def contains(a, b, tol=2):
    return a[0] - tol <= b[0] and a[1] - tol <= b[1] and a[2] + tol >= b[2] and a[3] + tol >= b[3]


ITEMS = g.FU["items"]
FI = {it["id"]: it for it in ITEMS}
EL = g.EL

# ===================================================================== 1. Полнота
def check_completeness():
    reg = g.load_register()
    pdf_dir = g.DRAW / "pdf"
    total_pages = 0
    for s in reg:
        f = ROOT / s["file"]
        if not f.exists():
            add(1, "Блокер", s["code"], "нет PDF листа", "ГОСТ Р 21.101-2020 п. 4", "pib-cad")
            continue
        try:
            info = subprocess.run(["pdfinfo", str(f)], capture_output=True, text=True).stdout
            pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
            txt = subprocess.run(["pdftotext", "-layout", str(f), "-"], capture_output=True, text=True).stdout
        except Exception as e:  # pragma: no cover
            add(1, "Замечание", s["code"], f"pdfinfo/pdftotext недоступны: {e}")
            continue
        total_pages += pages
        if pages != s.get("pages", 1):
            add(1, "Замечание", s["code"], f"страниц {pages} ≠ {s.get('pages')} в ведомости", "", "pib-cad")
        if s["code"] != "ОД-01" and f"КВ108-ДП-{s['code']}" not in txt:
            add(1, "Важно", s["code"], "в штампе нет обозначения документа", "ГОСТ Р 21.101-2020, форма 3", "pib-cad")
        fm = re.findall(r"Формат (A\d)", txt)
        if fm and fm[0] != s["format"]:
            add(1, "Замечание", s["code"], f"формат в штампе {fm[0]} ≠ ведомость {s['format']}", "", "pib-cad")
        if s.get("status") == "stub":
            add(1, "Блокер", s["code"], f"лист-заглушка: {s.get('note', '')[:120]}", "ГОСТ Р 21.101-2020 (состав РД)",
                s["owner"])
    alb = pdf_dir / "album.pdf"
    if alb.exists():
        info = subprocess.run(["pdfinfo", str(alb)], capture_output=True, text=True).stdout
        ap = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        if ap != total_pages:
            add(1, "Важно", "album.pdf", f"страниц в альбоме {ap} ≠ сумме листов {total_pages}", "", "pib-cad")
    # графы штампа «Пров./ГИП/Н.контр./Утв.» — пустые на всех листах (по образцу АР-07)
    add(1, "Замечание", "все листы", "в основной надписи не заполнены графы «Пров.», «ГИП», «Н.контр.», «Утв.» "
        "(заполняются после закрытия замечаний НК)", "ГОСТ Р 21.101-2020, прил. Ж (графы 10–13)", "pib-cad / pib-chief-architect")
    gn = ROOT / "04-specs/general-notes.md"
    if not gn.exists():
        add(1, "Блокер", "ОД-03 / 04-specs/general-notes.md", "общие указания не выпущены (CAD-11)",
            "ГОСТ Р 21.101-2020 п. 4.2.x (общие данные РД)", "pib-chief-architect")
    ev = g.EV["elevations"] if g.EV else []
    by_room = {}
    for e in ev:
        by_room.setdefault(e["room"], []).append(e["wall_id"])
    if not by_room.get("R2"):
        add(1, "Блокер", "АР-16 / elevations.json", "нет разверток детской R2 (CAD-05)", "состав комплекта (README)", "pib-finishes")
    if len(by_room.get("R4", [])) < 2:
        add(1, "Важно", "АР-12 / elevations.json", f"прихожая-коридор: только {by_room.get('R4')} — нет W12/W13/NW4/W7 со стороны коридора, "
            "W14 со щитами U15/U16, W5 с входной дверью (CAD-05)", "состав комплекта (README)", "pib-finishes")
    for rid, need in (("R1", {"W1", "W8"}), ("R3", {"W10", "W8"})):
        have = set(by_room.get(rid, []))
        if not (need & have):
            add(1, "Замечание", f"elevations {rid}", f"развертки {sorted(have)}; нет {sorted(need)} (окно/рабочее место, шкаф, буфет)",
                "", "pib-finishes")


# ===================================================================== 2. Геометрия
WALL_SOLID = None


def walls_solid():
    global WALL_SOLID
    if WALL_SOLID is None:
        fg = g.final_geometry()
        WALL_SOLID = unary_union(list(fg["kept"].values()) + list(fg["new"].values()))
    return WALL_SOLID


LOOSE = {"F26", "F27", "F28", "F29", "F30", "F31", "F50", "F55", "F58", "F36"}   # стулья, кресла, ковёр, пуф
IGNORE_WALL = {"F37", "F39", "F40", "F41", "F90", "F64", "F68"}   # в зоне остекления / на стене / облицовка / щит


def check_geometry():
    ws = walls_solid()
    for it in ITEMS:
        if it["id"] in IGNORE_WALL:
            continue
        r = box(*rect(it))
        a = r.intersection(ws).area
        if a > 2000:
            add(2, "Важно", it["id"], f"заходит в тело стен на {a/1e4:.1f} дм²", "геометрия D1", "pib-furniture")
    # частичные пересечения (вложенные встроенные элементы — пропускаются)
    for i in range(len(ITEMS)):
        for j in range(i + 1, len(ITEMS)):
            a, b = ITEMS[i], ITEMS[j]
            if a["room"] != b["room"]:
                continue
            ra, rb = rect(a), rect(b)
            s = ov2(ra, rb)
            if s <= 2000 or contains(ra, rb) or contains(rb, ra):
                continue
            if min(a["size"][2], b["size"][2]) <= 20 or {a["id"], b["id"]} & LOOSE:
                continue
            za, zb = zr(a), zr(b)
            if min(za[1], zb[1]) - max(za[0], zb[0]) <= 0:
                continue
            add(2, "Замечание", f"{a['id']} × {b['id']}", f"частичное пересечение в плане {s/1e4:.1f} дм² и по высоте "
                f"({za[0]}..{za[1]} / {zb[0]}..{zb[1]}) — проверить, не вложенный ли элемент", "", "pib-furniture")
    # U22/U23 (gen_furniture)
    for u in g.M["utilities"]:
        if u["type"] == "balcony_post_or_drain":
            px, py = u["pos"]
            ur = (px - 100, py - 100, px + 100, py + 100)
            for it in ITEMS:
                if (it.get("z") or 0) < 100 and ov2(rect(it), ur) > 0:
                    add(2, "Замечание", f"{it['id']} × {u['id']}", "изделие стоит на элементе балкона Ø200 (CAD-09)",
                        "questions №46", "pib-furniture / pib-measurement")
    check_doors()


# параметры распашных дверей: (id, стена, ось вдоль стены, координата грани со стороны открывания,
#   направление открывания (+1/-1 по нормали), петли у s0 (True) / s1, полотно, макс. угол)
DOOR_SWING = {
    "D1": dict(axis="y", face=3380, into=-1, hinge_at_s0=True, leaf=800, max_deg=90),
    "D2": dict(axis="x", face=6051, into=+1, hinge_at_s0=True, leaf=800, max_deg=90),
    "D3": dict(axis="y", face=4820, into=-1, hinge_at_s0=True, leaf=700, max_deg=180),
    "D4": dict(axis="x", face=2011, into=+1, hinge_at_s0=True, leaf=700, max_deg=180),
}


def door_geom(did):
    o = next(x for x in g.PL["new_openings"] if x["id"] == did)
    _, s0, s1 = g.parse_span(o["span"])
    p = DOOR_SWING[did]
    hinge = s0 if p["hinge_at_s0"] else s1
    sign_open = 1 if p["hinge_at_s0"] else -1            # направление вдоль стены к ручке
    L = p["leaf"]

    def pt(s, n):   # s — вдоль стены, n — от грани в сторону открывания
        return (s, p["face"] + p["into"] * n) if p["axis"] == "x" else (p["face"] + p["into"] * n, s)

    hp = Point(pt(hinge, 0))
    sweep = hp.buffer(L, 64)
    quad = box(*_bbox([pt(hinge, 0), pt(hinge + sign_open * L, L)]))
    arc90 = sweep.intersection(quad)
    leaf180 = None
    if p["max_deg"] >= 180:
        leaf180 = box(*_bbox([pt(hinge, 0), pt(hinge - sign_open * L, 45)]))
    handle = hinge + sign_open * (s1 - s0) if p["hinge_at_s0"] else s0
    return dict(arc=arc90, leaf180=leaf180, hinge=hinge, handle=handle, s0=s0, s1=s1, p=p, sign=sign_open)


def _bbox(pts):
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    return min(xs), min(ys), max(xs), max(ys)


def check_doors():
    gs = {d: door_geom(d) for d in DOOR_SWING}
    for did, dg in gs.items():
        for it in ITEMS:
            if (it.get("z") or 0) >= 2100:
                continue
            r = box(*rect(it))
            a = r.intersection(dg["arc"]).area
            if a > 500:
                add(2, "Важно", f"{did} × {it['id']}", f"дуга открывания 90° задевает изделие ({a/1e4:.1f} дм²)",
                    "СП 54.13330.2022 п. 5 (функциональность); doors.json", "pib-furniture")
            if dg["leaf180"] is not None and r.intersection(dg["leaf180"]).area > 500:
                add(2, "Важно", f"{did} × {it['id']}", "полотно при открывании на 180° ложится на изделие", "doors.json", "pib-furniture")
        # дверь ↔ дверь
        for d2, g2 in gs.items():
            if d2 <= did:
                continue
            a = dg["arc"].intersection(g2["arc"]).area
            if a > 500:
                add(2, "Важно", f"{did} × {d2}", f"дуги открывания пересекаются ({a/1e4:.1f} дм²)", "", "pib-furniture")
        # проход: остаток коридора при открытой D3
    # проход коридора при открытой D3 (полотно 90° поперёк коридора 1300)
    rest = 1300 - DOOR_SWING["D3"]["leaf"]
    if rest < 700:
        add(2, "Замечание", "D3 / коридор", f"при открытой на 90° D3 в коридоре остаётся {rest} мм", "СП 54 п. 5.x (≥ 850 — для постоянного прохода)", "pib-furniture")
    # мебель ↔ выключатели/розетки за полотном 180°
    for did, dg in gs.items():
        if dg["leaf180"] is None:
            continue
        zone = dg["leaf180"].buffer(60)
        for sw in EL["switches"] + EL["sockets"] + EL["low_voltage"]:
            if Point(sw["pos"]).within(zone) and 300 <= sw.get("height", 0) <= 2100:
                add(3, "Важно", f"{did} × {sw['id']}", f"точка {sw['id']} (h {sw.get('height')}) оказывается за полотном "
                    f"{did}, открытым на 180° (doors.json: «лист ложится на стену»)",
                    "регламент НК п. 3; СП 256.1325800.2016 п. 15.x (доступность выключателей)", "pib-furniture / pib-electrical")


# ===================================================================== 3. Мебель ↔ электрика
def check_electrical():
    r = subprocess.run([sys.executable, str(ROOT / "tools/check_electrical_needs.py")], capture_output=True, text=True)
    out = r.stdout
    errs = re.findall(r"^  (?!нет)(.+)$", out.split("ПРЕДУПРЕЖДЕНИЯ:")[0].split("ОШИБКИ:")[-1], re.M)
    for e in errs:
        add(3, "Важно", "check_electrical_needs", e, "", "pib-electrical")
    m = re.search(r"needs: закрыто (\d+) из (\d+)", out)
    if m and m.group(1) != m.group(2):
        add(3, "Важно", "needs", f"закрыто {m.group(1)} из {m.group(2)}", "", "pib-electrical")
    # розетки, закрытые глухой мебелью (не связанные с изделием через need_ref)
    for s in EL["sockets"]:
        refs = {x.split(".")[0] for x in (s.get("need_ref") or [])}
        if s["type"] == "wire_out":
            continue                      # выводы под БП/оборудование — по замыслу за мебелью
        x, y = s["pos"]
        h = s.get("height", 0)
        if s["room"] == "R5":
            h += 80
        for it in ITEMS:
            if it["id"] in refs or it["id"] in ("F41", "F90"):   # облицовки/буазери — розетка в плоскости панели
                continue
            if any(r in FI and contains(rect(it), rect(FI[r])) for r in refs):
                continue                  # точка изделия, встроенного в этот корпус (холодильник в пенале и т. п.)
            x1, y1, x2, y2 = rect(it)
            z1, z2 = zr(it)
            if x1 - 30 <= x <= x2 + 30 and y1 - 30 <= y <= y2 + 30 and z1 - 40 <= h <= z2 + 40 and it["size"][2] > 50:
                add(3, "Замечание", f"{s['id']} × {it['id']}", f"розетка/вывод h {s.get('height')} за изделием {it['id']} "
                    f"(z {z1}..{z2}) без ссылки need_ref — проверить доступ", "", "pib-electrical / pib-furniture")
    # выключатели со стороны петель
    for did, p in DOOR_SWING.items():
        dg = door_geom(did)
        for sw in EL["switches"]:
            x, y = sw["pos"]
            s_along, n = (x, y) if p["axis"] == "x" else (y, x)
            if abs(n - p["face"]) > 200 and abs(n - (p["face"] - p["into"] * 80)) > 200:
                continue
            if dg["sign"] > 0 and dg["s0"] - 400 < s_along < dg["s0"] or dg["sign"] < 0 and dg["s1"] < s_along < dg["s1"] + 400:
                add(3, "Важно", f"{did} × {sw['id']}", "выключатель со стороны петель (за открытым полотном)", "регламент НК п. 3", "pib-electrical")
    # мощность
    pc = g.PN["totals"]["p_calc_kw"]
    if pc > 11:
        add(8, "Важно", "ЭМ-03", f"Pр = {pc} кВт > 11 кВт (допущение №4); выделенная мощность не подтверждена (вопрос №53)",
            "СП 256.1325800.2016 разд. 7; ТУ на техприсоединение", "заказчик → pib-electrical")
    # сумма Pр по группам
    s = round(sum(gr.get("p_calc_kw", 0) for gr in g.PN["groups"]), 2)
    if abs(s - g.PN["totals"]["p_sum_kc_kw"]) > 0.05:
        add(9, "Замечание", "panel.json totals", f"Σ Pр групп {s} ≠ p_sum_kc_kw {g.PN['totals']['p_sum_kc_kw']}", "", "pib-electrical")


# ===================================================================== 4. Мебель ↔ ВК
def check_plumbing():
    fx = g.VK["fixtures"]
    by_f = {}
    for f in fx:
        for fid in f.get("furniture", []):
            by_f.setdefault(fid, []).append(f)
    for it in ITEMS:
        n = it.get("needs", {})
        if not (n.get("water") or n.get("drain")):
            continue
        fs = by_f.get(it["id"], [])
        if not fs and it["id"] in ("F77", "F82"):
            continue                      # электрокраны узлов N1/N2 — plumbing.leak_protection.valves
        if not fs:
            add(4, "Важно", it["id"], "мокрый прибор без позиции в plumbing.fixtures", "СП 30.13330.2020", "pib-engineering")
            continue
        if n.get("water") and not any(f.get("cold") or f.get("hot") for f in fs):
            add(4, "Важно", it["id"], "нет выводов воды", "", "pib-engineering")
        if n.get("drain") and not any(f.get("drain") for f in fs):
            add(4, "Важно", it["id"], "нет вывода канализации", "", "pib-engineering")
    # уклоны: проектные и при нормальном 0,03 для Ø50
    for ln in sew.lines():
        r = sew.evaluate(ln)
        if not r["ok"]:
            add(4, "Блокер", ln["id"], f"самотёк не обеспечен: {r}", "СП 30.13330.2020", "pib-engineering")
        ln3 = dict(ln, i=0.03 if ln["dn"] == 50 else 0.02)
        r3 = sew.evaluate(ln3)
        if ln["dn"] == 50 and ln["riser"] == "U6":
            add(4, "Важно" if ln["id"] == "S1" else "Замечание", ln["id"],
                f"принят уклон {ln['i']} (Ø50). При нормальном 0,03: перепад {r3['drop']} мм, допустимый лоток тройника ≤ "
                f"{r3['tee_max']} (при 0,02 — ≤ {r['tee_max']}); при допущении −20 самотёк {'есть' if r3['ok'] else 'НЕТ'}",
                "СП 30.13330.2020 (нормальный уклон Ø50 — 0,03; 0,02 — наименьший); СНиП 2.04.01-85* п. 18.2", "pib-engineering")
    s1 = sew.evaluate(sew.lines()[0])
    if s1["tee_max"] < 5:
        add(4, "Важно", "S1 душ / подиум +80", f"запас по отметке лотка U6 {s1['tee_max']} мм — критерий выпуска подиума +80 "
            "зависит от обмера (K-15)", "D18, K-15", "pib-measurement → pib-engineering")
    # отметки: подиум / порог / полотно D3
    lv = g.FL["levels"]
    d3 = next(i for i in g.FL["doors"]["items"] if i["door"] == "D3")
    thr = int(re.search(r"\+(\d+)", d3["threshold"]).group(1))
    if thr < lv["R5"] + 10:
        add(7, "Важно", "D3", f"порог +{thr} не выше пола ванной +{lv['R5']} на 10", "D20", "pib-finishes")
    if d3["leaf_bottom"] < thr + 10:
        add(7, "Важно", "D3", f"низ полотна +{d3['leaf_bottom']} — зазор над порогом < 10", "D20", "pib-furniture")
    heads = {i["door"]: i.get("box_head") for i in g.FL["doors"]["items"] if i["door"] in ("D1", "D2", "D3", "D4")}
    if len(set(heads.values())) > 1:
        add(7, "Замечание", "D1–D4", f"разные верхи коробок {heads}", "D20", "pib-furniture")
    # устаревшие данные в planning.json (до D18/D20/D23)
    pj = json.dumps(g.PL, ensure_ascii=False)
    stale = [k for k in ("пандус", "x≈5990", "+1050..+1450") if k in pj]
    if stale:
        add(4, "Замечание", "planning.json (D3, bathroom, sewer, handoff)", f"остались формулировки до D18/D20/D23: {stale}",
            "D18, D20, D23", "pib-planning")


# ===================================================================== 5. ЭО ↔ потолки
def ceiling_zone(pt):
    for z in g.CE["zones"]:
        if "rect" in z:
            x1, y1, x2, y2 = z["rect"]
            if x1 <= pt[0] <= x2 and y1 <= pt[1] <= y2:
                return z
        elif "poly" in z and g._binding_text_solid is not None:
            from shapely.geometry import Polygon
            if Polygon(z["poly"]).buffer(1).contains(Point(pt)):
                return z
    return None


def check_ceilings():
    slab = 2750
    for l in EL["lights"]:
        if l.get("type") != "spot":
            continue
        z = ceiling_zone(l["pos"])
        if not z:
            add(5, "Важно", l["id"], "встроенный светильник вне зоны потолка ceilings.json", "", "pib-finishes / pib-electrical")
            continue
        plenum = slab - z["level"] - 12.5
        if l["room"] == "R7":
            plenum = 187.5   # по ceilings.json (утеплённый потолок, допущение №51)
        if plenum < 80:
            add(5, "Блокер", l["id"], f"пленум {plenum} < 80 под встроенный спот", "D19", "pib-finishes / pib-electrical")
        h = l.get("height", 0) + (80 if l["room"] == "R5" else 0)
        if h != z["level"]:
            add(5, "Замечание", l["id"], f"h {h} ≠ отметке потолка {z['level']}", "D19", "pib-electrical")
    for lc in g.CE.get("light_check", []):
        cur = next((l for l in EL["lights"] if l["id"] == lc["id"]), None)
        if cur and cur["height"] != lc["electrical_height"]:
            add(5, "Замечание", f"ceilings.json light_check {lc['id']}", f"electrical_height {lc['electrical_height']} устарел "
                f"(electrical.json {cur['height']}) — CAD-06", "", "pib-finishes")
    for p in g.CE.get("other_ceiling_points", []):
        cur = next((v for v in EL["low_voltage"] if v["id"] == p["id"]), None) or FI.get(p["id"])
        hv = cur.get("height", cur.get("z")) if cur else None
        tgt = int(re.search(r"(\d{4})", p["action"]).group(1))
        if hv is not None and abs(hv - tgt) > 50:
            add(5, "Замечание", p["id"], f"h {hv}, по потолкам требуется {tgt} (CAD-07)", "D19", "pib-electrical")


# ===================================================================== 6. ОВ ↔ потолки/мебель
def check_hvac():
    levels = g.CE["levels_summary"]
    for it in ITEMS:
        top = zr(it)[1]
        lim = levels.get(it["room"])
        if it["room"] == "R5":
            lim = lim - 80 if lim else lim      # высоты мебели ванной — от пола ванной
        if lim and top > lim + 5 and it["id"] not in ("F90", "F32"):
            add(6, "Важно", it["id"], f"верх {top} выше потолка {it['room']} ({lim})", "D19, K-08", "pib-furniture")
    # опуски hvac → ceilings
    boxes = g.CE["boxes"]
    for d in g.HV["ceiling_drops_to_finishes"]:
        if d.get("bottom") and d["room"].startswith("R3") and "W10" in d["what"]:
            cb2 = next(b for b in boxes if b["id"] == "CB-2")
            if cb2["bottom"] != d["bottom"]:
                add(6, "Замечание", "CB-2", f"низ короба {cb2['bottom']} ≠ hvac {d['bottom']}", "K-12", "pib-finishes")
            if cb2["rect"][1] != d["rect"][0][1]:
                add(6, "Замечание", "CB-2 / hvac.json", f"начало короба y {cb2['rect'][1]} ≠ hvac y {d['rect'][0][1]} "
                    "(принято K-12: y 350..620 — над пеналом +2400) — актуализировать hvac.json", "K-12", "pib-engineering")
    # вентканалы и решётки
    for u in g.M["utilities"]:
        if u["type"] == "vent_shaft" and u["id"] == "U12":
            (a, b), (c, d) = u["rect"]
            for it in ITEMS:
                if ov2(rect(it), (a, b, c, d)) > 1500:
                    add(6, "Блокер", it["id"], "перекрывает вентканал U12", "СП 54.13330.2022 п. 9.x; ПП 170", "pib-furniture")
        if u["type"] == "vent_grille":
            x, y = u["pos"]
            for it in ITEMS:
                x1, y1, x2, y2 = rect(it)
                if x1 - 50 <= x <= x2 + 50 and y1 - 150 <= y <= y2 + 150 and zr(it)[1] > 2290:
                    add(6, "Блокер", it["id"], "перекрывает решётку U13", "", "pib-furniture")
    add(6, "Замечание", "U13 / CB-2", "решётка естественной вытяжки кухни U13 (+2300..+2450) оказывается внутри короба CB-2 "
        "(низ +2290); естественная вытяжка — только через вентрешётку HC-2 200×150 (≥ 0,02 м²). Подтвердить живое сечение ≥ "
        "сечения решётки U13 и работу при выключенной вытяжке; врезку механической вытяжки в естественный канал — согласовать с УК",
        "СП 60.13330.2020 п. 7.x; ПП 170 п. 1.7.2; planning-compliance п. 10", "pib-engineering / pib-finishes")


# ===================================================================== 7. Отделка
def check_finishes():
    t = (ROOT / "04-specs/finish-schedule.md").read_text(encoding="utf-8")
    for rid in ("R1", "R2", "R3", "R4", "R5", "R6", "R7"):
        row = next((ln for ln in t.splitlines() if ln.startswith(f"| {rid} ")), None)
        if not row:
            add(7, "Важно", rid, "нет строки в ведомости отделки СП-01", "ГОСТ 21.501-2018", "pib-specs-estimate")
            continue
        cells = [c.strip() for c in row.split("|")[1:-1]]
        if not cells[1] or not cells[3] or not cells[7] or cells[7] == "—":
            add(7, "Важно", rid, "не заполнен потолок/стены/пол", "ГОСТ 21.501-2018", "pib-specs-estimate")
        if rid in ("R5", "R6") and "ГИ" not in row:
            add(7, "Важно", rid, "нет гидроизоляции в ведомости", "СП 29.13330.2011 п. 4.x", "pib-finishes")
    # площади полов СП-01 ↔ помещения
    fq = g.FQ
    for r in g.PL["rooms"]:
        pass
    # электро-ТП ↔ спецификация
    spec = (ROOT / "04-specs/spec-heating-hvac.md").read_text(encoding="utf-8")
    for m in EL["floor_heating"]["mats"]:
        mm = re.search(rf"\| ([\d,\.]+) м² \({m['id']}\)", spec) or re.search(rf"([\d\.]+) м² \({m['id']}\)", spec)
        if mm:
            sa = float(mm.group(1).replace(",", "."))
            if abs(sa - m["area_m2"]) > 0.15:
                add(9, "Замечание", m["id"], f"мат в СП-04.2 {sa} м² ≠ площадь раскладки {m['area_m2']} м² "
                    f"(мощность {m['power_kw']} кВт в щите → по спецификации {sa*0.15:.2f} кВт)", "", "pib-specs-estimate / pib-electrical")


# ===================================================================== 8. Нормы (ванная)
def check_bath_zones():
    # фактическая точка выхода воды — кронштейн верхнего душа на облицовке VK-C1 (АР-13: y 5150, h 2150)
    outlet = (7446, 5150)
    bath = (5841, 3800, 7541, 4550)
    for s in EL["sockets"]:
        if s["room"] != "R5" or s["type"] == "wire_out":
            continue
        x, y = s["pos"]
        d_sh = math.hypot(x - outlet[0], y - outlet[1])
        dx = max(bath[0] - x, 0, x - bath[2])
        dy = max(bath[1] - y, 0, y - bath[3])
        d_b = math.hypot(dx, dy)
        lvl = "ОК" if d_sh >= 1200 and d_b >= 600 else "НАРУШЕНИЕ"
        if lvl != "ОК":
            add(8, "Блокер", s["id"], f"розетка в зоне 1/2: {d_b:.0f} от ванны, {d_sh:.0f} от выхода воды душа",
                "ГОСТ Р 50571.7.701-2013 п. 701.512.3; ПУЭ 7.1.48", "pib-electrical")
    # точка в скрипте ЭМ
    src = (ROOT / "tools/check_electrical_needs.py").read_text(encoding="utf-8")
    if "shower_outlet = (7091, 5033)" in src:
        add(8, "Замечание", "tools/check_electrical_needs.py", "зона 1 душа считается от центра поддона (7091, 5033), "
            "а не от фактической точки выхода воды — кронштейна верхнего душа на VK-C1 (7446, 5150, h 2150 по АР-13). "
            "Результат не меняется (P-V01 2,19 м, P-V02 2,55 м), но критерий надо привести к норме",
            "ГОСТ Р 50571.7.701-2013 рис. 701.2", "pib-electrical")
    rcd = {gr["id"]: gr["rcd"] for gr in g.PN["groups"]}
    for gid in ("C3", "C12", "C13", "C14"):
        if "мА" not in rcd.get(gid, ""):
            add(8, "Блокер", gid, "цепь мокрого помещения без УЗО ≤ 30 мА", "ГОСТ Р 50571.7.701-2013 п. 701.411.3.3", "pib-electrical")
    if "10 мА" not in rcd.get("C12", ""):
        add(8, "Важно", "C12", "розетки ванной не на 10 мА (D16)", "D16", "pib-electrical")
    if not any("ДУП" in x for x in g.PN["rcd_policy"]):
        add(8, "Блокер", "ЭМ-03", "нет ДУП ванной", "ГОСТ Р 50571.7.701-2013 п. 701.415.2", "pib-electrical")
    f75 = FI.get("F75")
    if f75 and "30 мА" in json.dumps(f75.get("needs", {}), ensure_ascii=False):
        add(8, "Замечание", "F75 (furniture.json)", "в needs указано «УЗО 30 мА», по D16/panel.json — АВДТ 10 мА (C12)", "D16", "pib-furniture")


# ===================================================================== 9. Смета
def check_estimate():
    specs = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "04-specs").glob("spec-*.md"))
    miss = []
    for s in EL["sockets"]:
        if not re.search(rf"\b{re.escape(s['id'])}\b", specs):
            miss.append(s["id"])
    for l in EL["lights"]:
        if l["id"] not in specs:
            miss.append(l["id"])
    for sw in EL["switches"]:
        if not re.search(rf"\b{sw['id']}\b", specs):
            miss.append(sw["id"])
    for it in ITEMS:
        if not re.search(rf"\b{it['id']}\b", specs):
            miss.append(it["id"])
    if miss:
        add(9, "Важно", "спецификации", f"нет в спецификациях: {miss}", "", "pib-specs-estimate")
    # механизмы розеток: штучный пересчёт
    n2 = sum(2 if "×2" in s["type"] else 1 for s in EL["sockets"] if s["type"].startswith("2P+PE") and s["id"] != "P-SS1")
    m = re.search(r"Розетка 2П\+З 16 А со шторками.*?\| (\d+) \| шт", specs)
    if m and int(m.group(1)) != n2:
        add(9, "Важно", "СП-03.2 поз. 1", f"механизмов {m.group(1)} ≠ {n2} по ЭМ-01", "", "pib-specs-estimate")
    ls = len(g.VK["leak_protection"]["sensors"])
    m = re.search(r"Датчик протечки проводной.*?\| (\d+) \| шт", specs)
    if m and int(m.group(1)) != ls:
        add(9, "Важно", "датчики протечки", f"{m.group(1)} ≠ {ls}", "", "pib-specs-estimate")
    # бюджет
    est = (ROOT / "05-estimate/estimate.md").read_text(encoding="utf-8")
    for name, lim in (("Ремонт", 5_000_000), ("Мебель \\+ техника", 1_500_000)):
        m = re.search(rf"\| {name} \| [\d ]+ \| ([\d ]+) \| ([\d ]+) \|", est)
        if m:
            wo = int(m.group(1).replace(" ", ""))
            wr = int(m.group(2).replace(" ", ""))
            add(9, "Важно", f"СМ-01 «{name.replace(chr(92), '')}»", f"смета {wo:,} ₽ без резерва / {wr:,} ₽ с резервом 10 % при лимите "
                f"{lim:,} ₽ (+{(wr/lim-1)*100:.1f} %)".replace(",", " "), "бриф; program п. 4", "заказчик → pib-specs-estimate")
    # арифметика этапов
    rows = re.findall(r"^\| Э\d\d \| .*? \| ([\d ]+) \| ([\d ]+) \| ([\d ]+) \|", est, re.M)
    s = sum(int(r[2].replace(" ", "")) for r in rows)
    m = re.search(r"\*\*Итого без резерва\*\* \| \*\*[\d ]+\*\* \| \*\*[\d ]+\*\* \| \*\*([\d ]+)\*\*", est)
    if m and abs(int(m.group(1).replace(" ", "")) - s) > 5:
        add(9, "Важно", "СМ-01 раздел 1", f"Σ этапов {s} ≠ итог {m.group(1)}", "", "pib-specs-estimate")
    m1 = re.search(r"Встроенные шкафы прихожей и спальни.*?\| Ремонт \| ([\d ]+) \|", est)
    m2 = re.search(r"\| СП-02\.1 \| .*? \| ([\d ]+) \|", est)
    if m1 and m2 and m1.group(1).strip() != m2.group(1).strip():
        add(9, "Замечание", "СМ-01 «Границы бюджетов»", f"встроенная мебель {m1.group(1).strip()} ₽ ≠ СП-02.1 «Ремонт» {m2.group(1).strip()} ₽",
            "", "pib-specs-estimate")


def main():
    check_completeness()
    check_geometry()
    check_electrical()
    check_plumbing()
    check_ceilings()
    check_hvac()
    check_finishes()
    check_bath_zones()
    check_estimate()
    seen, uniq = set(), []
    for f in FINDINGS:
        k = (f["obj"], f["group"]) if f["group"] == 3 and " × S" in f["obj"] else (f["obj"], f["text"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(f)
    FINDINGS[:] = uniq
    order = {"Блокер": 0, "Важно": 1, "Замечание": 2}
    FINDINGS.sort(key=lambda f: (order[f["level"]], f["group"]))
    cnt = {k: sum(1 for f in FINDINGS if f["level"] == k) for k in order}
    for f in FINDINGS:
        print(f"[{f['level']}] гр.{f['group']} {f['obj']}: {f['text']}  ({f['ref']}) → {f['who']}")
    print("ИТОГО:", cnt)
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(FINDINGS, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if cnt["Блокер"] else 0


if __name__ == "__main__":
    sys.exit(main())
