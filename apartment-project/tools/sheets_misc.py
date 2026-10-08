"""Листы ОД, КД, СП, СМ (табличные, из md/json) и развертки АР-11..АР-16."""
from __future__ import annotations

import re
from pathlib import Path

import model as m
from draw import Sheet, View, text_w, wrap
from sheets_common import Flow, Overflow, sym_fill

STAMP_TOP = 60.0


def stub_sheet(ctx, title="", note="Лист-заглушка: исходные данные раздела ещё не выпущены."):
    sh = Sheet("A3", 1)
    sh.text((40, 230), title or "Лист-заглушка", 5, bold=True)
    sh.paragraph(40, 215, 330, note, 3.0)
    sh.meta = {"stub": True, "note": note}
    return sh


# ---------------------------------------------------------------- markdown → листы
def parse_md(text):
    """Блоки: ('h', level, text) | ('p', text) | ('table', header, rows)."""
    blocks = []
    lines = text.splitlines()
    i = 0
    para = []

    def flush():
        if para:
            blocks.append(("p", " ".join(para).strip()))
            para.clear()

    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.startswith("|"):
            flush()
            tl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tl.append(lines[i].strip())
                i += 1
            rows = [[c.strip() for c in t.strip("|").split("|")] for t in tl]
            rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "--") for c in r)]
            if rows:
                blocks.append(("table", rows[0], rows[1:]))
            continue
        if ln.startswith("#"):
            flush()
            lev = len(ln) - len(ln.lstrip("#"))
            blocks.append(("h", lev, ln.lstrip("#").strip()))
        elif not ln.strip():
            flush()
        elif ln.lstrip().startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            flush()
            para.append(ln.strip())
            flush()
        else:
            para.append(ln.strip())
        i += 1
    flush()
    return blocks


