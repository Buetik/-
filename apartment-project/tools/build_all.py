"""Сборка всех листов рабочей документации и альбома.

  python3 tools/build_all.py            — все листы + альбом + статусы в sheet-register.json
  python3 tools/build_all.py АР-01 ЭМ-01 — только указанные листы (без альбома и статусов)

Выход: 03-drawings/pdf/<код>.pdf, 03-drawings/dxf/<код>.dxf, 03-drawings/preview/<код>.png,
       03-drawings/pdf/album.pdf (в порядке ведомости).
"""
from __future__ import annotations

import inspect
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model as m  # noqa: E402
import stamp  # noqa: E402
from sheets_common import Overflow  # noqa: E402
import sheets_ar  # noqa: E402
import sheets_eng  # noqa: E402
import sheets_misc  # noqa: E402
import sheets_details  # noqa: E402

PDF = m.DRAW / "pdf"
DXF = m.DRAW / "dxf"
PNG = m.DRAW / "preview"

SECTION = {"ОД": "Общие данные", "АР": "Архитектурные решения", "КД": "Концепция дизайна",
           "ЭО": "Электроосвещение", "ЭМ": "Силовое электрооборудование и слаботочные сети",
           "ВК": "Водопровод и канализация", "ОВ": "Отопление и вентиляция", "СП": "Спецификации",
           "СМ": "Смета"}

# актуализация ведомости под фактические разделы (коды сохраняются, новые — добавляются)
TITLES = {
    "АР-02": "Планировочное решение (принятый вариант D1). Экспликация помещений",
    "АР-03": "Варианты планировки A, B, C (рассмотренные)",
    "АР-04": "Подварианты D1 (принят) и D2 (альтернатива)",
    "АР-17": "Узлы 1–6: потолки, ниши штор, люки, стыки покрытий, порог ванной, гидроизоляция",
}
ADD_AFTER = {
    "АР-17": [{"code": "АР-18", "title": "Узлы 7–11: трап, зашивка окна O1, ниша экрана, порог кухня–балкон, облицовка душа",
               "scale": "1:10", "owner": "pib-finishes", "status": "todo", "file": "03-drawings/pdf/АР-18.pdf"}],
    "ВК-01": [{"code": "ВК-02", "title": "Фрагменты 1:25: ванная, постирочная, мойка кухни — водопровод и канализация (уклоны)",
               "scale": "1:25", "owner": "pib-engineering", "status": "todo", "file": "03-drawings/pdf/ВК-02.pdf"}],
}
SCALE_FIX = {"АР-03": "1:100", "АР-04": "1:75"}


def actualize(reg):
    out = []
    codes = {r["code"] for r in reg}
    for r in reg:
        if r["code"] in TITLES:
            r["title"] = TITLES[r["code"]]
        if r["code"] in SCALE_FIX:
            r["scale"] = SCALE_FIX[r["code"]]
        out.append(r)
        for add in ADD_AFTER.get(r["code"], []):
            if add["code"] not in codes:
                out.append(dict(add))
    # убрать дубли, если уже были добавлены
    seen, res = set(), []
    for r in out:
        if r["code"] in seen:
            continue
        seen.add(r["code"])
        res.append(r)
    return res


def registry():
    reg = {}
    for mod in (sheets_ar, sheets_eng, sheets_misc, sheets_details):
        reg.update(mod.SHEETS)
    return reg


def make_pages(rec, ctx, fns):
    """Построить лист(ы) без штампа. Возвращает список Sheet."""
    code = rec["code"]
    fn = fns.get(code) or sheets_misc.stub_sheet
    sig = inspect.signature(fn).parameters
    try:
        res = fn(ctx)
    except Overflow as e:
        if "fmt" in sig:
            print(f"  {code}: {e} -> A2")
            res = fn(ctx, fmt="A2")
        else:
            raise
    return res if isinstance(res, list) else [res]


