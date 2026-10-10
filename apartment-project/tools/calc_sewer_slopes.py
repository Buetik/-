#!/usr/bin/env python3
"""pib-engineering: расчёт уклонов внутренней канализации (ВК), вариант планировки D1.

Редакция 2026-10-10: решение D26 «трап в уровень с полом» (требование заказчика) + НК-05.

Что считает:
  * трассы S1–S7: длина, перепад, лоток у прибора и у стояка, предельная отметка лотка
    отвода тройника К1 («тройник ≤»), при которой прибор идёт самотёком;
  * проектный уклон Ø50 — НОРМАЛЬНЫЙ 0,03 (СП 30.13330.2020, разд. 8); Ø110 — 0,02 (нормальный);
    0,02 для Ø50 — только как допустимый минимум для S1 (L ≤ 0,3 м, в кармане/коробе, без поворотов
    в горизонтали) и только если лоток U6 по обмеру не проходит при 0,03;
  * сценарии пола ванной:
      LEVEL (D26, база): сухая зона ±0 по существующей стяжке (−20) + пирог плитки 20;
          в зоне душа и по трассе S1 до стояка — ЛОКАЛЬНЫЙ демонтаж стяжки до плиты (−100)
          после тепловизора; уклон пола душа 1,5 % от линии стекла (±0) к линейному трапу;
      WALL (D26, вариант 2): пристенный трап в облицовке VK-C1; демонтаж стяжки только в полосе
          под облицовкой; пол душа по старой стяжке: −2 у стены … +10 на линии стекла;
      PODIUM (D18, запасной): пол ванной +F, всё поверх стяжки −20;
  * таблицу «лоток U6 → вариант».

Отметки — мм от УЧП (±0.000 = плита +100). Плита −100, верх существующей стяжки −20.
Запуск: python3 tools/calc_sewer_slopes.py
"""
import math

SLAB = -100
SCREED_TOP = -20
WALL = 2
PLINTH_TOP = 150
I50, I50_MIN, I110 = 0.03, 0.02, 0.02
SHOWER_SLOPE = 0.015
SHOWER_ENTRY_X = 6641
DRAIN_X = 7400            # ось линейного трапа у облицовки VK-C1 (грань x 7446)
CLAD_X = 7446
TRAP_OUT = 8              # лоток выпуска над низом корпуса трапа
BEDDING = 5               # мин. подливка под корпус трапа
TEE_ASSUMED = -80         # [ДОПУЩЕНИЕ] отвод тройника К1 на уровне стяжки застройщика (типично 1 этаж: −70…−90); обмер З-04 обязателен (ранее −20 — консервативно для D18)
TRAP_H_BASE = 65          # база D26-1: ультраплоский трап H ≤ 65
OD = {50: 50, 110: 110}

# реальные серии низких/ультраплоских трапов — ориентировочно, СВЕРИТЬ ПО ПАСПОРТУ
TRAPS = [
    {"model": "Geberit CleanLine20/30 + монтажный комплект низкий", "h": 65, "dn": 40, "q_ls": 0.4, "type": "линейный в пол"},
    {"model": "TECEdrainline + сифон плоский DN 40", "h": 67, "dn": 40, "q_ls": 0.5, "type": "линейный в пол / пристенный"},
    {"model": "Alcadrain APZ1101 Low (низкий)", "h": 60, "dn": 40, "q_ls": 0.4, "type": "линейный в пол"},
    {"model": "Pestan Confluo Premium / Frameless Line с низким сифоном", "h": 70, "dn": 40, "q_ls": 0.5, "type": "линейный в пол / у стены"},
    {"model": "Viega Advantix Vario (низкий корпус)", "h": 70, "dn": 40, "q_ls": 0.4, "type": "линейный в пол, укорачиваемый"},
    {"model": "Geberit настенный трап для душа в уровень с полом (в инсталляционной стене)", "h": 80, "dn": 50, "q_ls": 0.5, "type": "пристенный (вариант 2)"},
]


def shower_floor(x, entry=0.0):
    if x <= SHOWER_ENTRY_X:
        return entry
    return entry - SHOWER_SLOPE * (min(x, DRAIN_X) - SHOWER_ENTRY_X)