def clean_md(s):
    s = "" if s is None else str(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", s)
    s = s.replace("<br>", " ").replace("<br/>", " ")
    return s


def col_widths(header, rows, W, h):
    n = len(header)
    want = []
    for j in range(n):
        vals = [header[j]] + [r[j] if j < len(r) else "" for r in rows]
        mx = max(text_w(clean_md(v), h) for v in vals) + 2
        mn = max(text_w(w, h) for w in clean_md(header[j]).split() or [""]) + 2
        want.append((min(mx, 95), max(mn, 7)))
    tot = sum(w for w, _ in want)
    if tot <= W:
        k = W / tot
        return [w * k for w, _ in want]
    # сжатие длинных колонок
    ws = [w for w, _ in want]
    for _ in range(50):
        tot = sum(ws)
        if tot <= W:
            break
        over = tot - W
        big = [j for j in range(n) if ws[j] > want[j][1] + 0.5]
        if not big:
            break
        tb = sum(ws[j] for j in big)
        for j in big:
            ws[j] = max(want[j][1], ws[j] - over * ws[j] / tb)
    k = W / sum(ws)
    return [w * k for w in ws]


class Pager:
    """Несколько листов одного кода: при переполнении — новый лист (продолжение)."""

    def __init__(self, fmt="A3", cols=1):
        self.fmt = fmt
        self.ncols = cols
        self.pages = []
        self.new()

    def new(self):
        sh = Sheet(self.fmt, 1)
        W, H = sh.W, sh.H
        if self.ncols == 1:
            cols = [(22, W - 7, H - 7, STAMP_TOP + 3)]
        else:
            cw = (W - 29 - 4 * (self.ncols - 1)) / self.ncols
            cols = []
            for i in range(self.ncols):
                x0 = 22 + i * (cw + 4)
                cols.append((x0, x0 + cw, H - 7, STAMP_TOP + 3 if x0 + cw > W - 190 else 8))
        sh.meta = {}
        self.sh = sh
        self.fl = Flow(sh, cols)
        self.pages.append(sh)

    def width(self):
        x0, x1, _, _ = self.fl.cols[min(self.fl.i, len(self.fl.cols) - 1)]
        return x1 - x0

    def text(self, s, h=1.8, bold=False, title=None):
        try:
            if bold:
                self.fl.text("", h=0.1, title=s, title_h=h)
            else:
                self.fl.text(s, h=h)
        except Overflow:
            self.new()
            self.text(s, h, bold)

    def table(self, header, rows, h=1.5, title=None):
        header = [clean_md(c) for c in header]
        rows = [[clean_md(c) for c in r] + [""] * (len(header) - len(r)) for r in rows]
        rows = [r[:len(header)] for r in rows]
        cols = col_widths(header, rows, self.width(), h)
        first = True
        while rows:
            fl = self.fl
            x0, x1, yt, yb = fl.cols[fl.i]
            avail = fl.y - yb
            n = len(rows)
            t = title if first else None
            while n > 0 and self.sh.table_height(cols, rows[:n], h=h, header=header, title=t, max_lines=6) > avail:
                n -= 1
            if n == 0:
                fl.i += 1
                if fl.i >= len(fl.cols):
                    self.new()
                else:
                    fl.y = fl.cols[fl.i][2]
                continue
            hh = self.sh.table_height(cols, rows[:n], h=h, header=header, title=t, max_lines=6)
            x, top, w = fl.take(hh)
            self.sh.table(x, top, cols, rows[:n], h=h, header=header, title=t, max_lines=6)
            rows = rows[n:]
            first = False

    def md(self, path, h=1.5, skip_first_heading=False):
        text = Path(path).read_text(encoding="utf-8")
        blocks = parse_md(text)
        for bi, b in enumerate(blocks):
            if b[0] == "h":
                if skip_first_heading and bi == 0:
                    continue
                self.text(clean_md(b[2]), h=2.6 if b[1] <= 2 else 2.2, bold=True)
            elif b[0] == "p":
                self.text(clean_md(b[1]), h=h + 0.1)
            else:
                self.table(b[1], b[2], h=h)


def md_sheet(paths, fmt="A3", h=1.45, note=None):
    pg = Pager(fmt)
    found = False
    for p in paths:
        pp = m.ROOT / p
        if pp.exists():
            found = True
            pg.text(f"Источник: {p}", h=1.5)
            pg.md(pp, h=h)
    if not found:
        return stub_sheet({}, note="Нет исходного файла: " + ", ".join(paths))
    for s in pg.pages:
        s.meta = {"scale": "—", "note": note} if note else {"scale": "—"}
    return pg.pages if len(pg.pages) > 1 else pg.pages[0]


# ---------------------------------------------------------------- ОД
def od01(ctx):
    sh = Sheet("A3", 1)
    W, H = sh.W, sh.H
    sh.text((W / 2 + 7, H - 60), m.OBJECT, 7, ha="center", bold=True)
    sh.text((W / 2 + 7, H - 80), "ДИЗАЙН-ПРОЕКТ ИНТЕРЬЕРА", 6, ha="center")
    sh.text((W / 2 + 7, H - 95), "Рабочая документация. Стадия «Р»", 4.5, ha="center")
    sh.text((W / 2 + 7, H - 110), f"Шифр {m.CIPHER}", 4, ha="center")
    sh.text((W / 2 + 7, H - 125), f"Принятый вариант планировки: {m.PL['selected_option']} (решение заказчика D12)",
            3.2, ha="center")
    secs = ["ОД — Общие данные", "АР — Архитектурные решения (обмер, планировка, демонтаж/монтаж, мебель, двери, "
            "потолки, полы, развертки, узлы)", "КД — Концепция", "ЭО/ЭМ — Электрооборудование и слаботочные сети",
            "ВК — Водопровод и канализация", "ОВ — Отопление и вентиляция", "СП — Спецификации", "СМ — Смета"]
    y = H - 150
    for s in secs:
        sh.text((90, y), s, 3.0)
        y -= 6
    sh.text((W / 2 + 7, 40), f"Разработал: {m.AUTHOR}", 3.5, ha="center")
    sh.text((W / 2 + 7, 30), f"Санкт-Петербург, {m.DATE}", 3.5, ha="center")
    sh.meta = {"scale": "—"}
    return sh


def od02(ctx):
    reg = ctx["register"]
    pages = ctx.get("pages", {})
    pg = Pager("A3")
    rows = []
    for r in reg:
        rows.append([r["code"], r["title"], r.get("scale", "—"), r.get("format", ""), pages.get(r["code"], ""),
                     r["owner"], r.get("file", "")])
    pg.table(["Код", "Наименование листа", "Масштаб", "Формат", "Лист альбома", "Раздел (агент)", "Файл"], rows,
             h=1.7, title="Ведомость листов рабочей документации")
    pg.text("Лист альбома — номер страницы в 03-drawings/pdf/album.pdf. DXF каждого листа — 03-drawings/dxf/<код>.dxf "
            "(слои AR-WALLS, AR-NEW, AR-DEMO, FURN, EL-LIGHT, EL-SOCKET, EL-LOW, VK, OV, DIM, TEXT, FRAME; единицы — мм "
            "модели главного масштаба листа).", h=1.6)
    for s in pg.pages:
        s.meta = {"scale": "—"}
    return pg.pages if len(pg.pages) > 1 else pg.pages[0]


def od03(ctx):
    p = m.ROOT / "04-specs/general-notes.md"
    if p.exists():
        return md_sheet(["04-specs/general-notes.md"])
    sh = stub_sheet(ctx, "Общие указания", "Лист-заглушка. Общие указания выпускает ГИП (pib-chief-architect) — "
                    "файл 04-specs/general-notes.md ещё не создан. До выпуска действуют: решения D1–D23 "
                    "(00-brief/decisions.md), ±0.000 = УЧП = верх плиты +100; запрет крепления в пол и штробления "
                    "стяжки с водяным ТП (D3, D15).")
    return sh


def od04(ctx):
    pg = Pager("A3")
    rows = []
    for r in sorted(m.PL["rooms"], key=lambda r: m.ROOM_NO[r["id"]]):
        rows.append([m.ROOM_NO[r["id"]], r["id"], r["name"], r.get("purpose", ""), m.fmt_num(r["area"]),
                     r.get("category", "")])
    a = m.PL["areas"]
    rows.append(["", "", "Итого без балкона", "", m.fmt_num(a["sum_without_balcony"]), ""])
    rows.append(["", "", "в т.ч. жилая", "", m.fmt_num(a["living"]), ""])
    rows.append(["", "", "Балкон (БТИ / после утепления, оценка)", "",
                 f"{m.fmt_num(a['balcony_bti'])} / {m.fmt_num(a['balcony_after_insulation_est'])}", "к=0,3"])
    pg.table(["№", "Id", "Наименование", "Назначение", "Площадь, м²", "Категория"], rows, h=2.0,
             title="Экспликация помещений (вариант D1, по planning.json)")
    pg.text(a.get("note", ""), h=1.8)
    pg.text("Предварительная экспликация по геометрии planning.json; итоговую (по чистовой отделке) оформляет ГИП.",
            h=1.8)
    for s in pg.pages:
        s.meta = {"scale": "—", "note": "предварительная, по planning.json — итог за ГИП"}
    return pg.pages[0]


# ---------------------------------------------------------------- КД
def kd01(ctx):
    pg = Pager("A3")
    sh = pg.sh
    x, y = 24, sh.H - 10
    sh.text((x, y - 3), "Палитра (02-concept/palette.json)", 3, bold=True)
    y -= 8
    n = len(m.PAL)
    cw = (sh.W - 30 - 4) / n
    for i, c in enumerate(m.PAL):
        cx = x + i * cw
        sh.rect(cx, y - 22, cx + cw - 2, y, fc=c["hex"], ec="black", lw=0.2)
        sh.text((cx, y - 25.5), f"{c['code']} {c['hex']}", 1.6, bold=True)
        lines = wrap(c["name"], cw - 2, 1.4)
        for k, ln in enumerate(lines[:3]):
            sh.text((cx, y - 28.5 - k * 2.1), ln, 1.4)
        if c.get("ncs"):
            sh.text((cx, y - 35.5), f"NCS {c['ncs']}"[:28], 1.3)
    sh.occupy((22, y - 38, sh.W - 7, sh.H))
    pg.fl.y = y - 41
    rows = [[c["code"], c["name"], c["hex"], c.get("ncs") or "", c.get("use", "")] for c in m.PAL]
    pg.table(["Код", "Цвет", "HEX", "NCS", "Применение"], rows, h=1.5, title="Применение цветов")
    rows = [[x_["id"], x_.get("room", ""), x_.get("surface", ""), x_.get("element", ""), x_.get("material", ""),
             x_.get("finish", ""), x_.get("brand_example", "")] for x_ in m.MAT]
    pg.table(["Id", "Пом.", "Поверхность", "Элемент", "Материал", "Отделка", "Пример"], rows, h=1.35,
             title="Материалы (02-concept/materials.json)")
    for s in pg.pages:
        s.meta = {"scale": "—"}
    return pg.pages


def kd02(ctx):
    r = md_sheet(["02-concept/viz-brief.md"], h=1.5)
    return r


# ---------------------------------------------------------------- развертки
EC = {"tile_wet": "#c8dbe8", "tile_dry": "#dde8ef", "tile": "#e8e4dc", "paint": "#f6f3ec", "furniture": "#e3d3b8",
      "fixture": "#ffffff", "appliance": "#eeeeee", "cladding": "#d8e6f0", "boiserie": "#d9cfc0", "panel": "#cfc4b3",
      "infill": "#f3ead8", "niche": "#ffffff", "box": "#efe2cf", "shaft": "#f4d9c4", "opening": "#ffffff",
      "window": "#e6f2fb", "door": "#f1ece2", "screen": "#ffffff", "hatch": "#ffffff", "manifold": "#cfe8d6",
      "moulding": "#d9cfc0", "cornice": "#ece6d8", "plinth": "#d9cfc0", "trim": "#d9cfc0"}
PT_C = {"water": "#1f6fd6", "drain": "#6b3d1f", "power": "#8e44ad", "light": "#b8860b", "switch": "#b8860b",
        "low": "#1e7d32", "valve": "#1e7d32", "vent": "#e67e22"}
ORDER = ["paint", "tile_dry", "tile_wet", "tile", "cladding", "boiserie", "infill", "panel", "moulding", "cornice",
         "plinth", "trim", "box", "shaft", "window", "opening", "door", "niche", "hatch", "manifold", "furniture",
         "appliance", "fixture", "screen"]


def _flip(e):
    v = e["view"]
    mm = re.search(r"слева\s+[xy]\s*=\s*(-?\d+).*справа\s+[xy]\s*=\s*(-?\d+)", v)
    if mm:
        return float(mm.group(1)) > float(mm.group(2))
    return False


def elev_block_size(e, scale):
    s0, s1 = e["span"]
    z0, z1 = e["z"]
    return (abs(s1 - s0) / scale, (z1 - z0) / scale)


def draw_elev(sh, e, x, y, scale, tab_w=92, h=1.4):
    """Развертка e с левым нижним углом изображения в (x, y). Таблица позиций — справа."""
    s0, s1 = sorted(e["span"])
    z0, z1 = e["z"]
    flip = _flip(e)
    w = (s1 - s0) / scale
    hh = (z1 - z0) / scale

    def S(s):
        return x + ((s1 - s) if flip else (s - s0)) / scale

    def Z(z):
        return y + (z - z0) / scale

    tl = wrap(e["title"], w + 2, 2.0, True)
    for k, ln in enumerate(tl[:2]):
        sh.text((x, y + hh + 11 - k * 2.7), ln + ("…" if k == 1 and len(tl) > 2 else ""), 2.0, bold=True)
    vl = wrap(f"{e['view']}  М 1:{scale}", w + 2, 1.5)
    y0t = y + hh + (5.4 if len(tl) > 1 else 8.0)
    for k, ln in enumerate(vl[:2]):
        sh.text((x, y0t - k * 2.2), ln, 1.5)
    # контур стены
    sh.rect(x, y, x + w, y + hh, layer="AR-WALLS", fc="#fbfaf7", ec="black", lw=0.5, z=1)
    items = e["items"]
    rect_items = [it for it in items if isinstance(it["s"], list)]
    pt_items = [it for it in items if not isinstance(it["s"], list)]
    rect_items.sort(key=lambda it: ORDER.index(it["type"]) if it["type"] in ORDER else 50)
    tile_rects = []
    pos_no = {}
    for it in rect_items:
        a, b = it["s"]
        za, zb = it["z"]
        xa, xb = sorted((S(a), S(b)))
        ya, yb = Z(za), Z(zb)
        if xb - xa < 0.05:
            xb = xa + 0.3
        ls = "dashed" if it["type"] in ("hatch", "niche", "infill") else "solid"
        hatch = {"box": "\\\\", "shaft": "xx", "infill": "--", "manifold": "//"}.get(it["type"])
        sh.rect(xa, ya, xb, yb, layer="AR-FIN" if it["type"] not in ("furniture", "appliance", "fixture") else "FURN",
                fc=EC.get(it["type"], "#ffffff"), ec="#444444", lw=0.18, ls=ls, hatch=hatch, hc="#999999",
                z=2 + ORDER.index(it["type"]) * 0.01 if it["type"] in ORDER else 2.5)
        if it["type"] in ("tile_wet", "tile_dry", "tile"):
            tile_rects.append((xa, ya, xb, yb))
    # швы плитки
    t = e.get("tile")
    if t:
        vj, hj = [], []
        for k, val in t.items():
            if isinstance(val, dict) and "joints" in val:
                if k.startswith("z"):
                    hj += val["joints"]
                else:
                    vj += val["joints"]
        for (xa, ya, xb, yb) in tile_rects:
            for j in vj:
                xx = S(j)
                if xa < xx < xb:
                    sh.line((xx, ya), (xx, yb), layer="AR-FIN", ec="#6b8fa6", lw=0.1, z=2.9)
            for j in hj:
                yy = Z(j)
                if ya < yy < yb:
                    sh.line((xa, yy), (xb, yy), layer="AR-FIN", ec="#6b8fa6", lw=0.1, z=2.9)
    sh.occupy((x, y, x + w, y + hh))
    # позиции
    no = 0
    rows = []
    for it in rect_items:
        no += 1
        a, b = it["s"]
        za, zb = it["z"]
        cx = (S(a) + S(b)) / 2
        cy = (Z(za) + Z(zb)) / 2
        bb = (cx - 1.6, cy - 1.6, cx + 1.6, cy + 1.6)
        rows.append([no, it["name"], f"{int(min(a, b))}..{int(max(a, b))}", f"{za:g}..{zb:g}"])
        pos_no[id(it)] = (no, (cx, cy))
    for it in pt_items:
        no += 1
        q = (S(it["s"]), Z(it["z"]))
        col = PT_C.get(it["type"], "black")
        sh.circle(q, 0.8, layer="EL-SOCKET" if it["type"] == "power" else "VK", ec=col, fc=col, lw=0.1, z=7)
        hb = f" (h {it['h_bath']:g})" if it.get("h_bath") is not None else ""
        rows.append([no, it["name"], f"{it['s']:g}", f"{it['z']:g}{hb}"])
        pos_no[id(it)] = (no, q)
    # подписи номеров: точки — с выноской, поверхности — в центре
    for it in pt_items:
        n, q = pos_no[id(it)]
        sh.label(q, str(n), 1.5, color=PT_C.get(it["type"], "black"), radius=(2, 3.5, 5.5, 8, 11),
                 lcolor=PT_C.get(it["type"], "black"))
    for it in rect_items:
        n, q = pos_no[id(it)]
        sh.label(q, str(n), 1.5, color="#333333", radius=(0, 2.5, 4.5, 7, 10), lcolor="#777777")
    # размеры: общий по s и привязки точек
    ss = sorted({round(it["s"]) for it in pt_items} | {round(s0), round(s1)})
    xs = sorted(S(s) for s in ss)
    _chain_paper(sh, xs, y - 4, [abs(xs[i + 1] - xs[i]) * scale for i in range(len(xs) - 1)], h=1.4)
    _chain_paper(sh, [x, x + w], y - 8.5, [round((s1 - s0))], h=1.6)
    # отметки высот
    zz = sorted({it["z"] for it in pt_items} | {z0, z1})
    _chain_paper_v(sh, [Z(v) for v in zz], x - 4, [round(zz[i + 1] - zz[i]) for i in range(len(zz) - 1)], h=1.4)
    sh.text((x + w + 1, y - 0.7), f"{z0 / 1000:+.3f}".replace("+0.000", "±0.000"), 1.5, z=7)
    sh.text((x + w + 1, y + hh - 0.7), f"{z1 / 1000:+.3f}", 1.5, z=7)
    return rows


def _chain_paper(sh, xs, y, labels, h=1.4):
    sh.line((xs[0] - 1, y), (xs[-1] + 1, y), layer="DIM", lw=0.13)
    for x in xs:
        sh.line((x - 0.7, y - 0.7), (x + 0.7, y + 0.7), layer="DIM", lw=0.3)
        sh.line((x, y), (x, y + 2.5), layer="DIM", lw=0.1)
    last = -99
    for i in range(len(xs) - 1):
        s = str(int(round(labels[i])))
        mid = (xs[i] + xs[i + 1]) / 2
        w = text_w(s, h)
        if w + 0.6 < xs[i + 1] - xs[i]:
            sh.text((mid, y + 0.5), s, h, ha="center", layer="DIM")
        else:
            off = -(h + 1.0) * (2 if last == i - 1 else 1)
            sh.text((mid, y + off), s, h, ha="center", layer="DIM")
            last = i


def _chain_paper_v(sh, ys, x, labels, h=1.4):
    sh.line((x, ys[0] - 1), (x, ys[-1] + 1), layer="DIM", lw=0.13)
    for y in ys:
        sh.line((x - 0.7, y - 0.7), (x + 0.7, y + 0.7), layer="DIM", lw=0.3)
        sh.line((x, y), (x + 2.5, y), layer="DIM", lw=0.1)
    last = -99
    for i in range(len(ys) - 1):
        s = str(int(round(labels[i])))
        mid = (ys[i] + ys[i + 1]) / 2
        w = text_w(s, h)
        if w + 0.6 < ys[i + 1] - ys[i]:
            sh.text((x - 0.5, mid), s, h, ha="center", rot=90, layer="DIM")
        else:
            off = -(h + 1.0) * (2 if last == i - 1 else 1)
            sh.text((x - 0.5 + off, mid), s, h, ha="center", rot=90, layer="DIM")
            last = i


def elev_sheet(code, fmts=(("A3", 25), ("A2", 25), ("A2", 50), ("A1", 50))):
    els = [e for e in m.EV["elevations"] if e["sheet"] == code]
    if not els:
        return stub_sheet({}, note=f"В 03-drawings/elevations.json нет разверток для {code} — данные не выпущены "
                                   f"(pib-finishes).")
    for fmt, scale in fmts:
        sh = Sheet(fmt, scale)
        try:
            _place_elevs(sh, els, scale)
            sh.meta = {"scale": f"1:{scale}"}
            return sh
        except Overflow:
            continue
    raise Overflow("развертки не помещаются")


def _place_elevs(sh, els, scale, tab_w=96, h=1.35):
    W, H = sh.W, sh.H
    # блоки: изображение + таблица позиций справа
    blocks = []
    for e in els:
        w, hh = elev_block_size(e, scale)
        nrows = len(e["items"])
        rows_est = [[1, it["name"], "00000..00000", "0000..0000 (h 0000)"] for it in e["items"]]
        th = sh.table_height([6, tab_w - 40, 17, 17], rows_est, h=h, header=["№", "Элемент", "s", "z"], max_lines=3)
        bw = w + 12 + tab_w
        bh = max(hh + 26, th + 14)
        blocks.append((e, w, hh, bw, bh))
    # полочная укладка
    x, ytop = 24.0, H - 7
    shelf_h = 0
    placed = []
    for e, w, hh, bw, bh in blocks:
        if x + bw > W - 7:
            x = 24.0
            ytop -= shelf_h + 4
            shelf_h = 0
        if ytop - bh < 7 or (x + bw > W - 190 and ytop - bh < STAMP_TOP + 2):
            # попробовать новую полку
            if x > 24.0:
                x = 24.0
                ytop -= shelf_h + 4
                shelf_h = 0
            if ytop - bh < 7 or (x + bw > W - 190 and ytop - bh < STAMP_TOP + 2):
                raise Overflow("развертки")
        placed.append((e, x, ytop, w, hh, bw, bh))
        x += bw + 6
        shelf_h = max(shelf_h, bh)
    for e, x, ytop, w, hh, bw, bh in placed:
        y = ytop - 14 - hh
        rows = draw_elev(sh, e, x + 8, y, scale, tab_w=tab_w)
        sh.table(x + 8 + w + 4, ytop - 1, [6, tab_w - 40, 17, 17], rows, h=h, header=["№", "Элемент", "s, мм", "z, мм"],
                 max_lines=3)
        fin = "; ".join(e.get("finish") or [])
        if fin:
            yy = y - 13
            for ln in wrap("Отделка: " + fin, w + 4, 1.4)[:4]:
                sh.text((x + 6, yy), ln, 1.4)
                yy -= 2.1


def ar11(ctx):
    return elev_sheet("АР-11")


def ar12(ctx):
    return elev_sheet("АР-12")


def ar13(ctx):
    return elev_sheet("АР-13")


def ar14(ctx):
    return elev_sheet("АР-14")


def ar15(ctx):
    return elev_sheet("АР-15")


def ar16(ctx):
    return elev_sheet("АР-16")


# ---------------------------------------------------------------- СП/СМ
def sp01(ctx):
    return md_sheet(["04-specs/finish-schedule.md"])


def sp02(ctx):
    return md_sheet(["04-specs/spec-furniture.md", "04-specs/spec-kitchen-appliances.md",
                     "04-specs/spec-doors-hardware.md"], h=1.35)


def sp03(ctx):
    return md_sheet(["04-specs/spec-lighting.md", "04-specs/spec-wiring-devices.md", "04-specs/spec-panel-cable.md",
                     "04-specs/spec-lowcurrent-smarthome-cinema.md"], h=1.3)


def sp04(ctx):
    return md_sheet(["04-specs/spec-plumbing.md", "04-specs/spec-heating-hvac.md"], h=1.35)


def sp05(ctx):
    return md_sheet(["04-specs/spec-finish-materials.md"], h=1.35)


def sm01(ctx):
    return md_sheet(["05-estimate/estimate.md"], h=1.35)


SHEETS = {"ОД-01": od01, "ОД-02": od02, "ОД-03": od03, "ОД-04": od04, "КД-01": kd01, "КД-02": kd02,
          "АР-11": ar11, "АР-12": ar12, "АР-13": ar13, "АР-14": ar14, "АР-15": ar15, "АР-16": ar16,
          "СП-01": sp01, "СП-02": sp02, "СП-03": sp03, "СП-04": sp04, "СП-05": sp05, "СМ-01": sm01}
