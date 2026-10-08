"""АР-17, АР-18 — узлы 1:10 по 03-drawings/details.md (схематично, послойно, с выносками).

Толщины слоёв и отметки — из details.md и floors.json (pies). Ширины участков условны (разрыв).
"""
from __future__ import annotations

import model as m
from draw import Sheet, View, text_w, wrap
from sheets_common import Overflow

STAMP_TOP = 60.0
SC = 10

MATS = {
    "rc": dict(fc="#d9d9d9", hatch="//", hc="#555555"),
    "brick": dict(fc="#efd2c4", hatch="///", hc="#a0522d"),
    "plaster": dict(fc="#f3efe6"),
    "screed": dict(fc="#e4e4e4", hatch="..", hc="#777777"),
    "cps": dict(fc="#ececec", hatch="..", hc="#999999"),
    "gkl": dict(fc="#ffffff", hatch="\\\\", hc="#aaaaaa"),
    "metal": dict(fc="#7f8c8d"),
    "insul": dict(fc="#fff3b0", hatch="--", hc="#c9a227"),
    "xps": dict(fc="#cdeccd", hatch="--", hc="#4a9a4a"),
    "wood": dict(fc="#e3c9a0", hatch="||", hc="#b08850"),
    "tile": dict(fc="#c8dbe8"),
    "glue": dict(fc="#bdbdbd"),
    "wp": dict(fc="#2e86c1"),
    "pu": dict(fc="#f7f1e3"),
    "film": dict(fc="#444444"),
    "cork": dict(fc="#c49a6c"),
    "brass": dict(fc="#b39b6b"),
    "lvt": dict(fc="#c7a77d"),
    "mdf": dict(fc="#d9cfc0"),
    "glass": dict(fc="#d6eaf8"),
    "air": dict(fc=None),
    "mat": dict(fc="#e67e22"),
}


class Node:
    def __init__(self, no, title, bbox):
        self.no = no
        self.title = title
        self.bbox = bbox          # модельные мм (x0, z0, x1, z1)
        self.items = []           # (kind, data)
        self.calls = []           # (n, text, anchor)
        self.levels = []          # (x, z, text)

    def R(self, x0, z0, x1, z1, mat, call=None, ls="solid"):
        self.items.append(("rect", (min(x0, x1), min(z0, z1), max(x0, x1), max(z0, z1), mat, ls)))
        if call:
            self.call(call, ((x0 + x1) / 2, (z0 + z1) / 2))

    def Pg(self, pts, mat, call=None, anchor=None):
        self.items.append(("poly", (pts, mat)))
        if call:
            c = anchor or (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            self.call(call, c)

    def L(self, a, b, col="black", lw=0.3, ls="solid", call=None):
        self.items.append(("line", (a, b, col, lw, ls)))
        if call:
            self.call(call, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))

    def C(self, c, r, mat="air", call=None):
        self.items.append(("circle", (c, r, mat)))
        if call:
            self.call(call, c)

    def call(self, text, anchor):
        n = len(self.calls) + 1
        self.calls.append((n, text, anchor))

    def lev(self, x, z, text=None):
        self.levels.append((x, z, text or (f"{z / 1000:+.3f}".replace("+0.000", "±0.000").replace(".", ","))))

    def stack(self, x0, x1, pie, slab_top=None, slab_th=80, mat_map=None, with_calls=True, skip_slab=False):
        """Пирог пола из floors.json: первый слой — отметка верха плиты, далее толщины."""
        layers = pie["layers"]
        z = layers[0][1] if slab_top is None else slab_top
        if not skip_slab:
            self.R(x0, z - slab_th, x1, z, "rc", call=(layers[0][0] + f", верх {z:g}") if with_calls else None)
        for nm, t in layers[1:]:
            mat = pick_mat(nm, mat_map)
            if t and t > 0:
                self.R(x0, z, x1, z + t, mat, call=f"{nm} — {t:g}" if with_calls else None)
                z += t
            else:
                self.L((x0, z), (x1, z), col="#2e86c1" if "гидро" in nm or "плёнк" in nm else "#555", lw=0.35,
                       ls="dashed", call=nm if with_calls else None)
        return z


