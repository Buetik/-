"""Рамка формата и основная надпись по форме 3 ГОСТ Р 21.101-2020 (185×55).

Поля рамки: слева 20, остальные 5 мм. Графы формы 3:
  1 — обозначение документа (15), 2 — наименование объекта (10),
  3 — наименование раздела (15), 4 — наименование листа/изображений (15),
  6/7/8 — стадия, лист, листов, 9 — организация; слева — графы изменений и подписей.
"""
from __future__ import annotations

from draw import Sheet, text_w, wrap
import model as m

LW_THICK = 0.5
LW_THIN = 0.18


def frame(sh: Sheet):
    W, H = sh.W, sh.H
    sh.rect(20, 5, W - 5, H - 5, layer="FRAME", lw=LW_THICK, z=9)
    sh.text((W - 5, 1.6), f"Формат {sh.fmt}", 2.0, layer="FRAME", ha="right", z=9)
    sh.occupy((0, 0, 20.5, H))
    sh.occupy((0, H - 5.5, W, H))
    sh.occupy((W - 5.5, 0, W, H))
    sh.occupy((0, 0, W, 5.5))


def _fit(sh, x0, y0, x1, y1, s, hs=(3.5, 3.0, 2.5, 2.2, 2.0, 1.8), bold=False, center=True):
    w = x1 - x0 - 2.0
    hgt = y1 - y0 - 1.6
    for h in hs:
        lines = wrap(s, w, h, bold)
        tot = h + (len(lines) - 1) * h * 1.45
        if tot <= hgt:
            break
    yc = (y0 + y1) / 2 + tot / 2 - h
    for i, ln in enumerate(lines):
        if center:
            sh.text(((x0 + x1) / 2, yc - i * h * 1.45), ln, h, layer="FRAME", ha="center", bold=bold, z=9)
        else:
            sh.text((x0 + 1.0, yc - i * h * 1.45), ln, h, layer="FRAME", bold=bold, z=9)


def stamp(sh: Sheet, code, title, section, sheet_no, sheets_total, scale="—", designation=None):
    """Основная надпись форма 3 в правом нижнем углу."""
    frame(sh)
    W = sh.W
    x0, y0 = W - 5 - 185, 5
    top = y0 + 55
    sh.rect(x0, y0, x0 + 185, top, layer="FRAME", lw=LW_THICK, fc="white", z=8.5)
    sh.occupy((x0 - 1, y0, x0 + 185, top + 1))
    L = x0 + 65            # граница левой части
    R70 = L + 70
    # правая часть: горизонтали
    for yy, x_from, lw in ((top - 15, L, LW_THICK), (top - 25, L, LW_THICK), (top - 40, L, LW_THICK)):
        sh.line((x_from, yy), (x0 + 185, yy), layer="FRAME", lw=lw, z=9)
    sh.line((L, y0), (L, top), layer="FRAME", lw=LW_THICK, z=9)
    sh.line((R70, y0), (R70, top - 25), layer="FRAME", lw=LW_THICK, z=9)
    # стадия / лист / листов
    sh.line((R70, top - 30), (x0 + 185, top - 30), layer="FRAME", lw=LW_THIN, z=9)
    for dx in (15, 30):
        sh.line((R70 + dx, top - 40), (R70 + dx, top - 25), layer="FRAME", lw=LW_THIN, z=9)
    for dx, t in ((7.5, "Стадия"), (22.5, "Лист"), (40, "Листов")):
        sh.text((R70 + dx, top - 28.8), t, 2.0, layer="FRAME", ha="center", z=9)
    for dx, t in ((7.5, m.STAGE), (22.5, str(sheet_no)), (40, str(sheets_total))):
        sh.text((R70 + dx, top - 36.6), t, 3.5, layer="FRAME", ha="center", z=9)
    # левая часть: сетка 5 мм
    cols = [10, 10, 10, 10, 15, 10]
    xs = [x0]
    for c in cols:
        xs.append(xs[-1] + c)
    for i in range(1, 11):
        yy = y0 + i * 5
        lw = LW_THICK if i in (5, 6) else LW_THIN
        sh.line((x0, yy), (L, yy), layer="FRAME", lw=lw, z=9)
    for i, xx in enumerate(xs[1:-1], start=1):
        if i == 1:      # колонки 1-2 объединены в нижней части
            sh.line((xx, y0 + 25), (xx, top), layer="FRAME", lw=LW_THICK, z=9)
        elif i == 3:
            sh.line((xx, y0 + 25), (xx, top), layer="FRAME", lw=LW_THICK, z=9)
        else:
            sh.line((xx, y0), (xx, top), layer="FRAME", lw=LW_THICK, z=9)
    for i, t in enumerate(["Изм.", "Кол.уч", "Лист", "№док.", "Подп.", "Дата"]):
        sh.text((xs[i] + cols[i] / 2, y0 + 26.3), t, 1.8, layer="FRAME", ha="center", z=9)
    roles = ["Разраб.", "Пров.", "ГИП", "Н.контр.", "Утв."]
    for i, r in enumerate(roles):
        yy = y0 + 20 - i * 5 + 1.3
        sh.text((x0 + 1, yy), r, 2.0, layer="FRAME", z=9)
    sh.text((xs[2] + 0.8, y0 + 21.3), m.AUTHOR, 2.0, layer="FRAME", z=9)
    sh.text((xs[5] + 5, y0 + 21.3), m.DATE, 1.8, layer="FRAME", ha="center", z=9)
    # графы
    des = designation or f"{m.CIPHER}-{code}"
    _fit(sh, L, top - 15, x0 + 185, top, des, hs=(5.0, 4.0, 3.5), bold=True)
    _fit(sh, L, top - 25, x0 + 185, top - 15, m.OBJECT, hs=(3.5, 3.0, 2.5))
    _fit(sh, L, top - 40, R70, top - 25, section, hs=(3.0, 2.5, 2.2, 2.0, 1.8))
    t4 = title + (f"\nМасштаб {scale}" if scale and scale != "—" else "")
    _fit(sh, L, y0, R70, y0 + 15, t4, hs=(2.5, 2.2, 2.0, 1.8, 1.6))
    _fit(sh, R70, y0, x0 + 185, y0 + 15, "ПИБ\nагенты pib-*", hs=(3.0, 2.5))


def title_frame(sh: Sheet):
    frame(sh)