def bath_lines(ffl, scenario, trap_h=70, i_shower=I50):
    """Трассы ванной. ffl — отметка сухой зоны ванной; z_min — нижний предел лотка на трассе."""
    if scenario == "WALL":
        grate = -2.0                               # пол у стены по старой стяжке
        z_min_s1 = SLAB + WALL                     # полоса под облицовкой демонтирована до плиты
    else:
        grate = shower_floor(DRAIN_X, ffl)
        z_min_s1 = (SLAB + WALL) if scenario == "LEVEL" else (SCREED_TOP + WALL)
    trap_bottom = grate - trap_h
    return [
        dict(id="S1", fixture="P04 душ: линейный трап (выпуск у северного торца) → короб U10" if scenario != "WALL" else "P04 душ: пристенный трап в VK-C1 → короб U10",
             riser="U6", dn=50, i=i_shower, z_out=round(trap_bottom + TRAP_OUT, 1), grate=round(grate, 1), trap_bottom=round(trap_bottom, 1),
             z_min=z_min_s1, path=[(DRAIN_X if scenario != "WALL" else 7490, 5440), (7400, 5516), (7400, 5666), (7438, 5666)],
             note="выпуск сразу в короб U10; в стояк — в нижнюю точку (эксцентрический переход 110/50, лотки совмещены)"),
        dict(id="S2", fixture="P03 ванна: сифон у правого торца → под ванной → полость облицовки VK-C1 → короб U10",
             riser="U6", dn=50, i=I50, z_out=ffl + 70, z_min=(SLAB + WALL) if scenario in ("LEVEL", "WALL") else (SCREED_TOP + WALL),
             path=[(7350, 4175), (7490, 4175), (7490, 4550), (7490, 5516), (7490, 5600), (7438, 5600), (7438, 5666)],
             note="под ванной (ванна на ножках, экран с ревизией H6) и в полости облицовки — под полом не проходит"),
        dict(id="S3", fixture="P01 унитаз подвесной (инсталляция, ось x 6250)", riser="U6", dn=110, i=I110, z_out=ffl + 230 - 55,
             z_min=SCREED_TOP + WALL, path=[(6250, 5770), (6750, 5770), (6750, 5640), (7383, 5640)],
             note="короб инсталляции → короб-перемычка VK-C2 → U10; обход стояков В1/Т3/Т4 с юга"),
        dict(id="S4", fixture="P02 раковина в тумбе 900 (выпуск +550)", riser="U6", dn=50, i=I50, z_out=ffl + 550,
             z_min=SCREED_TOP + WALL, path=[(5250, 5815), (6700, 5815), (6700, 5640), (7383, 5640)],
             note="за тумбой над коллектором U14 (зазор ≥ 50) и в коробе инсталляции"),
    ]


def other_lines():
    return [
        dict(id="S5", fixture="P06 мойка кухни (+ ПММ через сифон)", riser="U1", dn=50, i=I50, z_out=450, z_min=SCREED_TOP + WALL, plinth=True,
             path=[(2490, 60), (4090, 60), (4216, 60), (4216, 101)],
             note="в цоколе вдоль W3 (основание 620, K-06), через W10 в короб U5; W3 не штробить"),
        dict(id="S6", fixture="P09 хозмойка 450", riser="U1", dn=50, i=I50, z_out=450, z_min=SCREED_TOP + WALL,
             path=[(4475, 450), (4326, 450), (4326, 101)], note="внутри короба U5"),
        dict(id="S7", fixture="P10 СМА + конденсат СМ", riser="U1", dn=50, i=I50, z_out=560, z_min=SCREED_TOP + WALL, plinth=True,
             path=[(5170, 60), (4475, 60), (4326, 101)], note="в цоколе карго/тумбы хозмойки; вариант — старый выпуск WC через 110/50"),
    ]


def length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])) / 1000


def evaluate(ln, tee=TEE_ASSUMED):
    L = length(ln["path"])
    drop = ln["i"] * L * 1000
    tee_max = ln["z_out"] - drop                       # предельный лоток тройника для самотёка
    z_end = max(tee, ln["z_min"])                      # фактически у стояка (ниже — вертикальный спуск в коробе)
    z_start = z_end + drop
    ok = z_start <= ln["z_out"] and tee <= tee_max
    plinth_ok = True
    if ln.get("plinth"):
        plinth_ok = z_start + OD[ln["dn"]] <= PLINTH_TOP
        ok = ok and plinth_ok
    if "trap_bottom" in ln:
        ok = ok and ln["trap_bottom"] >= SLAB + BEDDING if ln["z_min"] < SCREED_TOP else ok and ln["trap_bottom"] >= SCREED_TOP
    return dict(L=round(L, 2), drop=round(drop, 1), z_out=round(ln["z_out"], 1), z_start=round(z_start, 1), z_end=round(z_end, 1),
                tee_max=round(tee_max, 1), head=round(ln["z_out"] - z_start, 1), plinth_ok=plinth_ok, ok=ok)


def s1_limit(scenario, trap_h, i, ffl=0):
    ln = bath_lines(ffl, scenario, trap_h, i)[0]
    r = evaluate(ln)
    fits = ln["trap_bottom"] >= (SLAB + BEDDING if scenario in ("LEVEL", "WALL") else SCREED_TOP)
    return dict(scenario=scenario, trap_h=trap_h, i=i, grate=ln["grate"], trap_bottom=ln["trap_bottom"], z_out=ln["z_out"],
                tee_max=r["tee_max"], trap_fits=fits)