def pick_mat(nm, mat_map=None):
    t = nm.lower()
    if mat_map:
        for k, v in mat_map.items():
            if k in t:
                return v
    for k, v in (("стяжка с водяным", "screed"), ("подиум", "cps"), ("стяжка", "cps"), ("гидроизол", "wp"),
                 ("клей", "glue"), ("керамогранит", "tile"), ("доска", "wood"), ("lvt", "lvt"), ("xps", "xps"),
                 ("мат ", "mat"), ("грунт", "glue"), ("ремонт", "glue"), ("самовыравн", "cps")):
        if k in t:
            return v
    return "glue"


def draw_node(sh, nd: Node, x, ytop, list_w=70, h=1.35):
    """Узел: заголовок, изображение 1:10, выноски с номерами, перечень позиций справа."""
    x0, z0, x1, z1 = nd.bbox
    w = (x1 - x0) / SC
    hh = (z1 - z0) / SC
    sh.text((x, ytop - 3), f"Узел {nd.no}. {nd.title}", 2.2, bold=True)
    sh.text((x, ytop - 6.2), "М 1:10 (схематично, по details.md)", 1.5, color="#555555")
    v = View(sh, SC, (x0, z0), (x + 2, ytop - 10 - hh))
    sh.clip = (x + 2, ytop - 10 - hh, x + 2 + w, ytop - 10)
    for kind, d in nd.items:
        if kind == "rect":
            a, b, c, e, mat, ls = d
            st = MATS.get(mat, {})
            v.rect(a, b, c, e, layer="AR-FIN", fc=st.get("fc"), hatch=st.get("hatch"), hc=st.get("hc"),
                   ec="black" if mat != "air" else "#777", lw=0.18, ls=ls if mat != "air" else "dashed", z=2)
        elif kind == "poly":
            pts, mat = d
            st = MATS.get(mat, {})
            v.poly(pts, layer="AR-FIN", fc=st.get("fc"), hatch=st.get("hatch"), hc=st.get("hc"), ec="black", lw=0.18,
                   z=2.2)
        elif kind == "line":
            a, b, col, lw, ls = d
            v.line(a, b, layer="AR-FIN", ec=col, lw=lw, ls=ls, z=3)
        elif kind == "circle":
            c, r, mat = d
            st = MATS.get(mat, {})
            v.circle(c, r_mm=r, layer="AR-FIN", ec="black", fc=st.get("fc"), lw=0.2, z=3)
    for lx, lz, t in nd.levels:
        q = v.P((lx, lz))
        sh.poly([q, (q[0] - 1.2, q[1] + 1.6), (q[0] + 1.2, q[1] + 1.6)], layer="DIM", ec="black", lw=0.18, fc="white",
                z=7)
        sh.line((q[0], q[1] + 1.6), (q[0] + 9, q[1] + 1.6), layer="DIM", lw=0.18, z=7)
        sh.text((q[0] + 0.6, q[1] + 2.1), t, 1.5, layer="DIM", z=7)
    sh.clip = None
    sh.rect(x + 2, ytop - 10 - hh, x + 2 + w, ytop - 10, layer="AR-FIN", ec="#999999", lw=0.1, ls="dashdot", z=1)
    sh.occupy((x + 2, ytop - 10 - hh, x + 2 + w, ytop - 10))
    # выноски — номера в кружках
    for n, t, a in nd.calls:
        q = v.P(a)
        sh.label(q, str(n), 1.5, color="#1a1a1a", radius=(3, 5, 7.5, 10, 13), lcolor="#333333", bold=True)
    # перечень
    lx = x + 2 + w + 4
    y = ytop - 10
    for n, t, a in nd.calls:
        lines = wrap(t, list_w - 6, h)
        sh.text((lx, y - h), f"{n}.", h, bold=True)
        for ln in lines:
            sh.text((lx + 4.5, y - h), ln, h)
            y -= h * 1.45
        y -= 0.6
    sh.occupy((lx, y, lx + list_w, ytop - 10))
    return max(hh + 12, ytop - y + 2)