def save_pages(rec, pages, first_no, total):
    from pypdf import PdfWriter, PdfReader
    code = rec["code"]
    for d in (PDF, DXF, PNG):
        d.mkdir(parents=True, exist_ok=True)
    tmp = []
    for k, sh in enumerate(pages):
        meta = getattr(sh, "meta", {}) or {}
        if code == "ОД-01":
            stamp.title_frame(sh)
        else:
            title = rec["title"] + (f" (лист {k + 1} из {len(pages)})" if len(pages) > 1 else "")
            stamp.stamp(sh, code, title, SECTION.get(code[:2], ""), first_no + k, total,
                        scale=meta.get("scale", rec.get("scale", "—")))
        suf = "" if k == 0 else f"-{k + 1}"
        tp = PDF / f".tmp-{code}{suf}.pdf"
        sh.save(pdf=str(tp), png=str(PNG / f"{code}{suf}.png"), dxf=str(DXF / f"{code}{suf}.dxf"), dpi=130)
        tmp.append(tp)
    w = PdfWriter()
    for tp in tmp:
        for page in PdfReader(str(tp)).pages:
            w.add_page(page)
    with open(PDF / f"{code}.pdf", "wb") as f:
        w.write(f)
    for tp in tmp:
        tp.unlink()


def main(argv):
    reg = actualize(m.load_register())
    only = set(argv)
    fns = registry()
    ctx = {"register": reg}
    built, failed, stubs = [], [], []
    pages = {}
    # проход 1: все листы, кроме ведомости (ей нужны номера страниц)
    for rec in reg:
        if rec["code"] == "ОД-02":
            continue
        if only and rec["code"] not in only:
            # для нумерации в выборочном режиме считаем 1 страницу
            pages[rec["code"]] = None
            continue
        try:
            pages[rec["code"]] = make_pages(rec, ctx, fns)
        except Exception:
            traceback.print_exc()
            failed.append(rec["code"])
            pages[rec["code"]] = None

    def numbering(od02_n):
        nos, n = {}, 1
        for rec in reg:
            nos[rec["code"]] = n
            if rec["code"] == "ОД-02":
                n += od02_n
            else:
                pl = pages.get(rec["code"])
                n += len(pl) if pl else 1
        return nos, n - 1

    od2 = 1
    for _ in range(3):
        nos, total = numbering(od2)
        for rec in reg:
            pl = pages.get(rec["code"])
            rec["format"] = pl[0].fmt if pl else rec.get("format", "")
            rec["pages"] = len(pl) if pl else rec.get("pages", 1)
        ctx["pages"] = {c: (str(v) if not pages.get(c) or len(pages[c]) == 1 else f"{v}–{v + len(pages[c]) - 1}")
                        for c, v in nos.items()}
        rec2 = next(r for r in reg if r["code"] == "ОД-02")
        p2 = make_pages(rec2, ctx, fns)
        if len(p2) == od2:
            pages["ОД-02"] = p2
            break
        od2 = len(p2)
        pages["ОД-02"] = p2
    nos, total = numbering(len(pages["ОД-02"]))
    for rec in reg:
        code = rec["code"]
        pl = pages.get(code)
        if not pl or (only and code not in only):
            continue
        try:
            save_pages(rec, pl, nos[code], total)
            meta = getattr(pl[0], "meta", {}) or {}
            rec["format"] = pl[0].fmt
            rec["pages"] = len(pl)
            rec["dxf"] = f"03-drawings/dxf/{code}.dxf"
            if meta.get("stub"):
                stubs.append(code)
                rec["status"] = "stub"
                rec["note"] = meta.get("note", "лист-заглушка")
            else:
                rec["status"] = "drawn"
                rec.pop("note", None)
                if meta.get("note"):
                    rec["note"] = meta["note"]
            built.append(code)
            print(f"{nos[code]:>2} {code:<6} {pl[0].fmt} x{len(pl)} ok")
        except Exception:
            traceback.print_exc()
            failed.append(code)
    if not only:
        from pypdf import PdfWriter, PdfReader
        w = PdfWriter()
        for rec in reg:
            p = PDF / f"{rec['code']}.pdf"
            if p.exists():
                for page in PdfReader(str(p)).pages:
                    w.add_page(page)
        with open(PDF / "album.pdf", "wb") as f:
            w.write(f)
        m.save_register(reg)
        print("album:", PDF / "album.pdf", "pages:", total)
    print("built", len(built), "failed", failed, "stubs", stubs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