def podium_formula(tee, trap_h=65, i=I50):
    """D18-тип: пол ванной F поверх старой стяжки. Требуется F ≥ tee + ΔS1 и низ трапа ≥ −20."""
    s1_len = length(bath_lines(0, "PODIUM")[0]["path"])
    grate_off = SHOWER_SLOPE * (DRAIN_X - SHOWER_ENTRY_X)
    f_tee = tee + i * s1_len * 1000 + trap_h - TRAP_OUT + grate_off
    f_trap = SCREED_TOP + trap_h + grate_off
    return math.ceil(max(f_tee, f_trap) / 5) * 5


def report():
    base = [*bath_lines(0, "LEVEL", TRAP_H_BASE), *other_lines()]
    lines = []
    for ln in base:
        r = evaluate(ln)
        lines.append({**{k: ln[k] for k in ("id", "fixture", "riser", "dn", "i", "note")}, "path": [list(p) for p in ln["path"]], **r,
                      **({"grate": ln["grate"], "trap_bottom": ln["trap_bottom"]} if "grate" in ln else {})})
    limits = [s1_limit("LEVEL", h, i) for h in (60, 65, 70) for i in (I50, I50_MIN)] + \
             [s1_limit("WALL", 80, i) for i in (I50, I50_MIN)]
    lv = {(l["trap_h"], l["i"]): l["tee_max"] for l in limits if l["scenario"] == "LEVEL"}
    wl = {l["i"]: l["tee_max"] for l in limits if l["scenario"] == "WALL"}
    table = [
        {"tee_u6": f"≤ {lv[(70, I50)]:+.0f}", "solution": "D26-1: пол ±0, линейный трап H ≤ 70 (любая из серий), S1 i = 0,03", "pump": False, "podium": 0},
        {"tee_u6": f"{lv[(70, I50)]:+.0f} … {lv[(65, I50)]:+.0f}", "solution": "D26-1: пол ±0, трап H ≤ 65 (Geberit CleanLine низкий / Alcadrain Low), S1 i = 0,03", "pump": False, "podium": 0},
        {"tee_u6": f"{lv[(65, I50)]:+.0f} … {lv[(60, I50_MIN)]:+.0f}", "solution": "D26-1: пол ±0, трап H 60–65, S1 i = 0,02 (допустимый минимум, L 0,26 м, обоснование — plumbing.json)", "pump": False, "podium": 0},
        {"tee_u6": f"> {lv[(60, I50_MIN)]:+.0f}", "solution": "D26-3: пол ±0, трап H ≤ 70 + насос SFA Sanishower Flat в кармане на плите; ИЛИ (выбор заказчика) подиум по формуле F ≥ лоток + 76 (H 65, i 0,03): лоток −40 → +40, −20 → +60, 0 → +80, +20 → +100", "pump": True, "podium": "по формуле"},
        {"tee_u6": "контуры ТП в зоне душа, полоса у W14 свободна", "solution": f"D26-2: пристенный трап в VK-C1 (демонтаж только полосы 95 под облицовкой), лоток U6 ≤ {wl[I50]:+.0f} (0,03) / {wl[I50_MIN]:+.0f} (0,02); пол душа −2 у стены … +10 у стекла", "pump": False, "podium": 0},
        {"tee_u6": "контуры ТП и в зоне душа, и у W14", "solution": f"пол в уровень невозможен: запасной D18 — подиум F ≥ max(лоток + 76; +60) (трап H 65 поверх стяжки −20), при лотке −20 → +{podium_formula(-20)}, 0 → +{podium_formula(0)}; насос не помогает (нет глубины под корпус трапа)", "pump": False, "podium": "D18"},
    ]
    return {"assumptions": {"slab": SLAB, "screed_top": SCREED_TOP, "tee_invert_assumed": TEE_ASSUMED, "i_50": I50, "i_50_min": I50_MIN, "i_110": I110,
                            "shower_slope": SHOWER_SLOPE, "bath_floor_dry": 0, "trap_out_above_bottom": TRAP_OUT, "trap_h_base": TRAP_H_BASE},
            "lines": lines, "s1_limits": limits, "tee_table": table, "traps": TRAPS,
            "podium_examples": {t: podium_formula(t) for t in (-60, -40, -20, 0, 20)}}


if __name__ == "__main__":
    R = report()
    print(f"{'id':4} {'Ø':>4} {'L,м':>5} {'i':>5} {'Δh':>5} {'лоток пр.':>9} {'тройник≤':>9} ok")
    for r in R["lines"]:
        print(f"{r['id']:4} {r['dn']:>4} {r['L']:>5} {r['i']:>5} {r['drop']:>5} {r['z_out']:>9} {r['tee_max']:>9} {r['ok']}  {r['fixture']}")
    print("Пределы S1:")
    for l in R["s1_limits"]:
        print("  ", l)
    print("Лоток U6 → вариант:")
    for t in R["tee_table"]:
        print("  ", t["tee_u6"], "→", t["solution"])
    print("Подиум D18 при лотке:", R["podium_examples"])