def node_size(nd, list_w=70, h=1.35):
    x0, z0, x1, z1 = nd.bbox
    w = (x1 - x0) / SC
    hh = (z1 - z0) / SC
    lh = sum(len(wrap(t, list_w - 6, h)) * h * 1.45 + 0.6 for _, t, _ in nd.calls)
    return w + 8 + list_w, max(hh, lh) + 13


# ---------------------------------------------------------------- узлы
def n1a():
    nd = Node("1а", "Примыкание ГКЛ-потолка к стене, спальня/детская +2700", (-150, 2560, 450, 2860))
    nd.R(-150, 2560, -15, 2750, "brick", "Стена (кладка/ж/б) + штукатурка")
    nd.R(-15, 2560, 0, 2750, "plaster")
    nd.R(-150, 2750, 450, 2860, "rc", "Плита перекрытия, низ +2750")
    nd.R(0, 2712.5, 28, 2740, "metal", "ПН 28/27 по демпферной ленте, дюбели в стену шаг 400")
    nd.R(28, 2712.5, 450, 2716, "metal", "ПП 60/27, низ +2712,5")
    nd.R(300, 2716, 306, 2750, "metal", "Прямой подвес, шаг 600")
    nd.C((170, 2731), 10, "air", "Гофра нг ≤ Ø20 в зазоре 37,5 (D15)")
    nd.R(0, 2700, 450, 2712.5, "gkl", "ГКЛ (ГСП-А) 12,5, низ +2700; серпянка, шпаклёвка, окраска C1")
    nd.Pg([(0, 2630), (0, 2700), (80, 2700), (80, 2690), (15, 2640)], "pu",
          "Карниз M04 80×70: клей только к стене, к потолку — акриловый герметик 3 мм")
    nd.lev(380, 2700)
    nd.lev(380, 2750)
    return nd


def n1b():
    nd = Node("1б", "Потолок кухни, прихожей, коридора +2650 (пленум 100), спот", (-150, 2560, 450, 2860))
    nd.R(-150, 2560, -15, 2750, "brick", "Стена + штукатурка")
    nd.R(-15, 2560, 0, 2750, "plaster")
    nd.R(-150, 2750, 450, 2860, "rc", "Плита перекрытия, низ +2750")
    nd.R(0, 2662.5, 28, 2690, "metal", "ПН 28/27 по демпферной ленте")
    nd.R(28, 2662.5, 450, 2666, "metal", "ПП 60/27 на подвесах с тягой, низ +2662,5")
    nd.R(380, 2666, 386, 2750, "metal", "Подвес с тягой")
    nd.R(0, 2650, 450, 2662.5, "gkl", "ГКЛ 12,5, низ +2650 (без перепада на границе кухня/прихожая)")
    nd.R(200, 2650, 270, 2730, "metal", "Встроенный спот L2/L15/L16, монтажная глубина ≤ 80 (пленум 87,5)")
    nd.Pg([(0, 2580), (0, 2650), (80, 2650), (80, 2640), (15, 2590)], "pu", "Карниз 80×70 (к стене)")
    nd.lev(330, 2650)
    return nd


