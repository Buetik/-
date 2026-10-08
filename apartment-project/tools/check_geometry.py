#!/usr/bin/env python3
"""Проверка геометрии 01-input/measurements.json (раздел ОБ).

Проверяет:
  1. полигоны помещений замкнуты (>=3 вершин, ненулевая площадь, без самопересечений);
  2. полигоны помещений не перекрываются между собой (по площади пересечения);
  3. площади помещений ≈ площадям БТИ/плана (расхождение > 3 % — ошибка);
  4. сумма участков по стенам (размерные цепочки) совпадает с габаритами;
  5. диагонали (если заданы в room["diagonals"]) согласуются с прямоугольностью;
  6. проёмы помещаются в длину своей стены, ссылки на стены существуют;
  7. инженерные точки лежат внутри квартиры/помещений (информативно).

Запуск: python3 tools/check_geometry.py [путь к measurements.json]
Код возврата 0 — ошибок нет (предупреждения допускаются), 1 — есть ошибки.
Без внешних зависимостей (пересечение полигонов — отсечение Сазерленда–Ходжмана
по прямоугольным ячейкам сетки, т.к. все полигоны ортогональные).
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "01-input" / "measurements.json"
TOL_AREA = 0.03
errors, warns = [], []


def area(poly):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def seg_cross(p1, p2, p3, p4):
    """Собственное пересечение отрезков (без касания в концах)."""
    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return (v > 0) - (v < 0)
    o1, o2 = orient(p1, p2, p3), orient(p1, p2, p4)
    o3, o4 = orient(p3, p4, p1), orient(p3, p4, p2)
    return o1 * o2 < 0 and o3 * o4 < 0


def self_intersects(poly):
    n = len(poly)
    edges = [(poly[i], poly[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if seg_cross(*edges[i], *edges[j]):
                return True
    return False


def point_in_poly(pt, poly):
    x, y = pt
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def overlap_area(p, q):
    """Площадь пересечения двух ортогональных полигонов: разбиение на ячейки сетки."""
    xs = sorted({v[0] for v in p + q})
    ys = sorted({v[1] for v in p + q})
    s = 0.0
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            c = ((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2)
            if point_in_poly(c, p) and point_in_poly(c, q):
                s += (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
    return s


def bbox_poly(p):
    return (min(v[0] for v in p), min(v[1] for v in p), max(v[0] for v in p), max(v[1] for v in p))


def wall_len(w):
    return math.dist(w["a"], w["b"])


def main():
    m = json.loads(PATH.read_text(encoding="utf-8"))
    rooms, walls = m["rooms"], {w["id"]: w for w in m["walls"]}
    print(f"Файл: {PATH}")
    print(f"Стен: {len(walls)}, проёмов: {len(m['openings'])}, помещений: {len(rooms)}, инж. точек: {len(m['utilities'])}\n")

    # 1-3. Полигоны и площади
    print("Помещение                         S план, м²  S геом, м²   Δ, %   статус")
    total_geo = total_bti = 0.0
    for r in rooms:
        poly = r["polygon"]
        if len(poly) < 3:
            errors.append(f"{r['id']}: полигон < 3 вершин")
            continue
        if poly[0] == poly[-1]:
            poly = poly[:-1]
        a = area(poly)
        if abs(a) < 1:
            errors.append(f"{r['id']}: нулевая площадь")
        if self_intersects(poly):
            errors.append(f"{r['id']}: самопересечение полигона")
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
            if x1 != x2 and y1 != y2:
                warns.append(f"{r['id']}: неортогональное ребро ({x1},{y1})-({x2},{y2})")
        s = abs(a) / 1e6
        bti = r.get("bti_area")
        st = "-"
        if bti:
            d = (s - bti) / bti
            st = "OK" if abs(d) <= TOL_AREA else "ОШИБКА >3%"
            if abs(d) > TOL_AREA:
                errors.append(f"{r['id']} {r['name']}: площадь {s:.2f} vs план {bti:.2f} ({d*100:+.1f} %)")
            if r["id"] != "R7":
                total_geo += s
                total_bti += bti
        print(f"{r['id']:3} {r['name'][:28]:28} {bti or 0:9.2f} {s:11.2f} {((s-bti)/bti*100 if bti else 0):+7.2f}   {st}")
    print(f"{'':3} {'Итого без балкона':28} {total_bti:9.2f} {total_geo:11.2f} {(total_geo-total_bti)/total_bti*100:+7.2f}")
    if "areas" in m:
        rs = m["areas"].get("rooms_sum")
        if rs and abs(total_geo - rs) / rs > 0.01:
            errors.append(f"Сумма помещений {total_geo:.2f} ≠ {rs} (план)")
        bal = next((r for r in rooms if r.get("area_coef")), None)
        if bal:
            s_b = abs(area(bal["polygon"])) / 1e6 * bal["area_coef"]
            print(f"    Балкон с к={bal['area_coef']}: {s_b:.2f}; итого с балконом {total_geo + s_b:.2f} (план {m['areas'].get('with_balcony_coef_0_3')})")

    # 2. Перекрытия
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            ov = overlap_area(rooms[i]["polygon"], rooms[j]["polygon"])
            if ov > 1e4:  # > 0,01 м²
                errors.append(f"Перекрытие {rooms[i]['id']} и {rooms[j]['id']}: {ov/1e6:.3f} м²")
    print("\nПерекрытия помещений: " + ("нет" if not any("Перекрытие" in e for e in errors) else "ЕСТЬ"))

    # 4. Цепочки и габариты
    ov = m.get("overall", {})
    W, H = ov.get("interior_x"), ov.get("interior_y")
    if W and H:
        def thick(wid):
            return walls[wid]["thickness"]
        chains = {
            "верх (X): 3380 + W7 + 4150": (3380, thick("W7"), 4150, W),
            "лево (Y): 3580 + W8 + 5190": (3580, thick("W8"), 5190, H),
            "низ (X): кухня 4090 + W10 + с/у 1740": (4090, thick("W10"), 1740, walls["W4"]["a"][0] - thick("W4") / 2),
            "право (Y): 1931+W11..2011 + 1710 + W13 + 2041 + W15+зазор+W16 + 2860": (
                2011, 1710, thick("W13"), 2041, 6051 - 5841, 2860, H),
        }
        print("\nРазмерные цепочки:")
        for name, vals in chains.items():
            *parts, target = vals
            sm = sum(parts)
            ok = abs(sm - target) <= 5
            print(f"  {name}: Σ={sm:.0f} vs {target:.0f} {'OK' if ok else 'ОШИБКА'}")
            if not ok:
                errors.append(f"Цепочка '{name}': {sm} ≠ {target}")
        # проверка полигона по габариту стен
        xs = [v[0] for x in rooms if x["id"] != "R7" for v in x["polygon"]]
        ys = [v[1] for x in rooms if x["id"] != "R7" for v in x["polygon"]]
        print(f"  Габарит помещений по полигонам: {max(xs)-min(xs)} × {max(ys)-min(ys)} (заявлено {W} × {H})")
        if (max(xs) - min(xs), max(ys) - min(ys)) != (W, H):
            errors.append("Габарит по полигонам не совпадает с overall")
        # внутренние грани стен против полигонов
        checks = [("W2 внутр.грань x=0", walls["W2"]["a"][0] + thick("W2") / 2, 0),
                  ("W1 внутр.грань y=H", walls["W1"]["a"][1] - thick("W1") / 2, H),
                  ("W3 внутр.грань y=0", walls["W3"]["a"][1] + thick("W3") / 2, 0),
                  ("W6 внутр.грань x=W", walls["W6"]["a"][0] - thick("W6") / 2, W)]
        for n, v, t in checks:
            ok = abs(v - t) <= 2
            print(f"  {n}: {v:.0f} {'OK' if ok else 'ОШИБКА'}")
            if not ok:
                errors.append(f"{n}: {v} ≠ {t}")

    # 5. Диагонали
    print("\nДиагонали:")
    any_d = False
    for rr in rooms:
        dg = rr.get("diagonals")
        if not dg:
            continue
        any_d = True
        x0, y0, x1, y1 = bbox_poly(rr["polygon"])
        exp = math.hypot(x1 - x0, y1 - y0)
        for dv in dg:
            dd = dv - exp
            print(f"  {rr['id']}: диагональ {dv} vs прямоугольник {exp:.0f} (Δ {dd:+.0f})")
            if abs(dd) > 20:
                warns.append(f"{rr['id']}: диагональ отличается на {dd:+.0f} мм — помещение не прямоугольное")
    if not any_d:
        print("  диагонали не заданы (нет фактического обмера) — проверка пропущена")
        warns.append("Диагонали помещений не измерены — прямоугольность не подтверждена (ОБ-1)")

    # 6. Проёмы
    for o in m["openings"]:
        w = walls.get(o["wall"])
        if not w:
            errors.append(f"{o['id']}: стена {o['wall']} не найдена")
            continue
        if o["offset"] < 0 or o["offset"] + o["width"] > wall_len(w) + 1:
            errors.append(f"{o['id']}: проём выходит за длину стены {o['wall']} ({o['offset']}+{o['width']} > {wall_len(w):.0f})")
        if o.get("sill") is not None and o.get("head") is not None and o["head"] <= o["sill"]:
            errors.append(f"{o['id']}: head <= sill")

    # 7. Инженерные точки
    apt = [x for x in rooms]
    for u in m["utilities"]:
        p = u.get("pos")
        if p is None:
            continue
        inside = any(point_in_poly(p, x["polygon"]) for x in apt)
        if not inside and u.get("wall") is None:
            warns.append(f"{u['id']} ({u['type']}) в точке {p} вне полигонов помещений")

    print("\nПредупреждения:")
    for w in warns:
        print("  - " + w)
    print("Ошибки:")
    for e in errors or ["нет"]:
        print("  - " + e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
