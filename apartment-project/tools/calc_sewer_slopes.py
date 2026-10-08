#!/usr/bin/env python3
"""pib-engineering: расчёт уклонов внутренней канализации (ВК) квартиры — вариант D1.

Что считает:
  * длину каждой трассы (по ломаной в плане + вертикальные участки не учитываются в уклоне);
  * перепад при проектном уклоне, отметку лотка у прибора и у стояка;
  * проверку «хватает ли напора» (лоток выпуска прибора ≥ лоток трассы в начале);
  * проверку защитного слоя над трубой в подиуме (участки под полом, по которому ходят);
  * проверку высоты цоколя мебели (участки в цоколях кухни/постирочной);
  * чувствительность: какая отметка чистого пола ванной (подиум) нужна при разной
    отметке лотка врезки в стояк К1 (отметка неизвестна — вопрос на обмер).

Отметки — мм от УЧП квартиры (±0.000 = плита +100). Верх существующей стяжки с водяным
ТП = −20 (резать/штробить запрещено, D3/D4) → труба не может лежать ниже −20 + стенка.
Нормы: СП 30.13330.2020 (уклоны: Ø50 — не менее 0,02 (норм. 0,03), Ø110 — не менее
0,012 (норм. 0,02)); защитный слой над трубой в подиуме — принят 30 мм фиброармированной
стяжки + 20 мм гидроизоляция/клей с матом ТП/плитка [ДОПУЩЕНИЕ, подтверждает pib-finishes].

Запуск: python3 tools/calc_sewer_slopes.py   (печатает таблицы; функции импортирует gen_engineering.py)
"""
import math

SCREED_TOP = -20          # верх существующей стяжки с водяным ТП
COVER = 50                # над верхом трубы до чистого пола в подиуме (30 стяжка + 20 гидро/клей/плитка)
PLINTH_TOP = 150          # верх зоны цоколя мебели (цоколь 160)
TEE_ASSUMED = -20         # [ДОПУЩЕНИЕ] лоток отвода тройника К1 U1/U6 (обмер!)
FFL_BATH = 80             # подиум ванной (planning.json D1)
SHOWER_SLOPE = 0.015      # уклон пола душа к лотку
SHOWER_ENTRY_X = 6641     # вход в душ (плоскость стекла) — отметка = пол ванной
DRAIN_X = 7400            # ось линейного лотка (перед облицовкой W14 толщ. ≈ 95 с плиткой)
TRAP_H = 70               # монтажная высота низкого трапа (верх решётки — низ корпуса), паспорт
TRAP_OUT = 8              # лоток выпуска над низом корпуса трапа

OD = {50: 50, 110: 110, 40: 40}
WALL = 2


def shower_floor(x, ffl):
    """Отметка чистого пола в душе (однонаправленный уклон к лотку у W14)."""
    if x <= SHOWER_ENTRY_X:
        return ffl
    return ffl - SHOWER_SLOPE * (min(x, DRAIN_X) - SHOWER_ENTRY_X)


def bath_floor(x, y, ffl):
    if 6641 <= x <= 7541 and 4550 <= y <= 5516:
        return shower_floor(x, ffl)
    return ffl