def n1c():
    nd = Node("1в", "Ванная/постирочная: теневое примыкание ГКЛВ к плитке", (-120, 2330, 330, 2800))
    nd.R(-120, 2330, -20, 2750, "brick", "Стена/перегородка")
    nd.R(-20, 2330, -10, 2450, "glue", "Гидроизоляция + клей C2TE S1")
    nd.R(-10, 2330, 0, 2450, "tile", "Плитка стены до потолка")
    nd.R(0, 2450, 10, 2460, "metal", "Теневой профиль 10×10 под окраску, на клею-герметике поверх плитки")
    nd.R(-120, 2750, 330, 2800, "rc", "Плита перекрытия")
    nd.R(10, 2462.5, 330, 2466, "metal", "ПП 60/27 оцинк. на подвесах (пленум 300/250: EF1/EF2)")
    nd.R(10, 2450, 330, 2462.5, "gkl", "ГКЛВ 12,5, низ +2450 (ванная) / +2500 (постирочная); шов 10 — тень")
    nd.lev(250, 2450, "+2,450")
    return nd


def n2():
    nd = Node("2", "Ниша под карниз штор CN-1/CN-2 (+2700, глубина 62)", (-150, 2600, 450, 2860))
    nd.R(-150, 2600, 0, 2750, "brick", "Наружная стена W1 (откос окна)")
    nd.R(-150, 2750, 450, 2860, "rc", "Плита; дно ниши — шпаклёвка + C1")
    nd.R(200, 2700, 212.5, 2750, "gkl", "Борт ниши ГКЛ 12,5 на ПН/ПП, вертикальная грань 62")
    nd.R(212.5, 2700, 450, 2712.5, "gkl", "Потолок ГКЛ +2700")
    nd.R(45, 2715, 75, 2750, "metal", "Трек ряд 1 (блэкаут) ≤ 35, ось 60 от W1, дюбели в плиту")
    nd.R(105, 2715, 135, 2750, "metal", "Трек ряд 2 (тюль), ось 120 от W1")
    nd.Pg([(212.5, 2630), (212.5, 2700), (292, 2700), (292, 2690), (227, 2640)], "pu",
          "Карниз M04 по кромке ниши (y 8711)")
    nd.lev(400, 2700)
    return nd


def n3():
    nd = Node("3", "Люк-невидимка H1/H3 в коробе (сечение в плане)", (-60, 0, 520, 160))
    nd.R(-60, 0, 0, 160, "air", "Полость короба стояков (узел N1/N2)")
    nd.R(0, 0, 25, 160, "gkl", "Короб: ПП 60/27 + 2×ГВЛВ 12,5")
    nd.R(25, 0, 30, 160, "glue", "Клей C2TE S1")
    nd.R(30, 0, 40, 160, "tile", "Плитка/«кабанчик»; швы совпадают с контуром люка")
    nd.R(40, 0, 60, 160, "air")
    nd.R(140, 40, 152, 160, "metal", "Алюминиевая рама люка к каркасу короба")
    nd.R(152, 40, 470, 52.5, "gkl", "Полотно ЦСП/ГВЛВ 12,5 на магнитно-нажимных защёлках (push), уплотнитель")
    nd.R(152, 52.5, 470, 60.5, "glue")
    nd.R(152, 60.5, 470, 70.5, "tile", "Облицовка полотна той же плиткой; по контуру — силикон в тон (зазор 2)")
    nd.R(470, 40, 482, 160, "metal")
    return nd


def n4():
    nd = Node("4", "Стык доска/керамогранит J2 (и шов J4 у дверей D1/D2)", (-320, -200, 320, 40))
    z = nd.stack(-320, -3, m.FL["pies"]["P-OAK"], slab_th=80)
    nd.stack(3, 320, m.FL["pies"]["P-TILE-HALL"], slab_th=80, skip_slab=True, with_calls=False)
    nd.R(3, -100, 320, -180, "rc")
    tz = -20
    for nm, t in m.FL["pies"]["P-TILE-HALL"]["layers"][2:]:
        nd.R(3, tz, 320, tz + t, pick_mat(nm))
        tz += t
    nd.call("Справа: P-TILE-HALL — " + "; ".join(f"{n} {t:g}" for n, t in m.FL["pies"]["P-TILE-HALL"]["layers"][2:]),
            (200, -10))
    nd.R(-3, -20, 3, 0, "cork", "Пробковый компенсатор 5 на всю толщину покрытия")
    nd.R(-1.5, -10, 1.5, 0, "brass", "Латунная вставка C8 3×10 заподлицо, на эпоксидном/MS-клее, без саморезов")
    nd.lev(150, 0)
    return nd


