"""Рендер листов рабочей документации: DXF (ezdxf) и PDF/PNG (matplotlib).

Лист собирается из примитивов в координатах бумаги (мм, 0,0 — левый нижний угол формата).
Виды (View) переводят модельные мм в мм листа по масштабу. Один набор примитивов
выводится в оба формата: DXF — в мм модели главного масштаба (бумага × S), PDF — 1:1 на формат.
"""
from __future__ import annotations

import math
from functools import lru_cache

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.patches import PathPatch, Circle, Arc  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
from matplotlib.textpath import TextPath  # noqa: E402
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, box as sbox  # noqa: E402

FONT = "DejaVu Sans"
matplotlib.rcParams.update({
    "font.family": FONT,
    "pdf.fonttype": 42,          # TrueType целиком — кириллица без квадратов
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "lines.scale_dashes": False,
    "hatch.linewidth": 0.35,
})
_FP = FontProperties(family=FONT)
_FPB = FontProperties(family=FONT, weight="bold")
CAP = 0.729                       # высота прописной DejaVu Sans в долях кегля
PT = 72 / 25.4                    # пунктов в мм

FORMATS = {"A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0)}

# слои DXF: (ACI цвет, тип линии)
LAYERS = {
    "FRAME": (7, "CONTINUOUS"), "AR-WALLS": (7, "CONTINUOUS"), "AR-NEW": (5, "CONTINUOUS"),
    "AR-DEMO": (1, "DASHED"), "FURN": (8, "CONTINUOUS"), "EL-LIGHT": (30, "CONTINUOUS"),
    "EL-SOCKET": (6, "CONTINUOUS"), "EL-LOW": (3, "CONTINUOUS"), "VK": (4, "CONTINUOUS"), "OV": (3, "CONTINUOUS"),
    "DIM": (7, "CONTINUOUS"), "TEXT": (7, "CONTINUOUS"), "AR-FIN": (9, "CONTINUOUS"), "BASE": (9, "CONTINUOUS"),
}
LS = {"solid": None, "dashed": (0, (3.0 * PT, 1.5 * PT)), "dashdot": (0, (6 * PT, 1.2 * PT, 0.6 * PT, 1.2 * PT)),
      "dotted": (0, (0.6 * PT, 1.0 * PT)), "longdash": (0, (8 * PT, 2 * PT))}
DXF_LT = {"solid": "CONTINUOUS", "dashed": "DASHED", "dashdot": "DASHDOT", "dotted": "DOT", "longdash": "DASHED"}
HATCH_DXF = {"/": ("ANSI31", 0), "\\": ("ANSI31", 90), "x": ("ANSI37", 0), ".": ("DOTS", 0), "-": ("LINE", 0),
             "|": ("LINE", 90), "+": ("NET", 0), "o": ("HONEY", 0)}


# ---------------------------------------------------------------- измерение текста
@lru_cache(maxsize=20000)
def text_w(s: str, h: float, bold=False) -> float:
    """Ширина строки (мм) при высоте прописной h (мм)."""
    if not s:
        return 0.0
    size = h / CAP
    tp = TextPath((0, 0), s.replace("$", r"\$"), size=size, prop=_FPB if bold else _FP)
    ext = tp.get_extents()
    return max(ext.x1, 0) + 0.05 * size


def text_box(s, h, bold=False, ls=1.55):
    lines = str(s).split("\n")
    w = max(text_w(l, h, bold) for l in lines)
    hh = h + (len(lines) - 1) * h * ls
    return w, hh


def wrap(s, width, h, bold=False):
    """Перенос строки по словам под ширину width (мм)."""
    out = []
    for para in str(s).split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            t = (cur + " " + w).strip()
            if text_w(t, h, bold) <= width or not cur:
                cur = t
            else:
                out.append(cur)
                cur = w
        # слишком длинное одно слово — режем
        while text_w(cur, h, bold) > width and len(cur) > 2:
            n = len(cur)
            while n > 1 and text_w(cur[:n], h, bold) > width:
                n -= 1
            out.append(cur[:n])
            cur = cur[n:]
        out.append(cur)
    return out


# ---------------------------------------------------------------- лист
class Sheet:
    def __init__(self, fmt="A3", scale_den=50):
        self.fmt = fmt
        self.W, self.H = FORMATS[fmt]
        self.S = scale_den           # масштаб DXF (главный вид 1:1 в модели)
        self.prims = []
        self.occ = []                # занятые прямоугольники (для подписей)

    # --- примитивы (координаты бумаги, мм)
    def poly(self, pts, closed=True, layer="TEXT", ec="black", lw=0.25, ls="solid", fc=None, alpha=1.0,
             hatch=None, hc=None, z=2):
        self.prims.append(dict(k="poly", pts=[tuple(p) for p in pts], closed=closed, layer=layer, ec=ec, lw=lw,
                               ls=ls, fc=fc, alpha=alpha, hatch=hatch, hc=hc or ec or "black", z=z))

    def line(self, p1, p2, **kw):
        kw.setdefault("closed", False)
        self.poly([p1, p2], **kw)

    def rect(self, x0, y0, x1, y1, **kw):
        self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], **kw)

    def shape(self, geom, layer="AR-WALLS", ec="black", lw=0.35, ls="solid", fc=None, alpha=1.0, hatch=None, hc=None,
              z=3):
        """shapely Polygon/MultiPolygon в координатах бумаги."""
        if geom is None or geom.is_empty:
            return
        polys = []
        if isinstance(geom, Polygon):
            polys = [geom]
        elif isinstance(geom, (MultiPolygon, GeometryCollection)):
            polys = [g for g in geom.geoms if isinstance(g, Polygon)]
        for p in polys:
            rings = [list(p.exterior.coords)] + [list(r.coords) for r in p.interiors]
            self.prims.append(dict(k="shape", rings=rings, layer=layer, ec=ec, lw=lw, ls=ls, fc=fc, alpha=alpha,
                                   hatch=hatch, hc=hc or ec or "black", z=z))

    def circle(self, c, r, layer="TEXT", ec="black", lw=0.25, fc=None, ls="solid", z=4, alpha=1.0):
        self.prims.append(dict(k="circle", c=tuple(c), r=r, layer=layer, ec=ec, lw=lw, fc=fc, ls=ls, z=z, alpha=alpha))

    def arc(self, c, r, a0, a1, layer="TEXT", ec="black", lw=0.25, ls="solid", z=4):
        self.prims.append(dict(k="arc", c=tuple(c), r=r, a0=a0, a1=a1, layer=layer, ec=ec, lw=lw, ls=ls, z=z))

    def text(self, pos, s, h=2.5, layer="TEXT", rot=0.0, ha="left", va="baseline", color="black", bold=False,
             z=6, occupy=False, bg=None):
        if s is None or s == "":
            return
        s = str(s)
        self.prims.append(dict(k="text", pos=tuple(pos), s=s, h=h, layer=layer, rot=rot, ha=ha, va=va,
                               color=color, bold=bold, z=z, bg=bg))
        if occupy:
            self.occ.append(self.text_bbox(pos, s, h, rot, ha, va, bold))

    def text_bbox(self, pos, s, h, rot=0, ha="left", va="baseline", bold=False):
        w, hh = text_box(s, h, bold)
        x, y = pos
        if ha == "center":
            x0 = x - w / 2
        elif ha == "right":
            x0 = x - w
        else:
            x0 = x
        nlines = s.count("\n") + 1
        if va == "center":
            y0 = y - hh / 2
        elif va == "top":
            y0 = y - hh
        elif va == "bottom":
            y0 = y
        else:  # baseline (первая строка)
            y0 = y - (nlines - 1) * h * 1.55 - 0.25 * h
        bb = (x0, y0, x0 + w, y0 + hh + 0.25 * h)
        if abs(rot) > 1e-6:
            # поворот рамки вокруг pos
            cs, sn = math.cos(math.radians(rot)), math.sin(math.radians(rot))
            pts = [(bb[0], bb[1]), (bb[2], bb[1]), (bb[2], bb[3]), (bb[0], bb[3])]
            rp = [(x + (px - x) * cs - (py - y) * sn, y + (px - x) * sn + (py - y) * cs) for px, py in pts]
            xs, ys = [p[0] for p in rp], [p[1] for p in rp]
            bb = (min(xs), min(ys), max(xs), max(ys))
        return bb

    # --- служебное
    def occupy(self, bb):
        self.occ.append(tuple(bb))

    def free(self, bb, pad=0.4):
        x0, y0, x1, y1 = bb
        if x0 < 21 or y0 < 6 or x1 > self.W - 6 or y1 > self.H - 6:
            return False
        for o in self.occ:
            if x0 - pad < o[2] and x1 + pad > o[0] and y0 - pad < o[3] and y1 + pad > o[1]:
                return False
        return True

    def label(self, anchor, s, h=2.0, layer="TEXT", color="black", leader=True, radius=(0, 3, 6, 9, 13, 18, 24),
              prefer=None, lcolor=None, bold=False, z=7, bg="white", min_r=0):
        """Подпись с поиском свободного места вокруг anchor; при смещении — выноска."""
        ax, ay = anchor
        w, hh = text_box(s, h, bold)
        dirs = prefer or [(1, 1), (1, -1), (-1, 1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1)]
        for r in radius:
            if r < min_r:
                continue
            for dx, dy in (dirs if r else [(1, 1)]):
                if r == 0:
                    cx, cy = ax + 1.2, ay + 1.0
                else:
                    n = math.hypot(dx, dy) or 1
                    cx, cy = ax + dx / n * r, ay + dy / n * r
                # прямоугольник подписи прилегает к точке со стороны направления
                x0 = cx if dx >= 0 else cx - w
                if dx == 0:
                    x0 = cx - w / 2
                y0 = cy if dy >= 0 else cy - hh
                if dy == 0:
                    y0 = cy - hh / 2
                bb = (x0 - 0.3, y0 - 0.3, x0 + w + 0.3, y0 + hh + 0.3)
                if self.free(bb):
                    self.occ.append(bb)
                    top_base = y0 + hh - h
                    self.text((x0, top_base), s, h, layer=layer, color=color, bold=bold, z=z, bg=bg)
                    if leader and r > 3.5:
                        # выноска до ближайшей точки рамки
                        px = min(max(ax, bb[0]), bb[2])
                        py = min(max(ay, bb[1]), bb[3])
                        self.line((ax, ay), (px, py), layer=layer, ec=lcolor or color, lw=0.13, z=z - 0.5)
                        self.circle((ax, ay), 0.25, layer=layer, ec=lcolor or color, fc=lcolor or color, lw=0.1, z=z)
                    return bb
        # не нашлось — ставим принудительно справа сверху (с выноской)
        x0, y0 = ax + 3, ay + 3
        self.text((x0, y0), s, h, layer=layer, color=color, bold=bold, z=z, bg=bg)
        self.line((ax, ay), (x0, y0), layer=layer, ec=lcolor or color, lw=0.13)
        self.occ.append((x0, y0, x0 + w, y0 + hh))
        return (x0, y0, x0 + w, y0 + hh)

    # --- таблица
    def table(self, x, y_top, cols, rows, h=1.8, header=None, hh=None, layer="TEXT", pad=0.8, row_min=None,
              title=None, title_h=2.5, fills=None, max_lines=4, bold_rows=()):
        """Таблица: cols — ширины (мм), rows — списки строк. Возвращает нижнюю отметку y."""
        hh = hh or h
        y = y_top
        W = sum(cols)
        if title:
            self.text((x, y - title_h - 0.6), title, title_h, layer=layer, bold=True)
            y -= title_h + 2.2
        lsp = h * 1.45
        allrows = ([("H", header)] if header else []) + [("R", r) for r in rows]
        for ri, (kind, r) in enumerate(allrows):
            th = hh if kind == "H" else h
            cells = []
            nl = 1
            isb = kind == "H" or (ri - (1 if header else 0)) in bold_rows
            for c, wcol in zip(r, cols):
                lines = wrap("" if c is None else str(c), wcol - 2 * pad, th, isb)
                if len(lines) > max_lines:
                    lines = lines[:max_lines]
                    lines[-1] = lines[-1][: max(1, len(lines[-1]) - 1)] + "…"
                cells.append(lines)
                nl = max(nl, len(lines))
            rh = max(row_min or 0, th * 1.0 + (nl - 1) * th * 1.45 + 2 * pad + 0.4)
            if kind == "H":
                rh = max(rh, th + 2 * pad + 1.2)
            fc = None
            if kind == "H":
                fc = "#e6e6e6"
            elif fills and (ri - (1 if header else 0)) in fills:
                fc = fills[ri - (1 if header else 0)]
            self.rect(x, y - rh, x + W, y, layer=layer, lw=0.25 if kind == "H" else 0.13, fc=fc, z=1.5)
            cx = x
            for lines, wcol in zip(cells, cols):
                self.line((cx, y), (cx, y - rh), layer=layer, lw=0.13)
                ty = y - pad - th - 0.2
                for ln in lines:
                    self.text((cx + pad, ty), ln, th, layer=layer, bold=isb)
                    ty -= th * 1.45
                cx += wcol
            self.line((cx, y), (cx, y - rh), layer=layer, lw=0.13)
            y -= rh
        self.rect(x, y, x + W, y_top - ((title_h + 2.2) if title else 0), layer=layer, lw=0.35, z=1.6)
        self.occ.append((x, y, x + W, y_top))
        return y

    def table_height(self, cols, rows, h=1.8, header=None, pad=0.8, title=None, title_h=2.5, max_lines=4,
                     bold_rows=()):
        tot = (title_h + 2.2) if title else 0
        for i, (kind, r) in enumerate(([("H", header)] if header else []) + [("R", r) for r in rows]):
            nl = 1
            isb = kind == "H" or (i - (1 if header else 0)) in bold_rows
            for c, wcol in zip(r, cols):
                nl = max(nl, min(max_lines, len(wrap("" if c is None else str(c), wcol - 2 * pad, h, isb))))
            rh = h + (nl - 1) * h * 1.45 + 2 * pad + 0.4
            if kind == "H":
                rh = max(rh, h + 2 * pad + 1.2)
            tot += rh
        return tot

    def paragraph(self, x, y_top, width, text, h=2.0, layer="TEXT", lsp=1.5, bold=False):
        y = y_top - h
        for para in str(text).split("\n"):
            for ln in wrap(para, width, h, bold):
                self.text((x, y), ln, h, layer=layer, bold=bold)
                y -= h * lsp
        self.occ.append((x, y + h * lsp - 0.5, x + width, y_top))
        return y + h * lsp - h * 0.6

    def paragraph_height(self, width, text, h=2.0, lsp=1.5):
        n = sum(len(wrap(p, width, h)) for p in str(text).split("\n"))
        return n * h * lsp + 0.5

    # --- вывод
    def save(self, pdf=None, png=None, dxf=None, svg=None, dpi=110):
        if pdf or png or svg:
            render_mpl(self, pdf=pdf, png=png, svg=svg, dpi=dpi)
        if dxf:
            render_dxf(self, dxf)


