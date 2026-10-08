#!/usr/bin/env python3
"""pib-electrical: проверка раздела ЭО/ЭМ.

1) Каждая потребность furniture.json → needs.power[i] / needs.low_current[i] закрыта точкой electrical.json
   (sockets / lights / low_voltage с need_ref), силовые точки — не далее 1 м в плане от габарита изделия.
2) Ванная: розетки вне зон 0–2 (≥ 600 от ванны, ≥ 1200 от точки выхода воды душа без поддона), IP44+.
3) Каждая цепь розеток/света есть в panel.json; группы света → цепь; выключатели управляют существующими группами.
4) Электро-ТП не под ванной/душем/коллекторами (≥ 300) и не под П-диваном.
5) Щиты U15/U16 не перекрыты мебелью.
6) Расчётная мощность ≤ выделенной (15 кВт; предупреждение при > 11 кВт).
Выход: код 0 — ошибок нет (предупреждения допускаются). Запуск: python3 tools/check_electrical_needs.py
"""
import json, sys, math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FU = json.loads((ROOT / "03-drawings/furniture.json").read_text(encoding="utf-8"))
EL = json.loads((ROOT / "03-drawings/electrical.json").read_text(encoding="utf-8"))
PN = json.loads((ROOT / "03-drawings/panel.json").read_text(encoding="utf-8"))
err, warn = [], []


def rect(it):
    x, y = it["pos"]
    w, d, _ = it["size"]
    bw, bd = (w, d) if it["rotation"] in (0, 180) else (d, w)
    return x, y, x + bw, y + bd


def dist(p, r):
    dx = max(r[0] - p[0], 0, p[0] - r[2])
    dy = max(r[1] - p[1], 0, p[1] - r[3])
    return math.hypot(dx, dy)


ITEMS = {it["id"]: it for it in FU["items"]}
points = [("socket", s) for s in EL["sockets"]] + [("light", l) for l in EL["lights"]] + [("lv", v) for v in EL["low_voltage"]]
refs = {}
for kind, p in points:
    for r in p.get("need_ref", []):
        refs.setdefault(r, []).append((kind, p))
for r in refs:
    fid = r.split(".")[0]
    if fid not in ITEMS:
        err.append(f"need_ref {r}: позиции {fid} нет в furniture.json")

# 1) покрытие needs
total = covered = 0
for it in FU["items"]:
    n = it.get("needs", {})
    for key in ("power", "low_current"):
        for i, txt in enumerate(n.get(key) or []):
            total += 1
            ref = f"{it['id']}.{key}[{i}]"
            if ref not in refs:
                err.append(f"НЕ ЗАКРЫТО {ref}: {txt}")
                continue
            covered += 1
            if key == "power":
                r = rect(it)
                near = [p for k, p in refs[ref] if k in ("socket", "light")]
                if near:
                    d = min(dist(p["pos"], r) for p in near)
                    if d > 1000:
                        err.append(f"{ref}: ближайшая точка {d:.0f} мм > 1 м от {it['id']}")

# 2) ванная
bath = (5841, 3800, 7541, 4550)
shower_outlet = (7091, 5033)
for s in EL["sockets"]:
    if s["room"] != "R5" or s["type"] == "wire_out":
        continue
    d_bath = dist(s["pos"], bath)
    d_sh = math.hypot(s["pos"][0] - shower_outlet[0], s["pos"][1] - shower_outlet[1])
    if d_bath < 600:
        err.append(f"{s['id']}: розетка в зоне 2 ванны ({d_bath:.0f} мм)")
    if d_sh < 1200:
        err.append(f"{s['id']}: розетка в зоне 1 душа без поддона ({d_sh:.0f} мм)")
    if s.get("ip", "IP20") < "IP44":
        err.append(f"{s['id']}: IP ниже IP44 в ванной")
    grp = next((g for g in PN["groups"] if g["id"] == s["circuit"]), None)
    if grp and "10 мА" not in grp["rcd"] and "30 мА" not in grp["rcd"]:
        err.append(f"{s['id']}: линия ванной без УЗО")