def n5():
    nd = Node("5", "Порог-ступень ванной D3 (J5, D20)", (-360, -200, 420, 160))
    nd.stack(-360, -40, m.FL["pies"]["P-OAK"], slab_th=80, with_calls=False)
    nd.call("Коридор: P-OAK, доска ±0", (-200, -5))
    zb = nd.stack(40, 420, m.FL["pies"]["P-BATH"], slab_th=80, skip_slab=True, with_calls=False)
    nd.R(-40, -180, 40, -100, "rc")
    nd.R(-40, -20, 40, 70, "cps", "Основание порога — ЦПС по нижней гидроизоляции")
    nd.R(-40, 70, 40, 90, "tile", "Ступень-порог керамогранит C9 20, верх +90; фаска + контрастная полоса")
    nd.L((-40, 90), (40, 90), col="#2e86c1", lw=0.4, ls="dashed",
         call="Гидроизоляция подиума заведена на порог, под коробку и на откосы на 200")
    nd.R(-30, 90, 30, 160, "mdf", "Коробка D3 на пороге (верх +2125), полотно низ +110")
    nd.call("Ванная: P-BATH, пол +80 (порог на 10 выше — ограничитель воды)", (250, 60))
    nd.lev(-300, 0)
    nd.lev(-30, 90, "+0,090")
    nd.lev(330, 80, "+0,080")
    return nd


def n6():
    nd = Node("6", "Гидроизоляция ванной (P-BATH) и рамка-бортик коллектора U14", (-130, -200, 640, 330))
    nd.R(-130, -200, -10, 330, "brick", "Стена ванной")
    nd.R(-10, -20, -8, 280, "wp", "Нижняя ГИ: заход на стену 200 над полом ванной (до +280)")
    nd.R(-8, 80, -6, 280, "wp", "Основная ГИ 2 слоя: заход 200; в душе и за ванной — до потолка +2450")
    nd.R(-6, 80, 0, 280, "tile")
    nd.stack(0, 420, m.FL["pies"]["P-BATH"], slab_th=80)
    nd.R(420, -180, 640, -100, "rc")
    nd.R(420, -100, 640, -20, "screed")
    nd.R(420, -20, 440, 100, "cps", "Бортик ЦСП 20 / нерж. уголок, на клею к стяжке, верх +100; без анкеров")
    nd.R(440, -20, 640, -18.5, "wp", "Ниша коллектора: подиум не заливается, дно — стяжка с нижней ГИ")
    nd.R(500, -18.5, 620, 330, "air", "Коллектор U14 (h ≈ 400), доступ через съёмный цоколь тумбы F71")
    nd.lev(200, 80, "+0,080")
    nd.lev(430, 100, "+0,100")
    return nd


def n7():
    nd = Node("7", "Трап линейный низкий у облицовки VK-C1 (D18)", (-100, -130, 1020, 220))
    nd.R(-100, -130, 1020, -100, "rc", "Плита")
    nd.R(-100, -100, 1020, -20, "screed", "Стяжка с водяным ТП, верх −20 — не резать (D3/D4)")
    nd.L((-100, -18.5), (900, -18.5), col="#2e86c1", lw=0.4, call="Нижняя гидроизоляция")
    nd.Pg([(0, -18.5), (735, -18.5), (735, 48.6), (0, 60)], "cps",
          "Подиум ЦПС М300 с уклоном 1,5 % от стекла (x 6641, +80) к трапу")
    nd.Pg([(0, 60), (735, 48.6), (735, 58.6), (0, 70)], "glue", "Основная ГИ + клей C2TE S1")
    nd.Pg([(0, 70), (735, 58.6), (735, 68.6), (0, 80)], "tile", "Плитка 600×1200 R10/B, подрезка у трапа 735")
    nd.R(735, -1.4, 805, 68.6, "metal", "Трап 800 низкий: низ корпуса −1,4, решётка +68,6; фланец вклеен в ГИ")
    nd.C((850, 6.6), 25, "air", "Отвод Ø50 к К1 U6 (0,4 м, i = 2 %)")
    nd.R(805, -18.5, 900, 220, "gkl", "Облицовка VK-C1 ≈ 95: ПП 60/27 + 2×ГВЛВ/ЦСП 12,5 + ГИ + плитка")
    nd.R(900, -100, 1020, 220, "brick", "Перегородка W14")
    nd.R(-30, 80, -20, 220, "glass", "Стекло душа F68 (профиль на клею)")
    nd.lev(100, 80, "+0,080")
    nd.lev(700, 68.6, "+0,069")
    return nd