def lines(ffl=FFL_BATH):
    """Трассы. path: [(x, y, kind_next)], kind — тип участка до следующей точки:
    free — под ванной / в коробе / в облицовке / в инсталляции (только ограничение по стяжке);
    podium — под полом с/у, по которому ходят (защитный слой); plinth — в цоколе мебели;
    trap — узел трапа. z_out — лоток выпуска прибора (абс.)."""
    grate = shower_floor(DRAIN_X, ffl)
    return [
        dict(id="S1", fixture="P04 душ: низкий линейный трап у облицовки W14 (выпуск у северного торца)",
             riser="U6", dn=50, i=0.02, z_out=round(grate - TRAP_H + TRAP_OUT, 1),
             trap_bottom=round(grate - TRAP_H, 1), grate=round(grate, 1),
             path=[(7400, 5440, "trap"), (7400, 5516, "free"), (7400, 5666, "free"), (7438, 5666, None)],
             note="выпуск трапа сразу в короб U10 через грань y=5516; в стояк — в нижнюю точку (эксцентрический переход 110/50, лотки совмещены)"),
        dict(id="S2", fixture="P03 ванна: сифон у правого торца (x≈7350) → под ванной → в облицовке W14 → короб U10",
             riser="U6", dn=50, i=0.02, z_out=ffl + 70,
             path=[(7350, 4175, "free"), (7490, 4175, "free"), (7490, 4550, "free"), (7490, 5516, "free"),
                   (7490, 5600, "free"), (7438, 5600, "free"), (7438, 5666, None)],
             note="участок y 4550..5516 — в полости облицовки W14 (душ), под полом не проходит; без соединений в облицовке"),
        dict(id="S3", fixture="P01 унитаз подвесной (инсталляция, ось x 6250)",
             riser="U6", dn=110, i=0.02, z_out=ffl + 230 - 55,
             path=[(6250, 5770, "free"), (6750, 5770, "free"), (6750, 5640, "free"), (7383, 5640, None)],
             note="в коробе инсталляции и низком коробе-перемычке x 6641..6863 (h до +450 от пола ванной); обход стояков В1/Т3/Т4 (y 5791) с юга"),
        dict(id="S4", fixture="P02 раковина в тумбе 900 (выпуск +550 от пола ванной)",
             riser="U6", dn=50, i=0.02, z_out=ffl + 550,
             path=[(5250, 5815, "free"), (6700, 5815, "free"), (6700, 5640, "free"), (7383, 5640, None)],
             note="за тумбой над коллектором U14 (верх +400 УЧП) и в коробе инсталляции; над U14 зазор ≥ 50"),
        dict(id="S5", fixture="P06 мойка кухни (+ ПММ через сифон мойки)",
             riser="U1", dn=50, i=0.02, z_out=450,
             path=[(2490, 60, "plinth"), (4090, 60, "free"), (4216, 60, "free"), (4216, 101, None)],
             note="в цоколе вдоль W3 (W3 не штробить — стена МОП), за ПММ и пеналом холодильника, через W10 (гильза) в короб U5"),
        dict(id="S6", fixture="P09 хозмойка 450 (выпуск на грани короба U5)",
             riser="U1", dn=50, i=0.02, z_out=450,
             path=[(4475, 450, "free"), (4326, 450, "free"), (4326, 101, None)],
             note="внутри короба U5"),
        dict(id="S7", fixture="P10 СМА (сифон в карго, + конденсат сушильной машины)",
             riser="U1", dn=50, i=0.02, z_out=560,
             path=[(5170, 60, "plinth"), (4475, 60, "free"), (4326, 101, None)],
             note="в цоколе карго/тумбы хозмойки вдоль W3; вариант — в бывший выпуск WC Ø110 через переход 110/50 под карго"),
    ]


def seg_len(p, q):
    return math.hypot(q[0] - p[0], q[1] - p[1])


def evaluate(line, tee=TEE_ASSUMED, ffl=FFL_BATH):
    od, i = OD[line["dn"]], line["i"]
    pts = line["path"]
    L = sum(seg_len(pts[k], pts[k + 1]) for k in range(len(pts) - 1)) / 1000
    z_floor_min = SCREED_TOP + WALL           # лоток не ниже, чем стяжка + стенка
    z_end = max(tee, z_floor_min)             # у стояка: если тройник ниже — вертикальный спуск в коробе
    z_start = z_end + i * L * 1000
    head = line["z_out"] - z_start            # запас напора у прибора (≥ 0 — самотёк)
    # проверки по участкам
    viol_cover, viol_plinth = 0.0, 0.0
    s = 0.0
    for k in range(len(pts) - 1):
        p, q, kind = pts[k], pts[k + 1], pts[k][2]
        l = seg_len(p, q)
        for t in (0.0, 0.5, 1.0):
            x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
            inv = z_start - i * (s + l * t)
            if kind == "podium":
                need = inv + od + COVER - bath_floor(x, y, ffl)
                viol_cover = max(viol_cover, need)
            if kind == "plinth":
                viol_plinth = max(viol_plinth, inv + od - PLINTH_TOP)
        s += l
    ok = head >= 0 and viol_cover <= 0 and viol_plinth <= 0
    if "trap_bottom" in line and line["trap_bottom"] < SCREED_TOP:
        ok = False
    return dict(L=round(L, 2), drop=round(i * L * 1000, 1), z_out=round(line["z_out"], 1),
                z_start=round(z_start, 1), z_end=round(z_end, 1), head=round(head, 1),
                tee_max=round(line["z_out"] - i * L * 1000, 1),
                cover_short=round(max(viol_cover, 0), 1), plinth_over=round(max(viol_plinth, 0), 1), ok=ok)


