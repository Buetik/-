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
    for mod in (sheets_ar, sheets_eng, sheets_misc):
        reg.update(mod.SHEETS)
    return reg


def build_one(rec, no, total, ctx, fns):
    code = rec["code"]
    fn = fns.get(code)
    if fn is None:
        fn = sheets_misc.stub_sheet
    sig = inspect.signature(fn).parameters
    try:
        sh = fn(ctx)
    except Overflow as e:
        if "fmt" in sig:
            print(f"  {code}: {e} -> A2")
            sh = fn(ctx, fmt="A2")
        else:
            raise
    meta = getattr(sh, "meta", {})
    if code == "ОД-01":
        stamp.title_frame(sh)
    else:
        stamp.stamp(sh, code, rec["title"], SECTION.get(code[:2], ""), no, total,
                    scale=meta.get("scale", rec.get("scale", "—")))
    PDF.mkdir(parents=True, exist_ok=True)
    DXF.mkdir(parents=True, exist_ok=True)
    PNG.mkdir(parents=True, exist_ok=True)
    pdf = PDF / f"{code}.pdf"
    sh.save(pdf=str(pdf), png=str(PNG / f"{code}.png"), dxf=str(DXF / f"{code}.dxf"), dpi=130)
    return sh, meta


def main(argv):
    reg = actualize(m.load_register())
    only = set(argv)
    fns = registry()
    total = len(reg)
    ctx = {"register": reg}
    built, failed, stubs = [], [], []
    for no, rec in enumerate(reg, start=1):
        if only and rec["code"] not in only:
            continue
        try:
            sh, meta = build_one(rec, no, total, ctx, fns)
            rec["format"] = sh.fmt
            if meta.get("stub"):
                stubs.append(rec["code"])
                rec["status"] = "stub"
                rec["note"] = meta.get("note", "лист-заглушка: нет исходных данных")
            else:
                rec["status"] = "drawn"
                rec.pop("note", None)
                if meta.get("note"):
                    rec["note"] = meta["note"]
            rec["dxf"] = f"03-drawings/dxf/{rec['code']}.dxf"
            built.append(rec["code"])
            print(f"{no:>2} {rec['code']:<6} {sh.fmt} ok")
        except Exception:
            traceback.print_exc()
            failed.append(rec["code"])
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
        print("album:", PDF / "album.pdf")
    print("built", len(built), "failed", failed, "stubs", stubs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