def n8():
    nd = Node("8", "Зашивка окна O1 под буазери (горизонтальное сечение)", (-430, -320, 80, 560))
    nd.R(-420, -320, -270, 0, "insul", "Наружный слой/утеплитель стены W2")
    nd.R(-270, -320, -21, 0, "brick", "Кладка 250")
    nd.R(-21, -320, 0, 0, "plaster")
    nd.R(-330, 0, -260, 560, "metal", "Оконный блок сохраняется, закрыт; на внутреннем стекле — светлая плёнка")
    nd.R(-260, 0, -38, 560, "insul", "Минвата 50–100 на всю глубину откоса (λ ≤ 0,04)")
    nd.R(-38, 0, -25, 560, "film", "Пароизоляция Sd ≥ 50 м, бутиловая лента по контуру откосов")
    nd.R(-75, 0, -38, 50, "wood", "Каркас ПП 60/27 / брус 50×50 в откосе — к откосам, не к блоку")
    nd.R(-25, 0, 0, 560, "gkl", "2×ГКЛ 12,5 заподлицо с плоскостью стены")
    nd.R(0, -320, 19, 560, "mdf", "Буазери M06: МДФ 19, эмаль C3; центральная филёнка 1860×1600 — съёмная")
    nd.R(19, 100, 49, 130, "mdf", "Молдинг 30")
    return nd


def n9():
    nd = Node("9", "Ниша экрана 80″ в коробе-ламбрекене CB-3 (разрез поперёк W2)", (-200, 2380, 600, 2860))
    nd.R(-200, 2380, 0, 2750, "brick", "Стена W2 (портал O4: перемычка до +2450, полоса стены C1 до +2550)")
    nd.R(-200, 2750, 600, 2860, "rc", "Плита перекрытия")
    nd.R(0, 2550, 60, 2575, "gkl", "Короб CB-3: 2×ГКЛ 12,5 по каркасу к W2 и плите, низ +2550")
    nd.R(240, 2550, 300, 2575, "gkl")
    nd.R(275, 2575, 300, 2650, "gkl")
    nd.R(60, 2550, 240, 2700, "air", "Ниша 180×150 (+2550..+2700), окраска C6")
    nd.R(70, 2560, 230, 2690, "metal", "Корпус экрана F32 ≈ 180×150 на 2 кронштейнах к плите (анкер в плиту)")
    nd.R(140, 2550, 160, 2560, "air", "Щель полотна 20 по оси x=150, кромки — алюминиевый уголок")
    nd.R(300, 2650, 600, 2662.5, "gkl", "Потолок кухни ГКЛ +2650")
    nd.Pg([(240, 2490), (300, 2490), (300, 2550), (240, 2550)], "pu", "Профиль-карниз 60 по нижней кромке")
    nd.lev(450, 2650)
    nd.lev(-150, 2450, "+2,450")
    return nd