# ---------------------------------------------------------------- вид (модель → бумага)
class View:
    def __init__(self, sheet: Sheet, scale, model_origin, paper_origin):
        self.sh = sheet
        self.k = 1.0 / scale
        self.scale = scale
        self.mo = model_origin
        self.po = paper_origin

    def P(self, p):
        return (self.po[0] + (p[0] - self.mo[0]) * self.k, self.po[1] + (p[1] - self.mo[1]) * self.k)

    def L(self, mm):
        return mm * self.k

    def geom(self, g):
        from shapely import affinity
        g2 = affinity.translate(g, -self.mo[0], -self.mo[1])
        g2 = affinity.scale(g2, self.k, self.k, origin=(0, 0))
        return affinity.translate(g2, self.po[0], self.po[1])

    # обёртки
    def poly(self, pts, **kw):
        self.sh.poly([self.P(p) for p in pts], **kw)

    def line(self, a, b, **kw):
        self.sh.line(self.P(a), self.P(b), **kw)

    def rect(self, x0, y0, x1, y1, **kw):
        self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], **kw)

    def shape(self, g, **kw):
        self.sh.shape(self.geom(g), **kw)

    def circle(self, c, r_mm=None, r_paper=None, **kw):
        self.sh.circle(self.P(c), r_paper if r_paper is not None else self.L(r_mm), **kw)

    def arc(self, c, r_mm, a0, a1, **kw):
        self.sh.arc(self.P(c), self.L(r_mm), a0, a1, **kw)

    def text(self, p, s, h=2.5, **kw):
        self.sh.text(self.P(p), s, h, **kw)

    def label(self, p, s, h=2.0, **kw):
        return self.sh.label(self.P(p), s, h, **kw)

    # --- размеры (ГОСТ 2.307: засечки 45°, текст над размерной линией)
    def dim_chain(self, pts, axis, at, ext_from=None, labels=None, h=2.0, layer="DIM", tick=1.6, gap=1.0,
                  text_side=1, ext_over=1.5, color="black"):
        """Цепочка размеров. axis='x' — горизонтальная (размеры вдоль X на уровне Y=at),
        axis='y' — вертикальная (вдоль Y на X=at). ext_from — модельная координата начала выносных линий
        (одно число или список по точкам)."""
        sh = self.sh
        pts = list(pts)
        if not pts:
            return
        efs = ext_from if isinstance(ext_from, (list, tuple)) else [ext_from] * len(pts)
        P = self.P
        if axis == "x":
            a = P((pts[0], at))
            b = P((pts[-1], at))
            sh.line((a[0] - 1.5, a[1]), (b[0] + 1.5, b[1]), layer=layer, lw=0.13, ec=color)
            for xm, ef in zip(pts, efs):
                q = P((xm, at))
                if ef is not None:
                    e = P((xm, ef))
                    sgn = 1 if q[1] > e[1] else -1
                    sh.line((q[0], e[1] + sgn * gap), (q[0], q[1] + sgn * ext_over), layer=layer, lw=0.13, ec=color)
                sh.line((q[0] - tick / 2, q[1] - tick / 2), (q[0] + tick / 2, q[1] + tick / 2), layer=layer, lw=0.35,
                        ec=color)
            last_out = -99
            for i in range(len(pts) - 1):
                v = abs(pts[i + 1] - pts[i]) if not labels else labels[i]
                s = str(int(round(v))) if isinstance(v, (int, float)) else str(v)
                q0, q1 = P((pts[i], at)), P((pts[i + 1], at))
                mid = (q0[0] + q1[0]) / 2
                w = text_w(s, h)
                seg = abs(q1[0] - q0[0])
                ty = q0[1] + 0.6 if text_side > 0 else q0[1] - 0.6 - h
                if w + 0.8 < seg:
                    sh.text((mid, ty), s, h, layer=layer, ha="center", color=color)
                    sh.occupy((mid - w / 2, ty - 0.2, mid + w / 2, ty + h + 0.2))
                else:
                    # текст выносим над/под с ступенькой
                    off = (h + 0.9) * text_side
                    tx = mid
                    if i > 0 and last_out == i - 1:
                        off *= 2
                    sh.text((tx, ty + off), s, h, layer=layer, ha="center", color=color)
                    sh.line((mid, q0[1]), (mid, ty + off - (0.3 if text_side > 0 else -h - 0.3)), layer=layer,
                            lw=0.1, ec=color)
                    sh.occupy((tx - w / 2, ty + off - 0.2, tx + w / 2, ty + off + h + 0.2))
                    last_out = i
            sh.occupy((min(a[0], b[0]) - 1, a[1] - 1, max(a[0], b[0]) + 1, a[1] + 1))
        else:
            a = P((at, pts[0]))
            b = P((at, pts[-1]))
            sh.line((a[0], a[1] - 1.5), (b[0], b[1] + 1.5), layer=layer, lw=0.13, ec=color)
            for ym, ef in zip(pts, efs):
                q = P((at, ym))
                if ef is not None:
                    e = P((ef, ym))
                    sgn = 1 if q[0] > e[0] else -1
                    sh.line((e[0] + sgn * gap, q[1]), (q[0] + sgn * ext_over, q[1]), layer=layer, lw=0.13, ec=color)
                sh.line((q[0] - tick / 2, q[1] - tick / 2), (q[0] + tick / 2, q[1] + tick / 2), layer=layer, lw=0.35,
                        ec=color)
            last_out = -99
            for i in range(len(pts) - 1):
                v = abs(pts[i + 1] - pts[i]) if not labels else labels[i]
                s = str(int(round(v))) if isinstance(v, (int, float)) else str(v)
                q0, q1 = P((at, pts[i])), P((at, pts[i + 1]))
                mid = (q0[1] + q1[1]) / 2
                w = text_w(s, h)
                seg = abs(q1[1] - q0[1])
                tx = q0[0] - 0.6 if text_side > 0 else q0[0] + 0.6 + h
                if w + 0.8 < seg:
                    sh.text((tx, mid), s, h, layer=layer, ha="center", rot=90, color=color)
                    sh.occupy((tx - h - 0.2, mid - w / 2, tx + 0.2, mid + w / 2))
                else:
                    off = -(h + 0.9) * text_side
                    if i > 0 and last_out == i - 1:
                        off *= 2
                    sh.text((tx + off, mid), s, h, layer=layer, ha="center", rot=90, color=color)
                    sh.line((q0[0], mid), (tx + off + (0.3 if text_side > 0 else -h - 0.3), mid), layer=layer,
                            lw=0.1, ec=color)
                    sh.occupy((tx + off - h - 0.2, mid - w / 2, tx + off + 0.2, mid + w / 2))
                    last_out = i
            sh.occupy((a[0] - 1, min(a[1], b[1]) - 1, a[0] + 1, max(a[1], b[1]) + 1))

    def dim(self, p1, p2, offset_mm=0, h=2.0, text=None, layer="DIM", color="black"):
        """Одиночный размер между p1 и p2 (горизонтальный/вертикальный по преобладающей оси)."""
        if abs(p2[0] - p1[0]) >= abs(p2[1] - p1[1]):
            at = p1[1] + offset_mm
            self.dim_chain([p1[0], p2[0]], "x", at, ext_from=[p1[1], p2[1]] if offset_mm else None,
                           labels=[text] if text else None, h=h, layer=layer, color=color)
        else:
            at = p1[0] + offset_mm
            self.dim_chain([p1[1], p2[1]], "y", at, ext_from=[p1[0], p2[0]] if offset_mm else None,
                           labels=[text] if text else None, h=h, layer=layer, color=color)

    def level_mark(self, p, s, h=2.0, layer="DIM", color="black"):
        """Отметка уровня на плане (прямоугольная рамка с отметкой, ГОСТ 21.101 п.5.5)."""
        q = self.P(p)
        w = text_w(s, h) + 1.6
        self.sh.rect(q[0], q[1], q[0] + w, q[1] + h + 1.4, layer=layer, lw=0.18, ec=color, fc="white", z=6.5)
        self.sh.text((q[0] + 0.8, q[1] + 0.7), s, h, layer=layer, color=color, z=7)
        self.sh.occupy((q[0], q[1], q[0] + w, q[1] + h + 1.4))