for s in EL["sockets"]:
    if s["room"] in ("R5", "R6") and s["type"] != "wire_out" and s.get("ip") != "IP44":
        err.append(f"{s['id']}: розетка мокрого помещения без IP44")

# 3) цепи
gids = {g["id"] for g in PN["groups"]}
for s in EL["sockets"]:
    if s["circuit"] not in gids:
        err.append(f"{s['id']}: цепь {s['circuit']} отсутствует в panel.json")
lg = {g["id"]: g for g in EL["light_groups"]}
for l in EL["lights"]:
    if l["group"] not in lg:
        err.append(f"{l['id']}: группа {l['group']} не описана")
    elif lg[l["group"]]["circuit"] not in gids:
        err.append(f"{l['group']}: цепь отсутствует в щите")
for sw in EL["switches"]:
    for c in sw["controls"]:
        for k in c.split("+"):
            if k not in lg:
                err.append(f"{sw['id']}: управляет несуществующей группой {k}")
    if not (600 <= sw["height"] <= 1100):
        warn.append(f"{sw['id']}: высота {sw['height']}")
for k in lg:
    if k not in ("L12", "L13", "L17", "L18", "L20", "L21") and not any(k in c.split("+") for sw in EL["switches"] for c in sw["controls"]):
        warn.append(f"группа {k} без выключателя (проверить: датчик/сцена)")
wet_items = {"F06": "C9", "F80": ("C10", "C11")}
for g in PN["groups"]:
    if any(w in g["name"] for w in ("ПММ", "Стиральная", "Сушильная", "Электро-ТП", "Ванная")) and "мА" not in g["rcd"]:
        err.append(f"{g['id']}: мокрая/ТП-линия без АВДТ/УЗО")

# 4) электро-ТП
forbid = {"ванна": bath, "душ": (6641, 4550, 7541, 5516), "U14±300": (5251, 5241, 5950, 6141),
          "U11±300": (3920, 1481, 4820, 2180), "П-диван": (-2431, 45, -1681, 3068),
          "F34": (-1681, 45, -1031, 745), "F35": (-1681, 2368, -1031, 3068), "колонна СМА": (5260, 0, 5910, 650)}
for m in EL["floor_heating"]["mats"]:
    for r in m["rects"]:
        for name, f in forbid.items():
            ox = min(r[2], f[2]) - max(r[0], f[0])
            oy = min(r[3], f[3]) - max(r[1], f[1])
            if ox > 0 and oy > 0:
                err.append(f"{m['id']}: мат пересекает «{name}» ({ox}×{oy})")

# 5) щиты
for pnl in EL["panels"]:
    x, _ = pnl["pos"]
    y1, y2 = pnl["span_y"]
    pr = (x - 120, y1, x, y2)
    for it in FU["items"]:
        if it["id"] == "F64":
            continue
        r = rect(it)
        if min(r[2], pr[2]) - max(r[0], pr[0]) > 0 and min(r[3], pr[3]) - max(r[1], pr[1]) > 0:
            err.append(f"{pnl['id']} перекрыт {it['id']}")
f64 = ITEMS.get("F64")
if f64:
    r = rect(f64)
    u16 = next(p for p in EL["panels"] if p["id"] == "U16")
    if (r[1], r[3]) != tuple(u16["span_y"]):
        warn.append(f"furniture.json F64 y {r[1]}..{r[3]} ≠ U16 {u16['span_y']} — обновить у pib-furniture (D14)")

# 6) мощность
pc = PN["totals"]["p_calc_kw"]
if pc > 15:
    err.append(f"Pр {pc} кВт > 15 кВт")
elif pc > 11:
    warn.append(f"Pр {pc} кВт > 11 кВт (допущение №4) — вопрос 53 заказчику")

print(f"needs: закрыто {covered} из {total}")
print(f"групп: {PN['totals']['groups_count']}, Pр = {pc} кВт")
print("ОШИБКИ:", *(err or ["нет"]), sep="\n  ")
print("ПРЕДУПРЕЖДЕНИЯ:", *(warn or ["нет"]), sep="\n  ")
sys.exit(1 if err else 0)