def n10():
    nd = Node("10", "Пол кухня / балкон через портал O4 (J1, D22)", (-1000, -260, 520, 60))
    nd.stack(-1000, -420, m.FL["pies"]["P-BALC"], slab_th=100)
    nd.R(-420, -260, 0, -100, "brick", "Кладка W2 под бывшим балконным блоком")
    nd.R(-420, -100, -210, -5, "cps", "Выравнивание ЦПС/ремсоставом до основания покрытий (без подогрева)")
    nd.R(-420, -5, -210, 0, "lvt")
    nd.R(-210, -100, 0, -17, "cps")
    nd.R(-210, -17, 0, 0, "wood")
    nd.stack(0, 520, m.FL["pies"]["P-OAK"], slab_th=100, with_calls=False)
    nd.call("Кухня: P-OAK — стяжка с ТП −20 → клей 2 → доска 15 → ±0.000", (300, -10))
    nd.R(-213, -17, -207, 0, "brass", "Стык J1 на оси стены x = −210: пробка 5 + латунный Т-профиль 8 на клею")
    nd.lev(250, 0)
    nd.lev(-800, -120, "−0,120 плита")
    return nd


def n11():
    nd = Node("11", "Облицовка W14 в душе VK-C1 с нишами (сечение в плане)", (-160, 0, 120, 1000))
    nd.R(0, 0, 80, 1000, "brick", "Перегородка W14 80")
    nd.R(-60, 0, 0, 1000, "air", "Каркас ПП 60/27 с отступом (к W14 и потолку); в полости Ø50 ванны, ХВС/ГВС, термостат")
    nd.R(-85, 0, -60, 600, "gkl", "Обшивка 2×ГВЛВ/ЦСП 12,5")
    nd.R(-85, 600 + 500, -60, 1000, "gkl")
    nd.R(-86, 0, -85, 1000, "wp", "Гидроизоляция на всю высоту")
    nd.R(-95, 0, -86, 600, "tile", "Плитка 1200×600 горизонтально; итого ≈ 95, душ в свету 805")
    nd.R(-95, 600, -25, 1000, "air")
    nd.R(-95, 350, -25, 600 + 0, "air")
    nd.R(-25, 350, -15, 850, "wp", "Ниша 500, глубина 70, ось y = 5150; внутри ГИ сплошная, кромки — латунный уголок C8")
    nd.C((-35, 150), 25, "air", "Отвод ванны Ø50 у основания (S2)")
    nd.R(-60, 650, -20, 760, "metal", "Корпус термостата, ось y 4750, +1180")
    return nd


ALL17 = [n1a, n1b, n1c, n2, n3, n4, n5, n6]
ALL18 = [n7, n8, n9, n10, n11]


def details_sheet(funcs):
    nodes = [f() for f in funcs]
    for fmt in ("A3", "A2", "A1"):
        sh = Sheet(fmt, SC)
        try:
            _pack(sh, nodes)
            sh.meta = {"scale": "1:10"}
            return sh
        except Overflow:
            continue
    raise Overflow("узлы")


def _pack(sh, nodes):
    W, H = sh.W, sh.H
    x, ytop, shelf = 24.0, H - 7, 0
    placed = []
    for nd in nodes:
        bw, bh = node_size(nd)
        if x + bw > W - 7:
            x, ytop, shelf = 24.0, ytop - shelf - 5, 0
        if ytop - bh < 7 or (x + bw > W - 190 and ytop - bh < STAMP_TOP + 2):
            if x > 24:
                x, ytop, shelf = 24.0, ytop - shelf - 5, 0
            if ytop - bh < 7 or (x + bw > W - 190 and ytop - bh < STAMP_TOP + 2):
                raise Overflow("узлы")
        placed.append((nd, x, ytop))
        x += bw + 6
        shelf = max(shelf, bh)
    for nd, x, ytop in placed:
        draw_node(sh, nd, x, ytop)


def ar17(ctx):
    return details_sheet(ALL17)


def ar18(ctx):
    return details_sheet(ALL18)


SHEETS = {"АР-17": ar17, "АР-18": ar18}