def podium_required(tee, step=5):
    """Минимальная отметка пола ванной, при которой все приборы ванной (U6) идут самотёком."""
    for ffl in range(60, 205, step):
        good = True
        for ln in lines(ffl):
            if ln["riser"] != "U6":
                continue
            r = evaluate(ln, tee, ffl)
            if not r["ok"]:
                good = False
                break
        if good:
            return ffl
    return None


def bath_via_floor_check(ffl=FFL_BATH, tee=TEE_ASSUMED):
    """Отклонённый вариант: ванна (сифон у левого торца, как в furniture F66) поперёк сухой зоны
    к коробу инсталляции — показывает, почему трасса перенесена в облицовку W14."""
    ln = dict(id="S2x", fixture="ванна поперёк пола к инсталляции (отклонено)", riser="U6", dn=50, i=0.02,
              z_out=ffl + 70,
              path=[(5990, 4175, "free"), (5990, 4550, "podium"), (5990, 5691, "free"), (6750, 5691, "free"),
                    (6750, 5640, "free"), (7383, 5640, None)])
    r = evaluate(ln, tee, ffl)
    # минимальный пол для этого варианта
    need = None
    for f in range(60, 260, 5):
        ln["z_out"] = f + 70
        if evaluate(ln, tee, f)["ok"]:
            need = f
            break
    r["ffl_needed"] = need
    return r


def report():
    out = {"assumptions": {"screed_top": SCREED_TOP, "cover_over_pipe": COVER, "tee_invert_assumed": TEE_ASSUMED,
                           "ffl_bath": FFL_BATH, "shower_slope": SHOWER_SLOPE, "trap_install_height": TRAP_H},
           "lines": [], "sensitivity": [], "rejected_bath_route": bath_via_floor_check()}
    for ln in lines():
        r = evaluate(ln)
        out["lines"].append({**{k: ln[k] for k in ("id", "fixture", "riser", "dn", "i", "note")},
                             "path": [[p[0], p[1]] for p in ln["path"]], **r,
                             **({"grate": ln["grate"], "trap_bottom": ln["trap_bottom"]} if "grate" in ln else {})})
    for tee in (-60, -40, -20, 0, 20, 40, 60):
        out["sensitivity"].append({"tee_invert": tee, "ffl_bath_required": podium_required(tee),
                                   "laundry_kitchen_ok": all(evaluate(l, tee)["ok"] for l in lines() if l["riser"] == "U1")})
    return out


if __name__ == "__main__":
    R = report()
    print("Допущения:", R["assumptions"])
    print(f"{'id':4} {'Ø':>4} {'L,м':>5} {'i':>5} {'Δh':>5} {'лоток пр.':>9} {'нач.трассы':>10} {'у стояка':>8} {'запас':>6} {'тройник≤':>8} ok")
    for r in R["lines"]:
        print(f"{r['id']:4} {r['dn']:>4} {r['L']:>5} {r['i']:>5} {r['drop']:>5} {r['z_out']:>9} {r['z_start']:>10} "
              f"{r['z_end']:>8} {r['head']:>6} {r['tee_max']:>8} {r['ok']}  {r['fixture']}")
    s1 = R["lines"][0]
    print(f"Душ: решётка {s1['grate']}, низ трапа {s1['trap_bottom']} (≥ {SCREED_TOP})")
    print("Отклонённая трасса ванны поперёк пола:", R["rejected_bath_route"])
    print("Чувствительность к отметке лотка врезки К1:")
    for s in R["sensitivity"]:
        print(f"  лоток тройника {s['tee_invert']:>4} → пол ванной ≥ +{s['ffl_bath_required']}; U1 (кухня/постирочная) ok: {s['laundry_kitchen_ok']}")
