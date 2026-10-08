from draw import Sheet


def stub_sheet(ctx, title="", note="Лист-заглушка"):
    sh = Sheet("A3", 1)
    sh.text((40, 200), note, 5)
    sh.meta = {"stub": True, "note": note}
    return sh


SHEETS = {}