# ---------------------------------------------------------------- matplotlib
def _mpl_ls(ls):
    return LS.get(ls) or "solid"


def render_mpl(sh: Sheet, pdf=None, png=None, svg=None, dpi=110):
    fig = plt.figure(figsize=(sh.W / 25.4, sh.H / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, sh.W)
    ax.set_ylim(0, sh.H)
    ax.set_aspect("equal")
    ax.axis("off")
    for p in sh.prims:
        k = p["k"]
        z = p.get("z", 2)
        if k in ("poly", "shape"):
            if k == "poly":
                pts = p["pts"]
                if p["closed"]:
                    verts = pts + [pts[0]]
                    codes = [MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 1) + [MPath.CLOSEPOLY]
                else:
                    verts = pts
                    codes = [MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 1)
                closed = p["closed"]
            else:
                verts, codes = [], []
                for ring in p["rings"]:
                    verts += ring
                    codes += [MPath.MOVETO] + [MPath.LINETO] * (len(ring) - 2) + [MPath.CLOSEPOLY]
                closed = True
            path = MPath(verts, codes)
            if closed and p.get("fc"):
                ax.add_patch(PathPatch(path, fc=p["fc"], ec="none", lw=0, alpha=p.get("alpha", 1), zorder=z))
            if closed and p.get("hatch"):
                ax.add_patch(PathPatch(path, fc="none", ec=p["hc"], lw=0, hatch=p["hatch"], zorder=z + 0.01))
            if p.get("ec") and p.get("lw", 0) > 0:
                ax.add_patch(PathPatch(path, fc="none", ec=p["ec"], lw=p["lw"] * PT, linestyle=_mpl_ls(p["ls"]),
                                       zorder=z + 0.02, capstyle="butt", joinstyle="miter",
                                       alpha=p.get("alpha", 1) if not p.get("fc") else 1))
        elif k == "circle":
            if p.get("fc"):
                ax.add_patch(Circle(p["c"], p["r"], fc=p["fc"], ec="none", zorder=z, alpha=p.get("alpha", 1)))
            if p.get("ec"):
                ax.add_patch(Circle(p["c"], p["r"], fc="none", ec=p["ec"], lw=p["lw"] * PT,
                                    linestyle=_mpl_ls(p["ls"]), zorder=z + 0.01, alpha=p.get("alpha", 1)))
        elif k == "arc":
            ax.add_patch(Arc(p["c"], 2 * p["r"], 2 * p["r"], theta1=p["a0"], theta2=p["a1"], ec=p["ec"],
                             lw=p["lw"] * PT, linestyle=_mpl_ls(p["ls"]), zorder=z))
        elif k == "text":
            size = p["h"] / CAP * PT
            kw = {}
            if p.get("bg"):
                kw["bbox"] = dict(fc=p["bg"], ec="none", pad=0.4, alpha=0.85)
            ax.text(p["pos"][0], p["pos"][1], p["s"], fontsize=size, rotation=p["rot"], ha=p["ha"],
                    va=p["va"], color=p["color"], fontweight="bold" if p["bold"] else "normal", zorder=p["z"],
                    rotation_mode="anchor", linespacing=1.55, fontfamily=FONT, **kw)
    if pdf:
        fig.savefig(pdf, format="pdf")
    if svg:
        fig.savefig(svg, format="svg")
    if png:
        fig.savefig(png, dpi=dpi)
    plt.close(fig)


# ---------------------------------------------------------------- DXF
def _hex_rgb(c):
    from matplotlib.colors import to_rgb
    r, g, b = to_rgb(c)
    return int(r * 255), int(g * 255), int(b * 255)


def render_dxf(sh: Sheet, path):
    import ezdxf
    from ezdxf import colors as ezcolors
    doc = ezdxf.new("R2018", setup=True, units=4)  # мм
    doc.header["$LTSCALE"] = 1.0
    doc.header["$MEASUREMENT"] = 1
    st = doc.styles.get("Standard")
    st.dxf.font = "DejaVuSans.ttf"
    if "GOST" not in doc.styles:
        doc.styles.add("GOST", font="DejaVuSans.ttf")
    for name, (col, lt) in LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=col, linetype=lt)
    msp = doc.modelspace()
    S = sh.S

    def T(p):
        return (p[0] * S, p[1] * S)

    def attribs(p, lt=True):
        a = {"layer": p["layer"]}
        if p["layer"] not in doc.layers:
            doc.layers.add(p["layer"])
        if lt and p.get("ls", "solid") != "solid":
            a["linetype"] = DXF_LT.get(p["ls"], "DASHED")
            a["ltscale"] = S * 3.0
        a["lineweight"] = max(0, min(211, int(round(p.get("lw", 0.25) * 100 / 5)) * 5)) if p.get("lw") else 13
        return a

    def color(e, c):
        if c in (None, "none"):
            return
        r, g, b = _hex_rgb(c)
        if (r, g, b) == (0, 0, 0):
            e.dxf.color = 7
        else:
            e.rgb = (r, g, b)

    for p in sh.prims:
        k = p["k"]
        if k in ("poly", "shape"):
            rings = [p["pts"]] if k == "poly" else p["rings"]
            closed = p["closed"] if k == "poly" else True
            if closed and (p.get("fc") or p.get("hatch")):
                hatch = msp.add_hatch(dxfattribs={"layer": p["layer"]})
                if p.get("hatch"):
                    ch = p["hatch"][0]
                    pat, ang = HATCH_DXF.get(ch, ("ANSI31", 0))
                    dens = max(1, len(p["hatch"]))
                    hatch.set_pattern_fill(pat, scale=S * 0.55 / dens * (2.0 if pat == "DOTS" else 1.0), angle=ang)
                    color(hatch, p["hc"])
                else:
                    hatch.set_solid_fill()
                    color(hatch, p["fc"])
                    if p.get("alpha", 1) < 1:
                        hatch.transparency = 1 - p["alpha"]
                for i, ring in enumerate(rings):
                    hatch.paths.add_polyline_path([T(q) for q in ring], is_closed=True,
                                                  flags=1 if i == 0 else 16)
                if p.get("hatch") and p.get("fc") and p["fc"] not in ("white", "#ffffff"):
                    h2 = msp.add_hatch(dxfattribs={"layer": p["layer"]})
                    h2.set_solid_fill()
                    color(h2, p["fc"])
                    h2.transparency = 0.5
                    for i, ring in enumerate(rings):
                        h2.paths.add_polyline_path([T(q) for q in ring], is_closed=True, flags=1 if i == 0 else 16)
            if p.get("ec") and p.get("lw", 0) > 0:
                for ring in rings:
                    e = msp.add_lwpolyline([T(q) for q in ring], close=closed, dxfattribs=attribs(p))
                    color(e, p["ec"])
        elif k == "circle":
            if p.get("fc"):
                h = msp.add_hatch(dxfattribs={"layer": p["layer"]})
                h.set_solid_fill()
                color(h, p["fc"])
                h.paths.add_edge_path().add_arc(T(p["c"]), p["r"] * S, 0, 360)
            if p.get("ec"):
                e = msp.add_circle(T(p["c"]), p["r"] * S, dxfattribs=attribs(p))
                color(e, p["ec"])
        elif k == "arc":
            e = msp.add_arc(T(p["c"]), p["r"] * S, p["a0"], p["a1"], dxfattribs=attribs(p))
            color(e, p["ec"])
        elif k == "text":
            hv = {"left": 0, "center": 1, "right": 2}[p["ha"]]
            lines = p["s"].split("\n")
            for i, ln in enumerate(lines):
                if not ln:
                    continue
                dy = -i * p["h"] * 1.55
                cs, sn = math.cos(math.radians(p["rot"])), math.sin(math.radians(p["rot"]))
                x = p["pos"][0] - dy * sn
                y = p["pos"][1] + dy * cs
                va = p["va"]
                if va == "center":
                    y -= p["h"] / 2 * cs
                    x += p["h"] / 2 * sn
                elif va == "top":
                    y -= p["h"] * cs
                    x += p["h"] * sn
                e = msp.add_text(ln, height=p["h"] * S, rotation=p["rot"],
                                 dxfattribs={"layer": p["layer"], "style": "GOST"})
                e.set_placement(T((x, y)), align=ezdxf.enums.TextEntityAlignment.LEFT if hv == 0 else (
                    ezdxf.enums.TextEntityAlignment.CENTER if hv == 1 else ezdxf.enums.TextEntityAlignment.RIGHT))
                color(e, p["color"])
    doc.saveas(path)
