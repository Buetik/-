"""Общие блоки листов: раскладка правой колонки, легенды, примечания."""
from __future__ import annotations

from draw import Sheet, wrap, text_w


class Overflow(Exception):
    pass


class Flow:
    """Раскладка блоков сверху вниз по колонкам (x0, x1, y_top, y_bottom)."""

    def __init__(self, sh: Sheet, cols, gap=4.0):
        self.sh = sh
        self.cols = cols
        self.i = 0
        self.y = cols[0][2]
        self.gap = gap

    def take(self, h):
        while self.i < len(self.cols):
            x0, x1, yt, yb = self.cols[self.i]
            if self.y - h >= yb - 0.01:
                top = self.y
                self.y -= h + self.gap
                return x0, top, x1 - x0
            self.i += 1
            if self.i < len(self.cols):
                self.y = self.cols[self.i][2]
        raise Overflow(f"не помещается блок высотой {h:.1f} мм")

    def _fitcols(self, cols):
        x0, x1, _, _ = self.cols[min(self.i, len(self.cols) - 1)]
        w = x1 - x0
        return cols if sum(cols) <= w + 0.01 else [c * w / sum(cols) for c in cols]

    def table(self, cols, rows, header=None, h=1.8, title=None, **kw):
        sh = self.sh
        cols = self._fitcols(cols)
        hh = sh.table_height(cols, rows, h=h, header=header, title=title, **{k: v for k, v in kw.items()
                                                                               if k in ("max_lines", "bold_rows")})
        i0 = self.i
        x, top, w = self.take(hh)
        if self.i != i0:
            # перешли в другую колонку — пересчёт ширины
            return self._retake(cols, rows, header, h, title, hh, **kw)
        scale = 1.0
        if sum(cols) > w + 0.01:
            scale = w / sum(cols)
            cols = [c * scale for c in cols]
        return sh.table(x, top, cols, rows, h=h, header=header, title=title, **kw)

    def _retake(self, cols, rows, header, h, title, hh, **kw):
        # откат и повтор в новой колонке с её шириной
        self.y += hh + self.gap
        cols = self._fitcols(cols)
        ml = {k: v for k, v in kw.items() if k in ("max_lines", "bold_rows")}
        hh = self.sh.table_height(cols, rows, h=h, header=header, title=title, **ml)
        x, top, w = self.take(hh)
        return self.sh.table(x, top, cols, rows, h=h, header=header, title=title, **kw)

    def split_table(self, cols, rows, header=None, h=1.8, title=None, **kw):
        """Таблица с переносом на следующую колонку (повтор шапки)."""
        sh = self.sh
        ml = {k: v for k, v in kw.items() if k in ("max_lines", "bold_rows")}
        cols0 = cols
        rows = list(rows)
        first = True
        while rows:
            x0, x1, yt, yb = self.cols[self.i]
            cols = self._fitcols(cols0)
            avail = self.y - yb
            n = len(rows)
            while n > 0 and sh.table_height(cols, rows[:n], h=h, header=header,
                                            title=(title if first else None), **ml) > avail:
                n -= 1
            if n == 0:
                self.i += 1
                if self.i >= len(self.cols):
                    raise Overflow("таблица не помещается")
                self.y = self.cols[self.i][2]
                continue
            t = title if first else (f"{title} (продолжение)" if title else None)
            hh = sh.table_height(cols, rows[:n], h=h, header=header, title=t, **ml)
            x, top, w = self.take(hh)
            sh.table(x, top, cols, rows[:n], h=h, header=header, title=t, **kw)
            rows = rows[n:]
            first = False

    def text(self, s, h=2.0, title=None, title_h=2.5, lsp=1.5):
        sh = self.sh
        x0, x1, _, _ = self.cols[self.i]
        w = x1 - x0
        hh = sh.paragraph_height(w, s, h, lsp) + ((title_h + 2.0) if title else 0)
        x, top, w = self.take(hh)
        if title:
            sh.text((x, top - title_h), title, title_h, bold=True)
            top -= title_h + 2.0
        sh.paragraph(x, top, w, s, h, lsp=lsp)

    def legend(self, items, title="Условные обозначения", h=1.8, sym_w=12.0):
        """items: [(fn(sh, x, y_mid), text)], fn рисует знак в поле sym_w×4."""
        sh = self.sh
        x0, x1, _, _ = self.cols[self.i]
        w = x1 - x0
        rows = []
        for fn, txt in items:
            lines = wrap(txt, w - sym_w - 2, h)
            rows.append((fn, lines, max(4.2, len(lines) * h * 1.45 + 1.6)))
        tot = 2.5 + 2.0 + sum(r[2] for r in rows)
        x, top, w = self.take(tot)
        sh.text((x, top - 2.5), title, 2.5, bold=True)
        y = top - 4.5
        for fn, lines, rh in rows:
            ymid = y - rh / 2
            fn(sh, x + 1, ymid)
            ty = ymid + (len(lines) - 1) * h * 1.45 / 2 - h / 2
            for ln in lines:
                sh.text((x + sym_w + 1.5, ty), ln, h)
                ty -= h * 1.45
            y -= rh
        sh.occupy((x, y, x + w, top))


# --- знаки для легенд
def sym_fill(fc, ec="black", hatch=None, hc=None, ls="solid", lw=0.3):
    def f(sh, x, y):
        sh.rect(x, y - 1.6, x + 10, y + 1.6, fc=fc, ec=ec, hatch=hatch, hc=hc, ls=ls, lw=lw, layer="TEXT", z=5)
    return f


def sym_line(ec="black", ls="solid", lw=0.35):
    def f(sh, x, y):
        sh.line((x, y), (x + 10, y), ec=ec, ls=ls, lw=lw, layer="TEXT", z=5)
    return f


def sym_circle(ec="black", fc=None, r=1.4, inner=None):
    def f(sh, x, y):
        sh.circle((x + 5, y), r, ec=ec, fc=fc, lw=0.3, layer="TEXT", z=5)
        if inner:
            sh.circle((x + 5, y), r * 0.45, ec=inner, fc=inner, lw=0.1, layer="TEXT", z=5.1)
    return f


def sym_text(s, h=1.8, color="black", box=True):
    def f(sh, x, y):
        w = text_w(s, h)
        if box:
            sh.rect(x + 5 - w / 2 - 0.8, y - h / 2 - 0.8, x + 5 + w / 2 + 0.8, y + h / 2 + 0.8, ec=color, lw=0.2,
                    layer="TEXT", fc="white", z=5)
        sh.text((x + 5, y - h / 2), s, h, ha="center", color=color, z=5.1)
    return f
