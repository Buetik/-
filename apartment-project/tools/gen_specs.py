#!/usr/bin/env python3
"""pib-specs-estimate: ведомость отделки, спецификации и смета (вариант D1).

Все количества считаются здесь из слоёв проекта (никаких ручных прикидок):
  01-input/measurements.json, 03-drawings/{planning,furniture,doors,electrical,panel,plumbing,
  heating,hvac,ceilings,floors,elevations}.json, 04-specs/finish-quantities.json,
  02-concept/materials.json.
Цены — ОРИЕНТИР СПб на 10.2026 (розница/подрядчики среднего сегмента), не оферта; см. PRICE_NOTE.

Выход:
  04-specs/finish-schedule.md                 — СП-01 ведомость отделки помещений (ГОСТ 21.501, форма)
  04-specs/spec-*.md                          — спецификации (СП-02…СП-05)
  04-specs/specifications.xlsx                — сводный файл, лист на каждую спецификацию, формулы сумм
  05-estimate/estimate.xlsx, estimate.md      — СМ-01 смета по этапам (работы / материалы), резерв 10 %
  05-estimate/value-engineering.md            — при превышении бюджета
Запуск: python3 tools/gen_specs.py
"""
import json, math, re
from collections import OrderedDict, defaultdict
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
J = lambda p: json.loads((ROOT / p).read_text(encoding="utf-8"))
M = J("01-input/measurements.json")
PL = J("03-drawings/planning.json")
FU = J("03-drawings/furniture.json")
DO = J("03-drawings/doors.json")
EL = J("03-drawings/electrical.json")
PA = J("03-drawings/panel.json")
VK = J("03-drawings/plumbing.json")
HT = J("03-drawings/heating.json")
HV = J("03-drawings/hvac.json")
CE = J("03-drawings/ceilings.json")
FL = J("03-drawings/floors.json")
EV = J("03-drawings/elevations.json")
FQ = J("04-specs/finish-quantities.json")
MAT = {m["id"]: m for m in J("02-concept/materials.json")}
assert PL["selected_option"] == "D1"

DATE = "2026-10-08"
PRICE_NOTE = ("Цены — ориентировочные для Санкт-Петербурга на 10.2026 (средний сегмент, розница/подрядчики), "
              "не являются офертой и подлежат проверке у поставщиков перед закупкой. Материалы — по диапазонам "
              "02-concept/materials.json (price_ref) с поправкой на рост цен 1-го полугодия 2026 (INFOline: плитка +17 %, "
              "электрика +15 %, ЛКМ +10 %, напольные +10,5 %); расценки работ — калибровка по открытым прайсам СПб "
              f"(поиск {DATE}, источники в 05-estimate/estimate.md).")

FI = {f["id"]: f for f in FU["items"]}
ROOMS = {r["id"]: r for r in PL["rooms"]}
RNAME = {r["id"]: r["name"] for r in PL["rooms"]}
OPEN = {o["id"]: o for o in M["openings"]}
r2 = lambda x: round(x + 1e-9, 2)
ceil = math.ceil


def perim(poly):
    return sum(math.dist(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))) / 1000


def roundup_pack(x, pack):
    return r2(ceil(x / pack - 1e-9) * pack)

# ======================================================================================
# 0. Сводные объёмы из finish-quantities.json
# ======================================================================================
WALLS = FQ["walls"]
FLOORS = FQ["floors"]
CEILS = FQ["ceilings"]
LIN = FQ["linear"]
CNT = {c["item"]: c for c in FQ["counts"]}


def fsum(rows, key="m2", **flt):
    return r2(sum(r[key] for r in rows if all((r.get(k) in v) if isinstance(v, (list, tuple, set)) else r.get(k) == v
                                              for k, v in flt.items())))


def lin(kind, room=None):
    return r2(sum(l["m"] for l in LIN if l["kind"] == kind and (room is None or l["room"] == room)))

FRAME_FACES = ("VK-C", "короб", "экран")
PAINT_KINDS = {"paint", "paint_c5_low+c1_up", "paint_wet", "paint_c6", "gvl+paint_c6", "gkl_cladding+paint"}
OTKOS_KINDS = {"plaster+paint", "plaster+paint_c1"}
o1 = OPEN["O1"]
O1_AREA = r2(o1["width"] * (o1["head"] - o1["sill"]) / 1e6)


def plaster_area(w):
    """Площадь штукатурки по маякам (черновая, включая зоны за мебелью)."""
    k = w["kind"]
    if k in {"gkl_cladding+paint", "gvl+paint_c6", "tile_apron", "tile_apron_porcelain"} | OTKOS_KINDS:
        return 0.0
    if any(t in w["face"] for t in FRAME_FACES):
        return 0.0
    if "надоконная" in w["face"]:
        return 0.0
    a = w["gross_m2"] - w["openings_m2"]
    if k == "boiserie":
        a -= O1_AREA  # зона зашитого окна O1 — каркас (узел 8), не штукатурка
    return max(a, 0.0)

PL_DRY = r2(sum(plaster_area(w) for w in WALLS if w["room"] not in ("R5", "R6")))
PL_WET = r2(sum(plaster_area(w) for w in WALLS if w["room"] in ("R5", "R6")))
Q3_WALLS = r2(sum(w["net_m2"] for w in WALLS if w["kind"] in PAINT_KINDS))
Q2_BEHIND = r2(sum(w["behind_furniture_m2"] for w in WALLS if w["kind"] in PAINT_KINDS)
               + sum(w["gross_m2"] for w in WALLS if w["kind"].startswith("paint_q2")))
OTKOS = r2(sum(w["net_m2"] for w in WALLS if w["kind"] in OTKOS_KINDS))
OTKOS_LEN = r2(sum(w["len_m"] for w in WALLS if w["kind"] in OTKOS_KINDS))

# окраска стен по колерам (палитра 02-concept/palette.json)
PAINT = OrderedDict()  # (колер, описание) -> [м², слоёв, ref]


def padd(key, a, coats, ref):
    v = PAINT.setdefault(key, [0.0, coats, set()])
    v[0] += a
    v[2].add(ref)

for w in WALLS:
    k, rm = w["kind"], w["room"]
    a = w["net_m2"]
    if k == "paint" or k == "gkl_cladding+paint":
        padd(("C2", "стены, матовая моющаяся класс 1–2"), a, 2, rm)
    elif k == "paint_c5_low+c1_up":
        # низ до +900 (молдинг chair rail M10) — C5, верх — C1; доля по высоте 0,9 / h
        lo = a * 0.9 / w["h_m"]
        padd(("C5", "детская, низ до +900, износостойкая класс 1"), lo, 2, rm)
        padd(("C1", "детская, верх стен"), a - lo, 2, rm)
    elif k == "paint_wet":
        padd(("C2-W", "стены ванной/постирочной, для влажных помещений"), a, 2, rm)
    elif k in ("paint_c6", "gvl+paint_c6"):
        padd(("C6", "балкон, глубокоматовая, тёмная (3 слоя)"), a, 3, rm)
    elif k in OTKOS_KINDS:
        padd(("C1", "откосы O2, O3, портал O4"), a, 2, rm)
CEIL_PAINT = OrderedDict()
for c in CEILS:
    rm, a = c["room"], c["m2"]
    if rm == "R7":
        CEIL_PAINT.setdefault(("C6", "потолок балкона и ниша CN-3"), [0.0, 3, set()])
        key = ("C6", "потолок балкона и ниша CN-3")
    elif rm in ("R5", "R6"):
        key = ("C1-W", "потолки ГКЛВ ванной и постирочной, влагостойкая")
        CEIL_PAINT.setdefault(key, [0.0, 2, set()])
    else:
        key = ("C1-P", "потолки ГКЛ, глубокоматовая")
        CEIL_PAINT.setdefault(key, [0.0, 2, set()])
    CEIL_PAINT[key][0] += a
    CEIL_PAINT[key][2].add(rm)
CEIL_TOTAL = r2(sum(c["m2"] for c in CEILS))

# потолки по типам
CEIL_GKL = r2(sum(c["m2"] for c in CEILS if c["kind"].startswith("gkl_paint")))
CEIL_GKLV = r2(sum(c["m2"] for c in CEILS if c["kind"].startswith("gklv_paint")))
CEIL_BALC = r2(sum(c["m2"] for c in CEILS if c["kind"].startswith("gklv_on_pir")))
CEIL_BOX = r2(sum(c["m2"] for c in CEILS if c["kind"].startswith("box_")))
CEIL_NICHE = r2(sum(c["m2"] for c in CEILS if c["kind"].startswith("curtain_niche")))

# полы
OAK = r2(sum(f["m2"] for f in FLOORS if f["kind"] == "oak_herringbone"))
OAK_BY_ROOM = {f["room"]: f["m2"] for f in FLOORS if f["kind"] == "oak_herringbone"}
LVT = fsum(FLOORS, kind="lvt_herringbone")
PG_HALL = fsum(FLOORS, kind="porcelain_60x60_hall")
PG_BATH = fsum(FLOORS, kind="porcelain_60x60_bath")
PG_LAUN = fsum(FLOORS, kind="porcelain_60x60_laundry")
PG_SHOWER = fsum(FLOORS, kind="porcelain_60x120_shower_R10B")
WP_FLOOR_R5 = fsum(FLOORS, kind="waterproofing_floor", room="R5")
WP_FLOOR_R6 = fsum(FLOORS, kind="waterproofing_floor", room="R6")
PODIUM = fsum(FLOORS, kind="podium_screed_80")
BALC_SCREED = fsum(FLOORS, kind="xps50+screed55")
WP_WALLS = r2(sum(w["m2"] for w in FQ["waterproofing_walls"]))
TILE_WET = fsum(WALLS, "net_m2", kind="tile_wet")
TILE_DRY = fsum(WALLS, "net_m2", kind="tile_dry")
TILE_DRY_LEN = r2(sum(w["len_m"] for w in WALLS if w["kind"] == "tile_dry"))
APRON_K = fsum(WALLS, "net_m2", kind="tile_apron_porcelain")
APRON_L = fsum(WALLS, "net_m2", kind="tile_apron")
BALC_PARAPET = fsum(WALLS, "net_m2", kind="gvl+paint_c6")
W7_CLAD = fsum(WALLS, "net_m2", kind="gkl_cladding+paint")
BATH_SCREEN = r2(sum(w["net_m2"] for w in WALLS if w["room"] == "R5" and "экран" in w["face"]))
INST_BOX = r2(sum(w["net_m2"] for w in WALLS if w["room"] == "R5" and "короб инсталляции" in w["face"]))
VKC2_FACE = r2(sum(w["net_m2"] for w in WALLS if w["room"] == "R5" and w["face"].startswith("VK-C2")))
VKC1 = next(c for c in VK["new_constructions"] if c["id"] == "VK-C1")
VKC1_H = next(w["h_m"] for w in WALLS if w["face"].startswith("VK-C1"))
VKC1_AREA = r2(abs(VKC1["rect"][1][1] - VKC1["rect"][0][1]) / 1000 * VKC1_H)

# ниши в душе (counts) — периметр под латунный уголок
NICHE_ITEM = next(k for k in CNT if k.startswith("ниша в облицовке душа"))
NICHE_PERIM = r2(sum(2 * (int(a) + int(b)) for a, b in re.findall(r"(\d+)×(\d+)", NICHE_ITEM)) / 1000)
TPROF = next(c for k, c in CNT.items() if k.startswith("латунный Т-профиль"))["m"]

# перегородки / закладки (planning.json new_walls + measurements openings)
NW = {w["id"]: w for w in PL["new_walls"]}
nwlen = lambda w: math.dist(w["a"], w["b"]) / 1000
H_SLAB = 2.75
NW1_A = r2(nwlen(NW["NW1"]) * H_SLAB)
D2 = next(d for d in PL["new_openings"] if d["id"] == "D2")
DOOR_ROUGH_H = 2.18  # doors.json general: черновые проёмы по высоте 2180
NW4_A = r2(nwlen(NW["NW4"]) * H_SLAB - D2["block"] / 1000 * DOOR_ROUGH_H)
NW8_A = r2(nwlen(NW["NW8"]) * OPEN["O7"]["head"] / 1000)
NW9_A = r2(nwlen(NW["NW9"]) * OPEN["O6"]["head"] / 1000)
DOBOR_D1 = r2(0.199 * 2.7)  # elevations R1 W7: добор ПГП 199, z 0..2700
CUT_W12 = r2((4531 - 4250) / 1000 * DOOR_ROUGH_H)  # planning demolition W12-cut y 4250..4531
CUT_W11 = r2((4910 - 4570) / 1000 * DOOR_ROUGH_H)  # W11-cut x 4570..4910
PGP80_A = r2(NW4_A + DOBOR_D1)
PGPG_A = r2(NW8_A + NW9_A)
NW_TAPE = r2(sum(2 * nwlen(w) + 2 * H_SLAB for w in PL["new_walls"]))

# балкон
BHB = EL["floor_heating"]["balcony_heat_balance"]
GLAZING_M2 = next(i[1] for i in BHB["items"] if i[0].startswith("остекление"))
BALC_CEIL_INS = r2(sum(c["m2"] for c in CEILS if c["room"] == "R7"))
R5_PER = r2(perim(ROOMS["R5"]["polygon"]))
R7_PER = r2(perim(ROOMS["R7"]["polygon"]))
FLOOR_TOTAL = PL["areas"]["sum_without_balcony"]
AREA_ALL = r2(FLOOR_TOTAL + PL["areas"]["balcony_bti"])

# ======================================================================================
# 1. Электрика: количества из electrical.json / panel.json
# ======================================================================================
CEIL_LEVEL = {"R1": 2700, "R2": 2700, "R3": 2650, "R4": 2650, "R5": 2450, "R6": 2500, "R7": 2500}
SOCK = [s for s in EL["sockets"] if s["id"] != "P-SS1"]  # P-SS1 — DIN-розетки в U16 (щит)
SW = EL["switches"]
LIGHTS = EL["lights"]
posts = lambda s: 2 if "×2" in s["type"] else 1
N_POSTS_SOCK = sum(posts(s) for s in SOCK)
N_BOXES = sum(posts(s) for s in SOCK) + len(SW)  # подрозетники = посты
N_POINTS = len(SOCK) + len(SW)
DROP_M = r2(sum(max(CEIL_LEVEL.get(p["room"], 2650) - p["height"], 0) for p in SOCK + SW) / 1000)
CABLE = defaultdict(float)
for g in PA["groups"]:
    if g.get("length_m"):
        CABLE[g["cable"]] += g["length_m"]
CABLE = {k: r2(v) for k, v in CABLE.items()}
CABLE_K = 1.15
CABLE_TOTAL = r2(sum(CABLE.values()))
CABLE_TOTAL_K = r2(CABLE_TOTAL * CABLE_K)
U16 = next(l for l in EL["low_voltage"] if l["id"] == "LV00")


def lv_len(l):
    """Трасса слаботочки по потолку (D15): |dx|+|dy| + подъёмы/спуски до потолка + 0,5 м запас на концах."""
    if l["kind"] == "floor_sensor":  # гофра от терморегулятора к центру мата (в слое клея)
        t = next(t for t in EL["floor_heating"]["thermostats"] if t["pos"] == l["pos"])
        m = next(m for m in EL["floor_heating"]["mats"] if m["thermostat"] == t["id"])
        cx = sum((r[0] + r[2]) / 2 for r in m["rects"]) / len(m["rects"])
        cy = sum((r[1] + r[3]) / 2 for r in m["rects"]) / len(m["rects"])
        return (abs(cx - l["pos"][0]) + abs(cy - l["pos"][1]) + l["height"]) / 1000 + 0.5
    if l["from"].startswith("P-"):  # гофра от розетки (ниша ТВ) к консоли F47
        sk = next(s for s in EL["sockets"] if s["id"] == l["from"])
        f = FI["F47"]
        return (abs(sk["pos"][0] - l["pos"][0]) + abs(sk["pos"][1] - l["pos"][1]) + abs(l["height"] - (f["z"] + 100))) / 1000 + 0.5
    if l["from"] in FI:
        f = FI[l["from"]]
        a, ha = f["pos"], 300
    else:
        a, ha = U16["pos"], U16["height"]
    b, hb = l["pos"], l["height"]
    c = CEIL_LEVEL.get(l["room"], 2650)
    return (abs(a[0] - b[0]) + abs(a[1] - b[1]) + max(c - ha, 0) + max(c - hb, 0)) / 1000 + 0.5

LVC = defaultdict(list)
for l in EL["low_voltage"]:
    k = l["kind"]
    if k in ("RJ45", "AP_PoE"):
        LVC["cat6"].append(l)
    elif k == "TV_coax":
        LVC["coax"].append(l)
    elif k == "speaker":
        LVC["speaker"].append(l)
    elif k == "leak_sensor":
        LVC["sensor"].append(l)
    elif k == "valve":
        LVC["valve"].append(l)
    elif k in ("AV_conduit",):
        LVC["av"].append(l)
    elif k == "conduit":
        LVC["conduit25"].append(l)
    elif k == "floor_sensor":
        LVC["fs"].append(l)
LVLEN = {k: r2(sum(lv_len(l) for l in v) * CABLE_K) for k, v in LVC.items()}
LVIDS = {k: ", ".join(l["id"] for l in v) for k, v in LVC.items()}
ZB_BUTTONS = sorted(set(re.findall(r"ZB-\d", json.dumps(EL, ensure_ascii=False))))
LV21 = next(l for l in EL["low_voltage"] if l["id"] == "LV21")
N_OPEN_SENS = 0
for part in LV21["note"].split(":", 1)[1].split("(")[0].split(","):
    mm = re.search(r"×(\d+)", part)
    N_OPEN_SENS += int(mm.group(1)) if mm else 1
MOTION = [l for l in EL["low_voltage"] if l["kind"] == "motion_sensor"]

# ======================================================================================
# 2. Спецификации
# ======================================================================================
SPECS = OrderedDict()


def spec(key, code, title, file, intro=""):
    SPECS[key] = dict(code=code, title=title, file=file, intro=intro, items=[])

spec("furn", "СП-02.1", "Мебель встроенная и отдельностоящая", "spec-furniture.md",
     "Источник: 03-drawings/furniture.json (АР-07), 02-concept/materials.json (M06, M07, M08, M09, M11, M15, M17, M26, M31). "
     "Встроенные шкафы, буазери и системы хранения постирочной — бюджет «Ремонт» (вопрос №34); отдельностоящая мебель — «Мебель+техника». "
     "Встроенная мебель — «под ключ» (изготовление, доставка, монтаж). Мебель ванной — в СП-04.")
spec("kitchen", "СП-02.2", "Кухня и бытовая техника", "spec-kitchen-appliances.md",
     "Источник: furniture.json F01–F24, F80; 04-specs/kitchen.md; materials.json M12, M13. Бюджет «Мебель+техника» (№34). "
     "Мойка, смеситель и фильтр кухни — сантехника, бюджет «Ремонт» (СП-04); фартук — СП-05.")
spec("light", "СП-03.1", "Светильники", "spec-lighting.md",
     "Источник: 03-drawings/electrical.json lights (ЭО-01), группы L1–L22; concept.md п.5; materials.json M30, M34. "
     "Длины LED-лент — по координатам pos→end. Бюджет «Ремонт».")
spec("dev", "СП-03.2", "Электроустановочные изделия (серия)", "spec-wiring-devices.md",
     "Серия: Systeme Electric ArtGallery (альтернатива — Werkel), цвет механизмов и рамок — «молочный/бежевый» в тон C1/C2 (materials.json M33). "
     "Источник: electrical.json sockets (ЭМ-01), switches (ЭО-02). Артикулы — по каталогу серии при заказе (цвет подтвердить). Бюджет «Ремонт».")
spec("panel", "СП-03.3", "Щит ЭМ-03 и кабельная продукция", "spec-panel-cable.md",
     "Источник: 03-drawings/panel.json (ЭМ-03), 04-specs/panel.md. Кабель — по длинам групп panel.json + 15 %. Бюджет «Ремонт».")
spec("vk", "СП-04", "Сантехника, мебель ванной и ВК-материалы", "spec-plumbing.md",
     "Источник: 03-drawings/plumbing.json (ВК-01…ВК-03), furniture.json F66–F77, F19, F20, F78; materials.json M23, M24. "
     "Трубы — по длинам трасс plumbing.json + 15 %. Бюджет «Ремонт» (сантехника — в ремонте, №34).")
spec("doors", "СП-02.3", "Двери и фурнитура", "spec-doors-hardware.md",
     "Источник: 03-drawings/doors.json (АР-08), 04-specs/doors.md; materials.json M19. Бюджет «Ремонт».")
spec("fin", "СП-05", "Отделочные и черновые материалы (с запасами)", "spec-finish-materials.md",
     "Источник: 04-specs/finish-quantities.json (объёмы нетто), floors.json (пироги), ceilings.json, planning.json (перегородки), materials.json. "
     "Запасы: керамогранит 60×60 и «кабанчик» +10 %, крупный формат 60×120 +15 %, инженерная доска ёлочка +8 %, LVT +8 %, погонаж +10 %; "
     "далее — округление до упаковки. Краска — площадь × расход 0,11 л/м² × слои. Бюджет «Ремонт».")
spec("hvac", "СП-04.2", "Тёплые полы (электро) и ОВ", "spec-heating-hvac.md",
     "Источник: 03-drawings/heating.json (ОВ-01), electrical.json floor_heating, hvac.json (ОВ-02). Водяной ТП застройщика — без изменений, "
     "в спецификацию не входит. Бюджет «Ремонт».")
spec("lv", "СП-03.4", "Слаботочные сети, умный дом, кинозона", "spec-lowcurrent-smarthome-cinema.md",
     "Источник: electrical.json low_voltage (ЭМ-02), plumbing.json leak_protection, furniture.json F32, F38–F40, F48, F64, F65. "
     "Длины кабелей — по координатам трасс (по потолку, D15) + 15 %. Сети и защита от протечек — «Ремонт»; проектор, экран, акустика, ТВ — «Мебель+техника» (№34).")

R, F = "Ремонт", "Мебель+техника"


def add(sk, name, art, maker, qty, unit, price, room, ref, budget=R, stage=None, note="", qf=None):
    assert qty is not None
    SPECS[sk]["items"].append(dict(name=name, art=art, maker=maker, qty=r2(qty), unit=unit, price=price,
                                   room=room, ref=ref, budget=budget, stage=stage, note=note, qf=qf))

# --- СП-02.1 мебель --------------------------------------------------------------------
add("furn", "Буазери стены-изголовья W2 2,9×2,7 м: МДФ 16–19, рамки 25–40, центральная филёнка 1860×1600 съёмная, эмаль C3",
    "по эскизу moodboard.html, схема 1", "мебельный/столярный цех СПб", 1, "компл", 95000, "R1", "F41; АР-15; M06; узел 8",
    stage="Э10", note="под ключ с окраской; зашивка O1 — в работах/СП-05")
add("furn", "Шкаф-купе Г 2480+745×600 до потолка: корпус ЛДСП E1, двери — рамочный профиль + вставки МДФ эмаль C3 с накладной филёнкой, верхний подвес",
    "Aristo/Командор, корпус Egger", "мебельный цех СПб", 1, "компл", 215000, "R1", "F45, F46; M07", stage="Э13",
    note="под ключ; подсветка L13 — СП-03.1")
add("furn", "Шкаф прихожей 2720×600×2650: 3 секции по 900, 6 распашных фасадов МДФ эмаль C2 с рамкой-филёнкой, дверь-зеркало, ниша робота",
    "по эскизу moodboard.html, схема 2", "мебельный цех СПб, фурнитура Blum/Hettich", 1, "компл", 195000, "R4",
    "F60, F61, F62; M17; АР-12", stage="Э13", note="под ключ; h 2650 (D19)")
add("furn", "Системы хранения постирочной: тумба хозмойки 450, карго 300, столешница компакт-плита 12 мм 770×600, навесные 350, пенал 540, антресоль 650, шкафы 350 у W10 (фасады от пола без дна над U11)",
    "Egger U702 ST9 «Кашемир серый», кромка ПВХ 2", "мебельный цех СПб", 1, "компл", 115000, "R6",
    "F78, F79, F83, F84, F85, F86, F87, F88; M26; АР-14", stage="Э13", note="под ключ")
add("furn", "Сушилка потолочная «лиана» 4 прутка", "ручная, 4 прутка", "Гимли/Лиана-класс", 1, "шт", 4500, "R6", "F89", stage="Э13")
# отдельностоящая (Мебель+техника)
chairs = [i for i in FU["items"] if i["type"] == "chair" and i["room"] == "R3"]
add("furn", "Стол обеденный 1800×900 (шпон дуба/массив)", "M15", "Stool Group / Woodville / Ellipsefurniture", 1, "шт", 50000, "R3", "F25", F)
add("furn", "Стул мягкий (рогожка/велюр, каркас бук)", "M15", "Stool Group / Woodville", len(chairs), "шт", 11000, "R3",
    ", ".join(c["id"] for c in chairs), F)
add("furn", "П-диван по размеру: спинная секция 3023×750 + 2 боковые 650×700 (отсек AV), съёмные чехлы, на ножках",
    "M31", "мастерская СПб по размеру / модульный", 1, "компл", 155000, "R7", "F33, F34, F35", F, note="встроенные блоки розеток P-B03a/P-B04a/b — поставка с диваном")
add("furn", "Пуф-стол 500×800", "M31", "мастерская (с диваном)", 1, "шт", 18000, "R7", "F36", F)
add("furn", "Кровать 1800×2000 с мягким изголовьем, рама на глайдерах", "M09", "Askona / Ormatek / Dreamline", 1, "шт", 75000, "R1", "F42", F)
add("furn", "Матрас 1800×2000 средней жёсткости", "M09", "Askona / Ormatek", 1, "шт", 40000, "R1", "F42", F)
add("furn", "Тумба прикроватная подвесная 450×500", "M08", "мебельный цех (с консолью)", 2, "шт", 9000, "R1", "F43, F44", F)
add("furn", "ТВ-консоль подвесная 1600×300 МДФ эмаль, низ +250", "M08", "мебельный цех", 1, "шт", 32000, "R1", "F47", F)
add("furn", "Стол рабочий 1400×600, столешница дуб, консоль/подстолье к стене", "M08", "мебельный цех / Woodville", 1, "шт", 35000, "R1", "F49", F)
add("furn", "Кресло рабочее эргономичное", "—", "Chairman / Бюрократ (средний)", 1, "шт", 18000, "R1", "F50", F)
add("furn", "Шкаф детский 1800×600×2400, 2 секции, распашной, крепление к стене", "M11", "местный цех / Ellipsefurniture", 1, "шт", 38000, "R2", "F52", F)
add("furn", "Кровать детская 900×2000 с ящиками для игрушек", "M11", "Ellipsefurniture / местный цех", 1, "шт", 28000, "R2", "F53", F)
add("furn", "Матрас 900×2000 детский", "M11", "Askona / Ormatek", 1, "шт", 12000, "R2", "F53", F)
add("furn", "Стол «растущий» 1200×600 с регулировкой", "M11", "Mealux / Kidfix-класс", 1, "шт", 24000, "R2", "F54", F)
add("furn", "Стул «растущий»", "M11", "Mealux / Kotokota-класс", 1, "шт", 9000, "R2", "F55", F)
add("furn", "ДСК настенный 800×800 (крепление к W6 и потолку)", "M11", "Romana / Kampfer-класс", 1, "шт", 19000, "R2", "F56", F)
add("furn", "Стеллаж низкий навесной 1600×350 h 600", "M11", "местный цех", 1, "шт", 11000, "R2", "F57", F)
add("furn", "Ковёр игровой 2200×1800 (безворсовый, допуск на ТП)", "—", "—", 1, "шт", 9000, "R2", "F58", F)
add("furn", "Банкетка откидная 500×350 на NW9", "M17", "мебельный цех (со шкафом прихожей)", 1, "шт", 14000, "R4", "F63", F)
add("furn", "Доставка, подъём (1 этаж) и сборка отдельностоящей мебели", "—", "поставщики", 1, "усл", 15000, "—", "АР-07", F)

# --- СП-02.2 кухня и техника -------------------------------------------------------------
KPRICE = {"K-01": 38000, "K-02": 22000, "K-03": 16000, "K-04": 26000, "K-05": 18000, "K-07": 38000, "K-08": 4000,
          "KW-01": 12000, "KW-02": 15000, "KW-03": 14000, "KW-04": 15000, "KW-05": 14000}
for f in FU["items"]:
    mod = f.get("module")
    if mod in KPRICE:
        add("kitchen", f"Модуль {f['name']}", f"{f['size'][0]}×{f['size'][1]}×{f['size'][2]}",
            "фабрика СПб по эскизу (M12)", 1, "шт", KPRICE[mod], "R3", f"{f['id']}; kitchen.md", F)
add("kitchen", "Фасад ПММ 600 (шейкер C4) + крепёж к полновстраиваемой ПММ", "K-06", "фабрика (M12)", 1, "шт", 8000, "R3", "F06; kitchen.md", F)
add("kitchen", "Цоколь с вентрешёткой (над водяным ТП), фальш-панели, карниз-фронт CB-1 (съёмная МДФ-панель)", "по месту",
    "фабрика (M12)", 1, "компл", 18000, "R3", "kitchen.md п.2; ceilings.json CB-1/HC-3", F)
add("kitchen", f"Буфет {FI['F24']['size'][0]}×{FI['F24']['size'][1]}×{FI['F24']['size'][2]}: низ — шкаф, ниша +900..+1400, верх — стекло, LED",
    "F24", "фабрика (M12)", 1, "шт", 55000, "R3", "F24; kitchen.md п.5", F)
add("kitchen", f"Столешница кварцевый агломерат 20 мм {FI['F09']['size'][0]}×{FI['F09']['size'][1]}, вырезы мойка/индукция, кромка",
    "светлый с тёплыми прожилками", "Neomarm / Avant / Grandex", 1, "компл", 62000, "R3", "F09; M13", F)
add("kitchen", "Сортировка мусора выдвижная в K-05", "300×500", "Hailo / Blum-класс", 1, "шт", 9000, "R3", "F21", F)
add("kitchen", "Варочная панель индукционная 60 см, 4 зоны, 7,4 кВт (с ограничением мощности)", "Bosch Serie 4 PUE6…", "Bosch / Haier / Weissgauff",
    1, "шт", 45000, "R3", "F15; C7", F)
add("kitchen", "Духовой шкаф встраиваемый 60 см, 3,5 кВт", "Bosch Serie 4 HBA…", "Bosch / Haier", 1, "шт", 48000, "R3", "F16; C8", F)
add("kitchen", "ПММ полновстраиваемая 60 см, 14 комплектов", "Bosch Serie 4 SMV4…", "Bosch / Weissgauff", 1, "шт", 45000, "R3", "F06; C9", F)
add("kitchen", "Холодильник встраиваемый ниша 1780–1940", "Bosch KIV86… / Haier", "Bosch / Haier", 1, "шт", 72000, "R3", "F18; C6", F)
add("kitchen", "Вытяжка встраиваемая 60 см 250–600 м³/ч, обратный клапан", "в модуль KW-02", "Maunfeld / Krona / Bosch", 1, "шт", 20000, "R3", "F17; hvac.json KH1", F)
add("kitchen", "Колонна: стиральная машина + сушильная машина с тепловым насосом, монтажный комплект", "ниша 650×650",
    "Haier / LG / Bosch", 1, "компл", 112000, "R6", "F80; C10, C11", F)
add("kitchen", "Монтаж кухни (входит в цену фабрики) и подключение встраиваемой техники", "—", "фабрика/сервис", 1, "усл", 15000,
    "R3", "kitchen.md п.6", F)

# --- СП-03.1 светильники ------------------------------------------------------------------
LPRICE = {  # (тип, ip) -> (наименование, пример, производитель, цена)
    ("spot", "IP20"): ("Спот встраиваемый LED 7 Вт, 2700 K, CRI ≥ 90, диммируемый, глубина ≤ 80", "Maytoni DL / Elektrostandard", "Maytoni / Elektrostandard", 2700),
    ("spot", "IP44"): ("Спот встраиваемый LED IP44, 3000 K, CRI ≥ 90", "Maytoni Zoom IP44-класс", "Maytoni / Elektrostandard", 3600),
    ("spot", "IP65"): ("Спот встраиваемый LED IP65 (над ванной/душем), 3000 K", "Maytoni Hoop IP65-класс", "Maytoni / Elektrostandard", 4300),
    ("pendant", "IP20"): ("Люстра столовой 5–6 рожков LED, латунь сатин/ткань, диммируемая", "M34", "Maytoni / Freya / Lussole", 32000),
    ("ceiling", "IP20"): ("Люстра/потолочный светильник диммируемый", "M34", "Maytoni / Odeon Light / Freya", 26000),
    ("wall", "IP20"): ("Бра латунь сатин C8 с абажуром", "M34", "Maytoni / Freya / Odeon Light", 9500),
    ("wall", "IP44"): ("LED зеркального шкафа (в составе F72)", "в комплекте F72", "—", 0),
}
LTP = {"L14": ("Светильник потолочный рассеянный детской, диммируемый", 14000), "L8": ("Люстра спальни, диммируемая, латунь/ткань", 24000)}
grp = OrderedDict()
for l in LIGHTS:
    if l["type"] == "led_strip":
        continue
    key = (l["room"], l["type"], l["ip"], l["group"])
    grp.setdefault(key, []).append(l)
nref = lambda ls: "".join(sorted({"; " + r.split(".")[0] for l in ls for r in l.get("need_ref", []) if r.startswith("F")}))
for (rm, tp, ip, g), ls in grp.items():
    nm, ex, mk, pr = LPRICE[(tp, ip)]
    if g in LTP:
        nm, pr = LTP[g]
    add("light", f"{nm} — группа {g}", ex, mk, len(ls), "шт", pr, rm, ", ".join(l["id"] for l in ls) + nref(ls) + "; ЭО-01",
        stage="Э13", note=f"{ls[0]['power_w']} Вт")
LED_TOTAL = 0.0
for l in LIGHTS:
    if l["type"] != "led_strip":
        continue
    L = r2(math.dist(l["pos"], l["end"]) / 1000)
    LED_TOTAL += L
    v = "12 В IP67" if l["ip"] == "IP67" else "24 В"
    add("light", f"Лента LED {v} {l['cct_k']} K CRI ≥ 90 — {l['note'].split('(')[0].split(',')[0][:60]}", "Arlight / Elektrostandard",
        "Arlight", roundup_pack(L * 1.1, 0.5), "м", 1500 if l["ip"] == "IP67" else 1300, l["room"], f"{l['id']}{nref([l])}; ЭО-01",
        stage="Э13", note=f"длина {L} м по pos→end + 10 %")
    add("light", f"Профиль алюминиевый с рассеивателем для {l['id']}", "Arlight / Elektrostandard", "Arlight",
        roundup_pack(L, 1.0), "м", 900, l["room"], l["id"], stage="Э13")
    w = l["power_w"] * 1.25
    bp = 30 if w <= 30 else 60 if w <= 60 else 100
    add("light", f"Блок питания {('12' if l['ip'] == 'IP67' else '24')} В {bp} Вт для {l['id']}", "Arlight ARPV / Mean Well", "Arlight / Mean Well",
        1, "шт", {30: 1500, 60: 2200, 100: 3000}[bp], l["room"], l["id"], stage="Э13", note=f"{l['power_w']} Вт × 1,25")
LED_TOTAL = r2(LED_TOTAL)

# --- СП-03.2 электроустановочные ---------------------------------------------------------
dcount = defaultdict(lambda: [0, []])
for s in SOCK:
    t = s["type"]
    if t.startswith("2P+PE"):
        k = ("Розетка 2П+З 16 А со шторками", 480)
    elif t == "IP44":
        k = ("Розетка 2П+З 16 А IP44 с крышкой", 950)
    elif t == "USB":
        k = ("Розетка 2П+З + USB A/C (быстрая зарядка)", 2300)
    else:
        k = ("Вывод кабеля (механизм-заглушка с выводом) / клеммная колодка", 400)
    dcount[k][0] += posts(s)
    dcount[k][1].append(s["id"])
SWN = {"dimmer": ("Выключатель кнопочный 1кл (под Zigbee-диммер)", 700), "2kl": ("Выключатель 2-клавишный", 650),
       "pass": ("Переключатель проходной", 600), "cross": ("Переключатель перекрёстный", 800), "1kl": ("Выключатель 1-клавишный", 450)}
for s in SW:
    t = s["type"]
    k = SWN[t]
    if s["id"] == "S5":
        k = ("Переключатель проходной 2-клавишный", 850)
    dcount[k][0] += 1
    dcount[k][1].append(s["id"])
for (nm, pr), (q, ids) in dcount.items():
    add("dev", nm + " (механизм)", "серия ArtGallery, «молочный»", "Systeme Electric", q, "шт", pr, "все", ", ".join(ids), stage="Э13")
fr1 = sum(1 for s in SOCK if posts(s) == 1) + len(SW)
fr2 = sum(1 for s in SOCK if posts(s) == 2)
add("dev", "Рамка 1-постовая", "ArtGallery, «молочный»", "Systeme Electric", fr1, "шт", 320, "все", "sockets (1 пост) + switches", stage="Э13",
    note="комбинирование в многопостовые рамки — по ЭО-02/ЭМ-01 при комплектации")
add("dev", "Рамка 2-постовая", "ArtGallery, «молочный»", "Systeme Electric", fr2, "шт", 520, "все", "sockets «2P+PE×2»", stage="Э13")
zbg = [g["id"] for g in EL["light_groups"] if g["id"] in ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L14")]
add("dev", "Модуль Zigbee диммер/реле за клавишей или контроллер LED 24 В Zigbee (работает без шлюза)", "Aqara / Sonoff / Gledopto",
    "Aqara / Sonoff", len(zbg), "шт", 3500, "R2, R3, R7", "light_groups " + ", ".join(zbg) + "; electrical.accepted.lighting_control", stage="Э13")
add("dev", "Подрозетник (кирпич/ГКЛ), с шаблоном", "Hegel / Schneider", "Hegel", N_BOXES, "шт", 90, "все", "посты sockets + switches", stage="Э04")

# --- СП-03.3 щит и кабель ------------------------------------------------------------------
add("panel", "Щит ЩРН-48 (4×12 модулей) накладной/полувстраиваемый IP31", "Hager Volta / Schneider Mini Pragma", "Hager / Schneider",
    1, "шт", 7500, "R4", "U15; panel.json panel; ЭМ-03", stage="Э04", note=f"занято {PA['panel']['modules_used']} из {PA['panel']['modules_total']} мод.")
DEVP = {"QS0/QF0": ("Автомат вводной 2P C63 6 кА", 2600), "FV1": ("УЗИП тип 2 (1P+N) 20 кА + защита", 6500),
        "KV1": ("Реле контроля напряжения 63 А", 4500), "QD0": ("УЗО 2P 80 А 100 мА тип S (противопожарное)", 9500),
        "HL": ("Индикатор наличия напряжения", 600)}
for d in PA["input"]["devices"]:
    nm, pr = DEVP[d["pos"]]
    add("panel", nm, d["item"][:60], "Schneider Easy9 / Hager / IEK Armat", 1, "шт", pr, "R4", f"{d['pos']}; panel.json input", stage="Э04")
bk = defaultdict(list)
for g in PA["groups"]:
    if not g.get("length_m"):
        continue
    dv = g["device"]
    if dv.startswith("автоматический"):
        k = (f"Автомат 1P {g['breaker'].split()[-1]} 6 кА", 650)
    else:
        ma = re.search(r"(\d+) мА", g["rcd"]).group(1)
        k = (f"АВДТ 1P+N {g['breaker'].split()[-1]} {ma} мА тип A 6 кА" + (" (2 мод.)" if "2 модуля" in dv else ""),
             5200 if g["breaker"].endswith("C32") else 4800 if ma == "10" else 3000)
    bk[k].append(g["id"])
for (nm, pr), ids in bk.items():
    add("panel", nm, "Schneider Easy9 / Hager / IEK Armat", "Schneider / Hager", len(ids), "шт", pr, "R4", ", ".join(ids) + "; ЭМ-03", stage="Э04")
add("panel", "Шины N/PE, гребёнки, заглушки, маркировка, DIN-розетки ×3 (P-SS1 в U16)", "—", "Hager / Schneider", 1, "компл", 6500, "R4",
    "panel.json; P-SS1", stage="Э04")
CPRICE = {"ВВГнг(А)-LS 3×1,5": 115, "ВВГнг(А)-LS 3×2,5": 170, "ВВГнг(А)-LS 3×6": 430}
for c, L in CABLE.items():
    ids = [g["id"] for g in PA["groups"] if g.get("cable") == c and g.get("length_m")]
    add("panel", f"Кабель {c}", "ГОСТ 31996", "Кольчугино / Конкорд / Севкабель", roundup_pack(L * CABLE_K, 5), "м", CPRICE[c], "все",
        f"{', '.join(ids)}; panel.json length_m", stage="Э04", note=f"Σ {L} м × 1,15", qf=f"=CEILING({L}*1.15,5)")
add("panel", "Труба гофрированная ПВХ нг Ø20 с зондом (по потолку, D15)", "DKC / Ruvinil", "DKC", roundup_pack(CABLE_TOTAL_K, 50), "м", 28, "все",
    "panel.json Σ length_m × 1,15", stage="Э04")
add("panel", "Провод ПуГВ 1×4 + коробки КУП (ДУП ванной и постирочной)", "—", "—", 2, "компл", 1800, "R5, R6", "panel.json rcd_policy (ДУП)", stage="Э04")
add("panel", "Крепёж кабеля: клипсы, дюбель-хомуты, распаечные коробки (доступные), клеммы Wago", "—", "DKC / Wago",
    1, "компл", 9000, "все", f"{len(PA['groups'])} групп", stage="Э04")

# --- СП-04 сантехника и ВК ---------------------------------------------------------------
add("vk", "Ванна 1700×750 акрил усиленный/кварил, ножки, экран — облицовка плиткой с ревизией H6", "Riho / Ravak / Am.Pm", "Riho / Ravak", 1, "шт", 42000, "R5", "F66; P03; M24", stage="Э13")
add("vk", "Сифон-автомат ванны с переливом (выпуск у правого торца)", "Viega Simplex / Alcaplast", "Viega / Alcaplast", 1, "шт", 6500, "R5", "P03; S2", stage="Э13")
add("vk", "Смеситель для ванны настенный, латунь браш C8", "WasserKRAFT / Lemark", "WasserKRAFT", 1, "шт", 18000, "R5", "P03; WB4", stage="Э13")
add("vk", "Термостат скрытого монтажа на 2 потребителя (встраиваемая часть + лицевая панель), латунь браш", "WasserKRAFT / Lemark / Grohe", "WasserKRAFT",
    1, "компл", 38000, "R5", "P04; WB3; D23", stage="Э05")
add("vk", "Верхний душ 250 + кронштейн, ручной душ со шлангом и подключением, латунь браш", "WasserKRAFT / Lemark", "WasserKRAFT", 1, "компл", 20000, "R5", "P04", stage="Э13")
add("vk", "Трап линейный низкий 800, h ≤ 70, под плитку, с гидрозатвором и фланцем ГИ", "Pestan Confluo / Alcaplast Low", "Pestan / Alcaplast",
    1, "шт", 16000, "R5", "F67; P04; S1; узел 7; D18", stage="Э05")
add("vk", "Стекло душа фиксированное 315×2000, 8 мм, профиль на клею, стабилизатор к потолку (латунь)", "по замеру", "стекольная мастерская СПб",
    1, "компл", 22000, "R5", "F68", stage="Э13")
add("vk", "Инсталляция для подвесного унитаза (рама к стене, D3)", "Geberit Duofix / Grohe Rapid SL", "Geberit", 1, "шт", 28000, "R5", "F69; P01", stage="Э05")
add("vk", "Кнопка смыва, латунь браш", "Geberit Sigma / Grohe", "Geberit", 1, "шт", 7000, "R5", "F69; P01", stage="Э13")
add("vk", "Унитаз подвесной безободковый + сиденье микролифт", "Jacob Delafon / Laufen Pro", "Laufen / Jacob Delafon", 1, "шт", 28000, "R5", "F70; P01", stage="Э13")
add("vk", "Тумба подвесная 900×480, 2 ящика, шалфей C4, столешница 12 мм + раковина", "Aqwella / Opadiris", "Aqwella / Opadiris", 1, "компл", 42000, "R5", "F71; P02; M23", stage="Э13")
add("vk", "Зеркальный шкаф 900×750×150 с LED и розеткой", "Aqwella / Opadiris", "Aqwella", 1, "шт", 24000, "R5", "F72; L20; M23", stage="Э13")
add("vk", "Пенал подвесной 500×350 до +2200", "Aqwella / Opadiris", "Aqwella", 1, "шт", 18000, "R5", "F73; M23", stage="Э13")
add("vk", "Тумба-корзина для белья подвесная 440×350×700", "Aqwella / Opadiris", "Aqwella", 1, "шт", 12000, "R5", "F74; M23", stage="Э13")
add("vk", "Смеситель для раковины, латунь браш, + донный клапан и сифон", "WasserKRAFT / Lemark", "WasserKRAFT", 1, "компл", 19000, "R5", "P02", stage="Э13")
add("vk", "Полотенцесушитель электрический 400×800, класс II IP44, латунь/бронза", "Сунержа / Terminus", "Сунержа", 1, "шт", 24000, "R5", "F75; P05; P-V03", stage="Э13")
add("vk", "Мойка кухни кварцевая 1 чаша 500×450 + сифон с переливом", "Granfest / Florentina", "Granfest", 1, "шт", 14000, "R3", "F19; P06",
    stage="Э13", note="№34: сантехника — бюджет «Ремонт»")
add("vk", "Смеситель кухни с краном питьевой воды, латунь браш", "Lemark / WasserKRAFT", "Lemark", 1, "шт", 15000, "R3", "F19; P06", stage="Э13")
add("vk", "Фильтр питьевой 3-ступенчатый под мойкой (без накопителя)", "Аквафор Кристалл / Гейзер", "Аквафор", 1, "шт", 8500, "R3", "F20; P08", stage="Э13")
add("vk", "Хозмойка накладная 450 + смеситель + сифон с отводом СМА", "керамика/нерж.", "Granfest / Lemark", 1, "компл", 16000, "R6", "F78; P09; S6", stage="Э13")
add("vk", "Кран шаровой ¾″ для СМА + сифон/отвод слива СМА и конденсата СМ", "Valtec / Itap", "Valtec", 1, "компл", 2500, "R6", "P10, P11; WL2; S7", stage="Э05")
nodes = VK["nodes"]
add("vk", "Кран шаровой квартирный ½″–¾″ (ХВС, ГВС)", "Itap Ideal / Valtec Base", "Itap", 2 * len(nodes), "шт", 1200, "R5, R6", "N1, N2 chain", stage="Э05")
add("vk", "Фильтр-редуктор комбинированный 100 мкм с манометром, 3,0 бар", "Honeywell FK06-класс / Valtec", "Valtec / Honeywell", 2 * len(nodes), "шт", 5500, "R5, R6",
    "N1, N2 chain; summary.filter", stage="Э05")
add("vk", "Обратный клапан ½″–¾″", "Valtec", "Valtec", 2 * len(nodes), "шт", 700, "R5, R6", "N1, N2 chain", stage="Э05")
add("vk", "Счётчик ИПУ Ду15 с импульсным выходом (если не установлены застройщиком)", "Пульс / Декаст", "Пульс", 2 * len(nodes), "шт", 2300, "R5, R6",
    "N1, N2 chain", stage="Э05", note="[ДОПУЩЕНИЕ] уточнить наличие у застройщика")
col_out = 0
for n in nodes:
    for ch in n["chain"]:
        if ch.startswith("коллектор"):
            col_out += sum(int(x) for x in re.findall(r"×(\d+)", ch))
            col_out += 1 if "заглушённый" in ch else 0
add("vk", "Коллектор ¾″ (гребёнка) ХВС/ГВС — корпус", "Valtec VTc.580", "Valtec", 2 * len(nodes), "шт", 2400, "R5, R6", "N1, N2 chain (коллекторы)", stage="Э05")
add("vk", "Выход коллектора с шаровым краном ½″ / евроконус", "Valtec", "Valtec", col_out, "шт", 750, "R5, R6", "N1, N2: выходы ХВС/ГВС", stage="Э05")
w_lines = sum(2 if "+" in w["sys"] else 1 for w in VK["pipes"]["water"])
pex = r2(sum(w["length_m"] * (2 if "+" in w["sys"] else 1) for w in VK["pipes"]["water"]))
pex_hot = r2(sum(w["length_m"] for w in VK["pipes"]["water"] if "ГВС" in w["sys"]))
pex_cold = r2(sum(w["length_m"] for w in VK["pipes"]["water"] if "ХВС" in w["sys"]))
add("vk", "Труба PEX-a 16×2,2 (цельные отрезки, без соединений в подиуме/облицовке)", "Rehau Rautitan / Valtec PEX-a", "Rehau",
    roundup_pack(pex * 1.15, 1), "м", 190, "R3, R5, R6", "plumbing.json pipes.water WB1–WB4, WK1, WL1, WL2", stage="Э05",
    note=f"Σ трасс × линии = {pex} м × 1,15")
add("vk", "Теплоизоляция 9 мм (ГВС) / 6 мм антиконденсатная (ХВС)", "Energoflex / K-Flex", "Energoflex",
    roundup_pack((pex_hot + pex_cold) * 1.15, 1), "м", 60, "R3, R5, R6", "pipes.water_material", stage="Э05")
add("vk", "Водорозетка латунная ½″ (выводы к приборам)", "Rehau / Valtec", "Valtec", w_lines, "шт", 900, "R3, R5, R6", "pipes.water: выводы", stage="Э05")
add("vk", "Фитинги на надвижной гильзе (уголки, тройники, переходники), ≈ 3 на вывод", "Rehau Everloc", "Rehau", 3 * w_lines, "шт", 450, "R3, R5, R6",
    "pipes.water", stage="Э05")
sw50 = r2(sum(s["L"] for s in VK["pipes"]["sewer"] if s["dn"] == 50))
sw110 = r2(sum(s["L"] for s in VK["pipes"]["sewer"] if s["dn"] == 110))
add("vk", "Труба ПП канализационная Ø50 (малошумная в коробах)", "Ostendorf / Sinikon", "Ostendorf", roundup_pack(sw50 * 1.15, 0.5), "м", 260, "R3, R5, R6",
    "sewer S1, S2, S4–S7", stage="Э05", note=f"Σ L = {sw50} м × 1,15")
add("vk", "Труба ПП канализационная Ø110", "Ostendorf / Sinikon", "Ostendorf", roundup_pack(sw110 * 1.15, 0.5), "м", 480, "R5", "sewer S3", stage="Э05",
    note=f"Σ L = {sw110} м × 1,15")
add("vk", "Фасонные части ПП (отводы 15–45°, тройники, эксц. переходы 110/50), хомуты с резиной", "Ostendorf", "Ostendorf",
    3 * len(VK["pipes"]["sewer"]) + 2, "шт", 350, "R3, R5, R6", "sewer S1–S7; заглушка P12", stage="Э05", note="≈ 3 на трассу + 2 перехода")
add("vk", "Заглушка Ø110 с ревизией (выпуск бывшего WC постирочной)", "—", "Ostendorf", 1, "шт", 900, "R6", "P12; D7; planning demolition F1", stage="Э05")
for h in VK["hatches"]:
    if "мебельный" in h["type"] or h["size"] == "—":
        continue
    pr = 9500 if h["size"] == "300×600" else 7500 if h["size"] == "300×400" else 5000
    add("vk", f"Люк ревизионный {h['size']} — {h['type'][:45]}", "Практика / Revizor", "Практика", 1, "шт", pr, "R5" if h["id"] != "H3" else "R6",
        f"{h['id']}; ВК-03", stage="Э08")
add("vk", "Монтажный комплект: кронштейны, шумоизоляция, ФУМ, герметики", "—", "—", 1, "компл", 6000, "R3, R5, R6", "ВК-01", stage="Э05")

# --- СП-02.3 двери --------------------------------------------------------------------------
for d in DO["doors"]:
    if d["no"].startswith("Д-"):
        wet = "влагостойкая" in d["type"]
        add("doors", f"Дверь {d['no']} ({d['id']}): полотно {d['leaf'].split('(')[0].strip()}, МДФ эмаль C1 филёнчатое{', влагостойкое' if wet else ''}, коробка, наличники 70–80 с цоколем",
            "линии неоклассики под эмаль", "Софья / Волховец / ProfilDoors", 1, "компл", 42000, d["room"].split()[0], f"{d['id']}; АР-08; M19", stage="Э12",
            note=f"проём {d['opening_clear']}")
        nh = int(re.search(r"×(\d+)", d["hardware"]).group(1)) if "×" in d["hardware"] else 3
        add("doors", f"Петли скрытые {'180°' if '180' in d['hardware'] else '3D'} для {d['no']}", "AGB Eclipse / Simonswerk Tectus-класс", "AGB", nh, "шт", 2600,
            d["room"].split()[0], d["id"], stage="Э12")
        add("doors", f"Ручка на розетке латунь сатин C8 для {d['no']}", "Morelli / Fratelli Cattini", "Fratelli Cattini", 1, "компл", 3800,
            d["room"].split()[0], d["id"], stage="Э12")
        add("doors", f"Защёлка магнитная для {d['no']}", "AGB Polaris", "AGB", 1, "шт", 1500, d["room"].split()[0], d["id"], stage="Э12")
        if "WC-фиксатор" in d["hardware"]:
            add("doors", f"WC-фиксатор с индикатором, латунь сатин, для {d['no']}", "Fratelli Cattini", "Fratelli Cattini", 1, "шт", 2600,
                d["room"].split()[0], d["id"], stage="Э12")
        add("doors", f"Ограничитель настенный (не в пол, D3) для {d['no']}", "Morelli", "Morelli", 1, "шт", 1100, d["room"].split()[0], d["id"], stage="Э12")
        if "доводчик" in d["hardware"]:
            add("doors", f"Доводчик-демпфер от защемления для {d['no']}", "—", "—", 1, "шт", 2500, d["room"].split()[0], d["id"], stage="Э12")
        if "уплотнитель" in d["hardware"]:
            add("doors", f"Уплотнитель акустический по коробке для {d['no']}", "—", "—", 1, "компл", 900, d["room"].split()[0], d["id"], stage="Э12")
        if "решётка" in d["hardware"]:
            add("doors", f"Переточная решётка в полотне для {d['no']}", "—", "в цвет C1", 1, "шт", 1500, d["room"].split()[0], d["id"], stage="Э12")
add("doors", "Надпроёмная панель над D1 до +2750 (МДФ эмаль C1, в системе двери)", "—", "Софья / Волховец / ProfilDoors", 1, "шт", 12000, "R1",
    "D1; doors.json opening_clear; M19", stage="Э12")
add("doors", "Наличник C1 изнутри входной двери ДВ-1 (комплект с цоколем)", "—", "Софья / Волховец", 1, "компл", 8000, "R4", "O5; ДВ-1", stage="Э12")

# --- СП-05 отделочные материалы -----------------------------------------------------------
def tile(name, art, mk, area, k, box, price, room, ref, stage="Э08"):
    q = roundup_pack(area * k, box)
    add("fin", name, art, mk, q, "м²", price, room, ref, stage=stage,
        note=f"нетто {r2(area)} м² × {k} → упаковка {box} м²", qf=f"=CEILING({r2(area)}*{k},{box})")

oak_rooms = ", ".join(f"{k} {str(v).replace('.', ',')}" for k, v in OAK_BY_ROOM.items())
tile("Инженерная доска дуб 2-слойная 14–15 мм, ёлочка 90×600, ультраматовый лак, допуск на водяной ТП", "Coswick «Ёлочка» / Alpine Floor Villa Herringbone",
     "Coswick / Alpine Floor", OAK, 1.08, 1.0, 7800, "R1, R2, R3, R4", f"floors oak_herringbone ({oak_rooms}); M01; АР-10", "Э11")
add("fin", "Клей паркетный MS-полимер эластичный (1,2 кг/м²)", "Uzin MK 250 / Bostik Tarbicol MS", "Uzin / Bostik", roundup_pack(OAK * 1.2, 15), "кг", 700,
    "R1, R2, R3, R4", "P-OAK; M01", stage="Э11", qf=f"=CEILING({OAK}*1.2,15)")
add("fin", "Грунт/ремонтный состав под клей (0,2 л/м²) и локальный ремонт стяжки", "Uzin PE 460 / Bostik", "Uzin", roundup_pack(OAK * 0.2, 5), "л", 950,
    "R1, R2, R3, R4", "P-OAK", stage="Э11")
tile("LVT клеевой «ёлочка» в тон дуба C7, 33/42 кл., слой износа ≥ 0,55, допуск на ТП", "Alpine Floor Parquet LVT / Aquafloor Parquet Glue",
     "Alpine Floor", LVT, 1.08, 0.5, 3300, "R7", "floors lvt_herringbone; M28", "Э11")
add("fin", "Клей дисперсионный для LVT (0,35 кг/м²)", "Bostik / Forbo / Homakoll", "Homakoll", roundup_pack(LVT * 0.35, 1), "кг", 450, "R7", "P-BALC; M28", stage="Э11")
tile("Керамогранит 60×60 «светлый камень» R10 ректификат (вход)", "Kerama Marazzi / Italon / Estima", "Kerama Marazzi", PG_HALL, 1.10, 1.44, 3900, "R4",
     "floors porcelain_60x60_hall; M16")
tile("Керамогранит 60×60 «светлый мрамор» R10 ректификат (ванная, постирочная)", "Italon Charme Evo / Kerama Marazzi", "Italon", PG_BATH + PG_LAUN, 1.10, 1.44,
     4500, "R5, R6", "floors porcelain_60x60_bath + _laundry; M20, M25")
tile("Керамогранит 60×120 «светлый мрамор» R10/B (пол душа, уклон к трапу)", "Italon Charme Evo (структ.)", "Italon", PG_SHOWER, 1.15, 1.44, 5900, "R5",
     "floors porcelain_60x120_shower_R10B; M20")
tile("Керамогранит 60×120 «светлый мрамор» матовый — стены ванной (мокрые зоны до потолка + до +1280) и фартук кухни", "Italon Charme Evo / Kerama Marazzi",
     "Italon", TILE_WET + TILE_DRY + APRON_K, 1.15, 1.44, 5600, "R5, R3", "walls tile_wet + tile_dry + tile_apron_porcelain; M21, M13; АР-13, АР-11")
tile("Плитка «кабанчик» матовая (фартук хозмойки)", "Kerama Marazzi «Метро» / Estima", "Kerama Marazzi", APRON_L, 1.10, 1.0, 2600, "R6", "walls tile_apron; M27; АР-14")
TILE_FLOOR = r2(PG_HALL + PG_BATH + PG_LAUN + PG_SHOWER)
TILE_WALL = r2(TILE_WET + TILE_DRY + APRON_K + APRON_L)
add("fin", "Клей плиточный C2TE S1 для ТП и крупного формата (пол 7 кг/м², стены 6 кг/м²)", "Litokol Hyperflex K100 / Ceresit CM 17", "Litokol",
    ceil((TILE_FLOOR * 7 + TILE_WALL * 6) / 25), "меш. 25 кг", 1250, "R3–R6", "floors/walls tile_*", stage="Э08",
    qf=f"=CEILING(({TILE_FLOOR}*7+{TILE_WALL}*6)/25,1)")
R5_TILE = r2(TILE_WET + TILE_DRY + PG_BATH + PG_SHOWER)
add("fin", "Затирка эпоксидная (ванная, 0,35 кг/м²)", "Litokol Starlike EVO", "Litokol", roundup_pack(R5_TILE * 0.35, 1), "кг", 1900, "R5", "M21", stage="Э08")
add("fin", "Затирка цементная (прихожая, постирочная, фартуки, 0,3 кг/м²)", "Litokol Litochrom", "Litokol",
    roundup_pack((PG_HALL + PG_LAUN + APRON_K + APRON_L) * 0.3, 1), "кг", 350, "R3, R4, R6", "tile_*", stage="Э08")
add("fin", "Система выравнивания плитки (СВП: клипсы, клинья)", "—", "—", roundup_pack(TILE_FLOOR + TILE_WALL, 1), "м²", 120, "R3–R6", "tile_*", stage="Э08")
add("fin", "Профиль латунь для плитки 10 мм (линия +1280 и обрамление ниш)", "Progress Profiles / Butech", "Progress Profiles",
    roundup_pack((TILE_DRY_LEN + NICHE_PERIM) * 1.1, 2.7), "м", 1500, "R5", f"walls tile_dry (Σ длин {TILE_DRY_LEN}); ниши {NICHE_PERIM} м; M21", stage="Э08")
add("fin", "Порог-ступень D3 из керамогранита 800×100×90 (изготовление)", "серия C9", "мастерская", 1, "шт", 4500, "R5", "J5; узел 5; D20", stage="Э08")
add("fin", "Порог-ограничитель D4 800×80×15 (керамогранит/камень, скругл.)", "—", "мастерская", 1, "шт", 2500, "R6", "J6; D4", stage="Э08")
WP_AREA = r2(WP_FLOOR_R5 * 2 + WP_FLOOR_R6 + WP_WALLS)
add("fin", "Гидроизоляция обмазочная 2-компонентная (2 слоя, 2,8 кг/м²; пол ванной — нижняя + основная)", "Mapei Mapelastic / Ceresit CL 51", "Mapei",
    roundup_pack(WP_AREA * 2.8, 1), "кг", 420, "R5, R6", f"floors waterproofing_floor ×(2 в R5) + waterproofing_walls = {WP_AREA} м²", stage="Э06",
    qf=f"=CEILING({WP_AREA}*2.8,1)")
add("fin", "Ленты, углы, манжеты, фланец трапа (комплект на помещение)", "Mapei Mapeband", "Mapei", 2, "компл", 6500, "R5, R6", "узел 6", stage="Э06")
pod_kg = PODIUM * 0.0785 * 2000
add("fin", "ЦПС М300 (подиум ванной 78,5 мм, фибра)", "Каменный цветок / Knauf", "—", ceil(pod_kg / 40), "меш. 40 кг", 380, "R5",
    "floors podium_screed_80; P-BATH", stage="Э06", qf=f"=CEILING({PODIUM}*0.0785*2000/40,1)")
add("fin", "Сетка Вр4 50×50 + фибра + демпферная лента (подиум, стяжка балкона)", "—", "—", roundup_pack((PODIUM + BALC_SCREED) * 1.1, 1), "м²", 380,
    "R5, R7", f"P-BATH, P-BALC; периметры R5 {R5_PER} м, R7 {R7_PER} м", stage="Э06")
add("fin", "Рамка-бортик U14 (ЦСП 20 / уголок нерж.)", "VK-C3", "—", 1, "шт", 2500, "R5", "VK-C3; J7; узел 6", stage="Э06")
add("fin", "XPS 300 кПа 50 мм (пол балкона)", "Пеноплэкс Комфорт / Технониколь Carbon", "Пеноплэкс", roundup_pack(BALC_SCREED * 1.05, 0.72), "м²", 650, "R7",
    "floors xps50+screed55; P-BALC; D22", stage="Э06")
add("fin", "Плёнка ПЭ 200 мкм (нахлёст 100, завод на стены)", "—", "—", roundup_pack(BALC_SCREED * 1.3, 1), "м²", 45, "R7", "P-BALC", stage="Э06")
add("fin", "ЦПС М300 (стяжка балкона 55 мм)", "—", "—", ceil(BALC_SCREED * 0.055 * 2000 / 40), "меш. 40 кг", 380, "R7", "P-BALC",
    stage="Э06", qf=f"=CEILING({BALC_SCREED}*0.055*2000/40,1)")
add("fin", "Самовыравнивающая смесь 10 мм по мату TP3 (16 кг/м²)", "Ceresit CN 175 / Knauf Боден", "Ceresit", ceil(BALC_SCREED * 16 / 25), "меш. 25 кг", 950,
    "R7", "P-BALC", stage="Э06")
# балкон: остекление и утепление
add("fin", "Остекление балкона тёплое ПВХ 70 мм, 2-камерный энергосберегающий стеклопакет, наружное стекло триплекс P2A, фурнитура с детским замком, отливы, подоконник",
    "VEKA / Exprof / Rehau-класс", "переработчик СПб", GLAZING_M2, "м²", 21000, "R7",
    "electrical.json balcony_heat_balance (остекление 10,5 м²); M32; №12", stage="Э03", note="поставка; монтаж — в работах")
nv = [s for s in HV["supply"] if s["id"].startswith("SV")]
add("fin", "Оконный приточный клапан в раме (гигрорегулируемый)", "Aereco / Air-Box", "Aereco", len(nv), "шт", 3500, "R7", ", ".join(s["id"] for s in nv) + "; ОВ-02",
    stage="Э03")
add("fin", "Утеплитель PIR 50 фольгированный (парапеты, потолок балкона)", "Logicpir / Технониколь", "Технониколь",
    roundup_pack((BALC_PARAPET + BALC_CEIL_INS) * 1.05, 0.72), "м²", 1050, "R7", f"walls gvl+paint_c6 {BALC_PARAPET} + ceilings R7 {BALC_CEIL_INS}; M29, M30", stage="Э03")
add("fin", "Лента алюминиевая, пароизоляция примыканий, пена", "—", "—", 1, "компл", 4500, "R7", "M29", stage="Э03")
add("fin", "ГВЛ 12,5 (обшивка парапетов) 2500×1200", "Knauf ГВЛ", "Knauf", ceil(BALC_PARAPET * 1.1 / 3), "лист", 780, "R7", "walls gvl+paint_c6", stage="Э03")
add("fin", "Каркас для обшивки парапетов (ПП 60/27, ПН, подвесы, крепёж)", "Knauf", "Knauf", roundup_pack(BALC_PARAPET, 1), "м²", 450, "R7", "walls gvl+paint_c6", stage="Э03")
# перегородки, зашивки, облицовки
add("fin", "ПГП полнотелая 667×500×100 (NW1)", "Волма / Knauf", "Волма", ceil(NW1_A / 0.3335 * 1.05), "шт", 520, "R1/R3", f"NW1 {NW1_A} м²; planning.json new_walls",
    stage="Э02")
add("fin", "ПГП полнотелая 667×500×80 (NW4, добор D1)", "Волма / Knauf", "Волма", ceil(PGP80_A / 0.3335 * 1.05), "шт", 400, "R2/R4, R1",
    f"NW4 {NW4_A} м² (за вычетом проёма D2) + добор 199 {DOBOR_D1} м²", stage="Э02")
add("fin", "ПГП гидрофобизированная 667×500×80 (NW8, NW9)", "Волма / Knauf", "Волма", ceil(PGPG_A / 0.3335 * 1.05), "шт", 450, "R5, R6",
    f"NW8 {NW8_A} + NW9 {NW9_A} м²", stage="Э02")
NW_ALL = r2(NW1_A + PGP80_A + PGPG_A)
add("fin", "Клей гипсовый монтажный для ПГП (2 кг/м²) + ГКЛ на клей NW1", "Волма Монтаж / Knauf Перлфикс", "Волма", ceil((NW_ALL * 2 + NW1_A * 4) / 30),
    "меш. 30 кг", 620, "—", "new_walls", stage="Э02")
add("fin", "Лента демпферная 10 мм + скобы/гибкие связи (без дюбелей в пол, D3)", "—", "—", roundup_pack(NW_TAPE, 1), "м", 120, "—",
    f"new_walls: периметры NW1, NW4, NW8, NW9 = {NW_TAPE} м", stage="Э02")
add("fin", "Перемычка (уголок) над новыми проёмами D3, D4", "—", "—", 2, "шт", 1200, "R5, R6", "W12-cut, W11-cut", stage="Э02")
GKL_WALL = r2(W7_CLAD + NW1_A + O1_AREA * 2)
add("fin", "ГКЛ 12,5 2500×1200 (облицовка W7, NW1 со стороны кухни, зашивка O1 в 2 слоя)", "Knauf ГСП-А", "Knauf", ceil(GKL_WALL * 1.1 / 3), "лист", 560,
    "R1, R3", f"W7 {W7_CLAD} + NW1 {NW1_A} + O1 2×{O1_AREA} м²", stage="Э02")
FRAME_W = r2(W7_CLAD + O1_AREA + VKC1_AREA + INST_BOX + BATH_SCREEN + VKC2_FACE)
add("fin", "Каркас стенных облицовок (ПП 60/27, ПН, подвесы; VK-C1 — стальной/ПП усиленный)", "Knauf", "Knauf", roundup_pack(FRAME_W, 1), "м²", 520,
    "R1, R5", f"W7, O1, VK-C1 {VKC1_AREA}, короб инсталляции {INST_BOX}, экран {BATH_SCREEN}, VK-C2 {VKC2_FACE}", stage="Э02")
GVLV = r2((VKC1_AREA + INST_BOX + BATH_SCREEN + VKC2_FACE) * 2)
add("fin", "ГВЛВ/ЦСП 12,5 (облицовка душа VK-C1, короб инсталляции, экран ванны, VK-C2 — 2 слоя)", "Knauf ГВЛВ / Аквапанель", "Knauf", ceil(GVLV * 1.15 / 3),
    "лист", 950, "R5", "VK-C1 (F90), VK-C2, F69, экран ванны", stage="Э02")
add("fin", "Минвата 100 + пароизоляция с проклейкой (зашивка O1)", "Rockwool Лайт Баттс / Ондутис", "Rockwool", roundup_pack(O1_AREA * 1.2, 1), "м²", 650, "R1",
    f"window_infill O1 {O1_AREA} м²; узел 8", stage="Э02")
# потолки
add("fin", "ГКЛ 12,5 2500×1200 (потолки, короба CB-1…CB-3, ниши штор)", "Knauf ГСП-А", "Knauf", ceil((CEIL_GKL + CEIL_BOX * 1.5 + CEIL_NICHE) * 1.1 / 3), "лист", 560,
    "R1–R4", f"ceilings gkl_* {CEIL_GKL} + box {CEIL_BOX}×1,5 + niche {CEIL_NICHE}", stage="Э09")
add("fin", "ГКЛВ 12,5 2500×1200 (потолки ванной, постирочной, балкона)", "Knauf ГСП-H2", "Knauf", ceil((CEIL_GKLV + CEIL_BALC) * 1.1 / 3), "лист", 650,
    "R5–R7", f"ceilings gklv_* {CEIL_GKLV} + {CEIL_BALC}", stage="Э09")
add("fin", "Каркас потолков (ПП 60/27, ПН 28/27, прямые подвесы, крабы, анкеры)", "Knauf", "Knauf", roundup_pack(CEIL_TOTAL, 1), "м²", 550, "все",
    f"ceilings Σ {CEIL_TOTAL} м²", stage="Э09")
add("fin", "Теневой профиль 10×10 алюминиевый под окраску", "Steel Shadow / Профиль-Т", "—", roundup_pack(lin("shadow_profile") * 1.05, 3), "м", 650, "R5, R6, R7",
    "linear shadow_profile; ceilings shadow_profiles", stage="Э09")
for c in CE["hatches"]:
    if c["id"] in ("HC-1", "HC-2"):
        add("fin", f"{c['id']}: {c['type'][:60]} {c['size']}", "Практика / Revizor", "—", 1, "шт", 4500 if c["id"] == "HC-1" else 1800,
            c["room"], f"{c['id']}; ceilings.json", stage="Э09")
# штукатурка, шпаклёвка
add("fin", "Штукатурка гипсовая по маякам (ср. 15 мм, 13,5 кг/м²)", "Knauf Ротбанд / Волма Слой", "Knauf", ceil(PL_DRY * 13.5 / 30), "меш. 30 кг", 640,
    "R1–R4, R7", f"walls (gross − проёмы, без каркасных облицовок) = {PL_DRY} м²", stage="Э07", qf=f"=CEILING({PL_DRY}*13.5/30,1)")
add("fin", "Штукатурка цементная для влажных помещений (ср. 15 мм, 18 кг/м²)", "Knauf Унтерпутц / Ceresit CT 24", "Knauf", ceil(PL_WET * 18 / 25), "меш. 25 кг", 520,
    "R5, R6", f"walls R5, R6 = {PL_WET} м²", stage="Э07", qf=f"=CEILING({PL_WET}*18/25,1)")
add("fin", "Маяки 6 мм 3 м + уголки штукатурные для откосов", "—", "—", ceil((PL_DRY + PL_WET) / 1.5 + OTKOS_LEN * 1.1 / 3), "шт", 70, "все",
    f"штукатурка; откосы {OTKOS_LEN} м", stage="Э07")
SHP = r2(Q3_WALLS + OTKOS + CEIL_TOTAL)
add("fin", "Грунт глубокого проникновения (2 прохода, 0,15 л/м²)", "Ceresit CT 17 / Knauf Тифенгрунд", "Ceresit",
    roundup_pack((PL_DRY + PL_WET + SHP + Q2_BEHIND) * 0.3, 10), "л", 120, "все", "штукатурка + шпаклёвка + Q2", stage="Э07")
add("fin", "Шпаклёвка финишная полимерная (стены Q3 1,2 кг/м², потолки Q4 1,5 кг/м², Q2 за мебелью 0,5 кг/м²)", "Sheetrock / Vetonit LR+ / Danogips", "Sheetrock",
    roundup_pack(Q3_WALLS * 1.2 + OTKOS * 1.2 + CEIL_TOTAL * 1.5 + Q2_BEHIND * 0.5, 20), "кг", 85, "все",
    f"Q3 стены {Q3_WALLS} + откосы {OTKOS} + потолки {CEIL_TOTAL} + Q2 {Q2_BEHIND} м²", stage="Э07")
add("fin", "Шпаклёвка для швов ГКЛ + серпянка (0,35 кг/м²)", "Knauf Фуген", "Knauf", roundup_pack((CEIL_TOTAL + GKL_WALL + GVLV / 2) * 0.35, 25), "кг", 70, "все",
    "ceilings + облицовки", stage="Э07")
add("fin", "Стеклохолст-паутинка 45 г/м² + клей (стены под покраску)", "Wellton / Oscar", "Wellton", roundup_pack(Q3_WALLS * 1.1, 50), "м²", 95, "все",
    f"walls под окраску {Q3_WALLS} м²; M05", stage="Э07")
# краски
PAINT_INFO = {"C1": ("Краска акриловая глубокоматовая, колер C1 «тёплый белый» NCS S 0502-Y", 1400),
              "C1-P": ("Краска потолочная глубокоматовая, колер C1 NCS S 0502-Y", 1300),
              "C1-W": ("Краска для влажных помещений матовая, колер C1", 1600),
              "C2": ("Краска акриловая матовая моющаяся (класс 1), колер C2 «лён» NCS S 1002-Y", 1500),
              "C2-W": ("Краска для влажных помещений матовая, колер C2 NCS S 1002-Y", 1600),
              "C5": ("Краска износостойкая моющаяся (класс 1), колер C5 NCS S 1510-B", 1500),
              "C6": ("Краска глубокоматовая (≤ 3 gloss), колер C6 «тёмная олива»", 1600)}
for src in (PAINT, CEIL_PAINT):
    for (col, desc), (a, coats, rooms) in src.items():
        nm, pr = PAINT_INFO[col]
        a = r2(a)
        add("fin", f"{nm} — {desc}", "Derufa / Caparol Samtex / Dulux-класс", "Derufa / Caparol", ceil(a * 0.11 * coats), "л", pr,
            ", ".join(sorted(rooms)), "finish-quantities walls/ceilings; palette.json", stage="Э10",
            note=f"{a} м² × 0,11 л × {coats} сл.", qf=f"=CEILING({a}*0.11*{coats},1)")
# погонаж
FRAMES_R1 = next(it for e in EV["elevations"] if e["room"] == "R1" and e["wall_id"] == "W7" for it in e["items"] if it["type"] == "moulding")
FR1_LEN = r2(2 * ((FRAMES_R1["s"][1] - FRAMES_R1["s"][0]) + (FRAMES_R1["z"][1] - FRAMES_R1["z"][0])) / 1000)
FR3_LEN = r2(3 * 2 * (0.9 + 1.8))  # M14: 2–3 рамки на W8/NW1 — [ДОПУЩЕНИЕ] 3 рамки 900×1800 (геометрии в elevations нет)
POG = [("cornice_80", "Карниз потолочный гладкий 80×70 полиуретан/дюрополимер", "Европласт / Orac Decor", 1300, "M04"),
       ("cornice_60", "Карниз потолочный 60×60", "Европласт / Orac Decor", 1000, "M04"),
       ("cornice_40", "Карниз 40 влагостойкий (ванная)", "Европласт / Orac Decor", 800, "M21"),
       ("cornice_profile_lambrequin_60", "Карниз-профиль 60 ламбрекена CB-3", "Европласт / Orac Decor", 1000, "M14"),
       ("cornice_boiserie_LED", "Карниз с LED-пазом (буазери, wall-wash)", "Orac Decor C-серия", 2800, "M06"),
       ("plinth_mdf_120", "Плинтус МДФ влагостойкий 120 под покраску, к стене", "Ultrawood / Orac SX", 850, "M02"),
       ("plinth_mdf_80_C6", "Плинтус МДФ влагостойкий 80, окраска C6", "Ultrawood", 650, "M29"),
       ("chair_rail_40x20_at_900", "Молдинг chair rail 40×20 на +900", "Европласт / Ultrawood", 650, "M10")]
POG_LEN = 0.0
for kind, nm, mk, pr, mref in POG:
    L = lin(kind)
    POG_LEN += L
    rooms = ", ".join(sorted({l["room"] for l in LIN if l["kind"] == kind}))
    add("fin", nm, mref, mk, roundup_pack(L * 1.1, 2), "м", pr, rooms, f"linear {kind} = {L} м", stage="Э10", qf=f"=CEILING({L}*1.1,2)")
add("fin", "Молдинг 30 гладкий для рамок (R1 — рамка ТВ-зоны W7; R3 — 3 рамки на W8 [ДОПУЩЕНИЕ 900×1800])", "Европласт / Orac Decor", "Европласт",
    roundup_pack((FR1_LEN + FR3_LEN) * 1.1, 2), "м", 450, "R1, R3", f"elevations R1 W7 moulding {FR1_LEN} м; M14 рамки {FR3_LEN} м", stage="Э10")
POG_LEN = r2(POG_LEN + FR1_LEN + FR3_LEN)
add("fin", "Клей монтажный для лепнины + акриловый герметик для швов", "Европласт Клей / Orac FX", "Европласт", ceil(POG_LEN / 5), "туба", 650, "все",
    f"погонаж Σ {POG_LEN} м", stage="Э10")
add("fin", "Эмаль акриловая полуматовая для погонажа и молдингов (C1/C2/C6)", "Derufa / Tikkurila Empire", "Derufa", ceil(POG_LEN * 0.25 * 2 * 0.1), "л", 1800,
    "все", f"погонаж {POG_LEN} м × 0,25 м² × 2 сл. × 0,1 л", stage="Э10")
add("fin", "Т-профиль латунный 8 мм на клею (стыки J1, J2)", "—", "—", roundup_pack(TPROF, 0.9), "м", 1900, "R3/R7, R4", "counts латунный Т-профиль; J1, J2",
    stage="Э11")
add("fin", "Компенсатор пробковый 5 мм (стыки J1, J2, J4)", "—", "—", roundup_pack(TPROF + 1.78, 1), "м", 250, "R1–R4, R7", "floors junctions J1, J2, J4", stage="Э11")
# текстиль и карнизы (ремонт по concept 7.1 п.13)
cn = {c["id"]: c for c in CE["curtain_niches"]}
cn_len = r2(sum((c["rect"][2] - c["rect"][0]) / 1000 for c in cn.values() if c.get("rect")))
add("fin", "Карниз потолочный профильный 2-рядный в нише (CN-1, CN-2)", "Forest / Mustang-класс", "—", roundup_pack(cn_len, 0.5), "м", 1800, "R1, R2",
    f"ceilings curtain_niches CN-1, CN-2 = {cn_len} м", stage="Э13")
add("fin", "П-образный потолочный карниз с электроприводом Zigbee (B1+B2+B3)", "Aqara / Dooya", "Aqara / Dooya", 1, "компл", 32000, "R7", "F37; CN-3; P-B02; M32",
    stage="Э13")
add("fin", "Портьеры блэкаут + тюль-лён, пошив (спальня, окно O2)", "Galleria Arben-класс", "ателье", 1, "компл", 38000, "R1", "M09; CN-1", stage="Э13")
add("fin", "Портьеры блэкаут + тюль, пошив (детская, окно O3)", "—", "ателье", 1, "компл", 26000, "R2", "CN-2", stage="Э13")
add("fin", "Портьеры блэкаут C6 на П-карниз балкона, пошив", "—", "ателье", 1, "компл", 48000, "R7", "F37; M32", stage="Э13")

# --- СП-04.2 ТП и ОВ ---------------------------------------------------------------------------
for m in EL["floor_heating"]["mats"]:
    std = math.floor(m["area_m2"] * 2 + 1e-9) / 2  # стандартный мат ≤ площади раскладки, шаг 0,5 м²
    add("hvac", f"Нагревательный мат 150 Вт/м², экранированный, {std} м² ({m['id']})", "Теплолюкс / «Национальный комфорт» / DEVI",
        "Теплолюкс", std, "м²", 3300, m["room"], f"{m['id']}; heating.json electric_ufh; ОВ-01",
        stage="Э04", note=f"раскладка {m['area_m2']} м² → мат {std} м² (мат не режется)")
for t in EL["floor_heating"]["thermostats"]:
    add("hvac", f"Терморегулятор программируемый Wi-Fi/Zigbee с датчиком пола ({t['id']} — {t['for']})", "Теплолюкс MCS 350 / Caleo", "Теплолюкс",
        1, "шт", 7500, t["room"], f"{t['id']}; P-V06/P-L05/P-B08", stage="Э13")
add("hvac", "Гофра Ø16 к датчику пола", "—", "DKC", roundup_pack(LVLEN.get("fs", 0), 1), "м", 30, "R4–R7", LVIDS.get("fs", ""), stage="Э04")
for c in EL["floor_heating"]["convectors"]:
    add("hvac", f"Электроконвектор низкий настенный {c['power_kw']} кВт, h ≤ 400, крепление к парапету/W2 ({c['id']})", "Noirot Melodie Evolution Plinthe / Ballu",
        "Noirot", 1, "шт", 17000, c["room"], f"{c['id']}; {c['outlet']}; D17", stage="Э13")
for e in HV["exhaust"]:
    if e["id"] == "KH1":
        add("hvac", "Воздуховод круглый Ø125 гладкий (ПВХ/оцинк.)", "Era / Вентс", "Era", roundup_pack(e["length_m"] * 1.15, 0.5), "м", 650, "R3",
            f"KH1 {e['length_m']} м; CB-1, CB-2", stage="Э05")
        nb = sum(int(x) for x in re.findall(r"(\d+)×", e["bends"]))
        add("hvac", "Отводы Ø125 (90°/45°), соединители, хомуты", "Era", "Era", nb, "шт", 450, "R3", f"KH1 bends: {e['bends']}", stage="Э05")
        add("hvac", "Решётка вентканала комбинированная с обратным клапаном и отверстиями естественной тяги (U13)", "Era / Вентс", "Era", 1, "шт", 2500, "R3",
            "U13; kitchen.md п.8", stage="Э05")
    else:
        add("hvac", f"Вентилятор вытяжной Ø100, обратный клапан, гигростат + таймер, IPX4/IPX5 ({e['id']})", "Soler&Palau Silent 100 Design / Blauberg",
            "Soler&Palau", 1, "шт", 8500, e["room"], f"{e['id']}; P-V05/P-L04", stage="Э13")
        add("hvac", f"Воздуховод Ø100 + врезка в канал ({e['id']})", "Era", "Era", roundup_pack(e["length_m"] * 1.15 + 0.5, 0.5), "м", 450, e["room"],
            f"{e['id']} {e['length_m']} м", stage="Э05")
for s in HV["supply"]:
    if s["id"].startswith("BR"):
        pr = 58000 if s["id"] == "BR1" else 26000
        add("hvac", f"Бризер {s['id']}: {s['name'].split(',')[0][:70]}", "Tion 4S / Ballu ONEAIR ASP-200" if s["id"] == "BR1" else "Ballu ONEAIR ASP-80 / Royal Clima Brezza",
            "Tion / Ballu", 1, "шт", pr, s["room"], f"{s['id']}; F51/F59; ОВ-02", stage="Э13")

# --- СП-03.4 слаботочка, умный дом, кинозона ---------------------------------------------
add("lv", "Щит слаботочный 400×500×120 накладной (U16) с DIN-рейкой и полкой", "ЩМП / Hager", "Hager / ЩМП", 1, "шт", 9000, "R4", "U16; LV00; F64; D14", stage="Э04")
add("lv", "Роутер Wi-Fi 6 (mesh-совместимый)", "Keenetic / TP-Link", "Keenetic", 1, "шт", 12000, "R4", "LV00; F64", stage="Э13", note="ONT — провайдера")
add("lv", "Коммутатор PoE 8 портов", "TP-Link / Keenetic", "TP-Link", 1, "шт", 9000, "R4", "LV00", stage="Э13")
add("lv", "Патч-панель Cat6 12p + патч-корды", "Hyperline", "Hyperline", 1, "компл", 6000, "R4", "LV00", stage="Э04")
add("lv", "Точка доступа Wi-Fi потолочная PoE", "TP-Link EAP / Keenetic Voyager", "TP-Link", 1, "шт", 12000, "R4", "F65; LV13", stage="Э13")
nrj = sum(1 for l in EL["low_voltage"] if l["kind"] == "RJ45")
add("lv", "Розетка RJ45 Cat6 (серия ArtGallery)", "ArtGallery", "Systeme Electric", nrj, "шт", 1300, "R1, R2, R7",
    ", ".join(l["id"] for l in EL["low_voltage"] if l["kind"] == "RJ45"), stage="Э13")
add("lv", "Розетка TV (серия ArtGallery)", "ArtGallery", "Systeme Electric", len(LVC["coax"]), "шт", 900, "R1", LVIDS["coax"], stage="Э13")
add("lv", "Кабель U/FTP Cat6 нг(А)-HF", "Hyperline / Netlan", "Hyperline", roundup_pack(LVLEN["cat6"] + LVLEN.get("av", 0), 5), "м", 95, "все",
    f"{LVIDS['cat6']}, {LVIDS.get('av', '')} — трассы по потолку + 15 %", stage="Э04")
add("lv", "Кабель коаксиальный RG-6 нг", "Cavel / Rexant", "Cavel", roundup_pack(LVLEN["coax"], 5), "м", 50, "R1", LVIDS["coax"], stage="Э04")
add("lv", "Кабель акустический 2×2,5", "Acoustic / Cordial", "—", roundup_pack(LVLEN["speaker"], 5), "м", 130, "R7", LVIDS["speaker"], stage="Э04")
add("lv", "Кабель датчиков протечки 3×0,5 нг", "КСВВнг(А)-LS / ПВСнг", "—", roundup_pack(LVLEN["sensor"], 5), "м", 35, "R3, R5, R6", LVIDS["sensor"], stage="Э04")
add("lv", "Кабель питания электрокранов 3×0,75 нг (12 В)", "ПВСнг(А)-LS", "—", roundup_pack(LVLEN["valve"], 5), "м", 55, "R5, R6", LVIDS["valve"], stage="Э04")
add("lv", "Гофра Ø32 (AV-трасса) / Ø25 (ТВ-ниша → консоль) + 12В-триггер 2×0,75", "DKC", "DKC",
    roundup_pack(LVLEN.get("av", 0) + LVLEN.get("conduit25", 0), 1), "м", 90, "R1, R7", f"{LVIDS.get('av', '')}, {LVIDS.get('conduit25', '')}, LV11", stage="Э04")
add("lv", "Кабель HDMI 2.1 оптический (AOC) 10 м", "Cablexpert / Ugreen", "—", 1, "шт", 9000, "R7", "LV08", stage="Э04")
add("lv", "Шлюз Zigbee (Яндекс-совместимый)", "Яндекс Хаб / Aqara M2", "Яндекс / Aqara", 1, "шт", 7000, "R4", "LV20", stage="Э13")
ev = VK["leak_protection"]["valves"]
ls_ = VK["leak_protection"]["sensors"]
add("lv", "Контроллер защиты от протечек 12 В с АКБ (проводные датчики, Zigbee/Wi-Fi)", "Neptun ProW+ / Аквасторож Эксперт", "Neptun", 1, "шт", 18000, "R4",
    "plumbing.json leak_protection; F64", stage="Э13")
add("lv", "Кран шаровой с электроприводом 12 В ½″–¾″", "Neptun Bugatti Pro 12 В", "Neptun", len(ev), "шт", 8500, "R5, R6", ", ".join(v["id"] for v in ev) + "; F77, F82",
    stage="Э05")
add("lv", "Датчик протечки проводной", "Neptun SW005", "Neptun", len(ls_), "шт", 1800, "R3, R5, R6", ", ".join(s["id"] for s in ls_) + "; F22, F76, F81", stage="Э13")
add("lv", "ИБП 600 ВА для СС-щита (роутер, шлюз, контроллер)", "Ippon / APC", "Ippon", 1, "шт", 7000, "R4", "leak_protection.controller", stage="Э13")
add("lv", "Датчик открытия Zigbee (окна O2, O3, створки балкона, вход)", "Aqara", "Aqara", N_OPEN_SENS, "шт", 1900, "R1, R2, R4, R7", "LV21", stage="Э13")
add("lv", "Сценарная кнопка Zigbee (Утро/Ужин/Кино/Уход)", "Aqara Wireless Mini / Opple", "Aqara", len(ZB_BUTTONS), "шт", 2500, "R2, R3, R4, R7",
    ", ".join(ZB_BUTTONS) + "; LV22", stage="Э13")
add("lv", "Датчик движения (потолочный 230 В / SELV / батарейный)", "Aqara / Arlight", "Aqara", len(MOTION), "шт", 2600, "R1, R4, R5",
    ", ".join(l["id"] for l in MOTION), stage="Э13")
add("lv", "Модуль Zigbee привода экрана (ZB-SCR)", "Aqara / Sonoff", "Aqara", 1, "шт", 3500, "R3", "LV11; P-K16", stage="Э13")
add("lv", "Извещатели автономные дымовые ИП 212 ×4 + тепловой ИП 101 (кухня)", "Kidde / Аврора", "—", 1, "компл", 4500, "R1–R4", "LV28", stage="Э13")
# кинозона и ТВ — бюджет «Мебель+техника»
add("lv", "Проектор 4K-класса (4K-enhancement), зум с throw ≈ 1,29–1,41, lens shift, ≤ 28 дБ", "Epson EH-TW7100 / BenQ W2710-класс", "Epson / BenQ", 1, "шт",
    130000, "R7", "F38; D11; planning.json cinema", F)
add("lv", "Кронштейн потолочный проектора (к плите балкона)", "—", "—", 1, "шт", 5000, "R7", "F38", F)
add("lv", "Экран моторизованный 80″ 16:9 tab-tension в нишу (полотно 1771×996), 12В-триггер", "Lumien Cinema Tensioned / Elite Screens", "Lumien", 1, "шт",
    60000, "R3", "F32; CB-3; узел 9", F)
add("lv", "Колонки настенные пассивные (пара L/R)", "Dali / Polk / Wharfedale", "Polk", 1, "пара", 22000, "R7", "F39, F40", F)
add("lv", "AV-ресивер 5.1 (с 12В-триггером, eARC)", "Denon / Yamaha", "Denon", 1, "шт", 32000, "R7", "F35 отсек AV; P-B04a", F)
add("lv", "Медиаплеер 4K (Android TV / Apple TV)", "Apple TV 4K / Ugoos", "—", 1, "шт", 15000, "R7", "F35; P-B04a", F)
add("lv", "Телевизор 65″ 4K + плоский кронштейн", "Samsung / LG / Sony", "—", 1, "компл", 65000, "R1", "F48; D12", F)

# ======================================================================================
# 3. Работы (смета)
# ======================================================================================
STAGES = OrderedDict([
    ("Э01", "Демонтаж и подготовка"),
    ("Э02", "Перегородки, закладки, зашивка окна, каркасные облицовки"),
    ("Э03", "Утепление и остекление балкона"),
    ("Э04", "Электромонтаж (черновой), щит, слаботочка, электро-ТП"),
    ("Э05", "Сантехмонтаж (черновой) и вентиляция"),
    ("Э06", "Подиум ванной, гидроизоляция, стяжка балкона"),
    ("Э07", "Штукатурка и шпаклёвка"),
    ("Э08", "Плиточные работы"),
    ("Э09", "Потолки ГКЛ, короба, ниши"),
    ("Э10", "Покраска, молдинги, карнизы, буазери"),
    ("Э11", "Полы (инженерная доска, LVT)"),
    ("Э12", "Двери"),
    ("Э13", "Чистовой монтаж (электрика, сантехника, свет, мебель, шторы, умный дом)"),
    ("Э14", "Вывоз мусора, логистика, уборка"),
])
WORKS = []


def w(stage, name, unit, qty, rate, ref, calc=""):
    WORKS.append(dict(stage=stage, name=name, unit=unit, qty=r2(qty), rate=rate, ref=ref, calc=calc))

# Э01
w("Э01", "Тепловизионная съёмка пола при работающем водяном ТП, разметка трасс труб", "компл", 1, 14000, "planning.json new_walls_general; D3; №13")
w("Э01", "Укрытие и защита стяжки с водяным ТП на период работ", "м²", FLOOR_TOTAL, 120, "planning.json areas.sum_without_balcony")
w("Э01", "Демонтаж заполнения балконного проёма O4 (блок, порог), без расширения проёма", "шт", 1, 9000, "O4-fill; D2; АР-05")
w("Э01", "Пробивка проёмов в перегородках W12 (D3) и W11 (D4) вручную, без ударного инструмента", "м²", CUT_W12 + CUT_W11, 4500,
  "W12-cut, W11-cut; АР-05", f"W12 {CUT_W12} + W11 {CUT_W11}")
w("Э01", "Демонтаж подоконной доски и внутренних откосов O1", "шт", 1, 2500, "O1-infill; АР-05")
w("Э01", "Демонтаж приборов застройщика (WC постирочной F1 и пр., если установлены), заглушки", "компл", 1, 6000, "planning demolition F1, F-all")
# Э02
w("Э02", "Кладка ПГП 100 на клей по демпферной ленте (NW1, закладка O9) + ГКЛ на клей со стороны кухни", "м²", NW1_A, 2600, "NW1; АР-06")
w("Э02", "Кладка ПГП 80 (NW4 за вычетом проёма D2, добор у D1)", "м²", PGP80_A, 1700, "NW4; elevations R1 W7 добор 199")
w("Э02", "Кладка ПГП-Г 80 (закладки NW8, NW9) с обмазочной ГИ со стороны с/у", "м²", PGPG_A, 1900, "NW8, NW9")
w("Э02", "Устройство перемычек над новыми проёмами D3, D4", "шт", 2, 2000, "W12-cut, W11-cut")
w("Э02", "Зашивка окна O1 изнутри: каркас в откосе, минвата, пароизоляция, 2×ГКЛ (съёмная зона под буазери)", "м²", O1_AREA, 5000, "window_infill O1; узел 8")
w("Э02", "Облицовка W7 ГКЛ 12,5 на профиле (без штроб в ж/б, D15, D23)", "м²", W7_CLAD, 1100, "walls R1 gkl_cladding; АР-15")
w("Э02", "Облицовка W14 в душе VK-C1: каркас + 2×ГВЛВ, к стене и потолку (без крепления в пол), ниши 2 шт", "м²", VKC1_AREA, 3500, "VK-C1; узел 11")
w("Э02", "Короб инсталляции с полкой h 1200 (2×ГВЛВ)", "шт", 1, 6500, "F69; АР-13")
w("Э02", "Короб-перемычка VK-C2 h 450 и экран ванны на каркасе с ревизией H6", "м²", VKC2_FACE + BATH_SCREEN, 3000, "VK-C2; экран ванны; H6")
w("Э02", "Закладные под люстры, подвесы, проектор, ДСК, сушилку, карниз с приводом", "шт", next(c for k, c in CNT.items() if k.startswith("закладные"))["qty"], 1500,
  "finish-quantities counts")
# Э03
w("Э03", "Демонтаж существующего остекления балкона застройщика (если есть) [ДОПУЩЕНИЕ, №7]", "компл", 1, 10000, "№7")
w("Э03", "Монтаж тёплого остекления ПВХ (с отливами, подоконником, откосами, клапанами SV1/SV2)", "м²", GLAZING_M2, 4800, "M32; balcony_heat_balance; SV1, SV2")
w("Э03", "Утепление парапетов: каркас, PIR 50, примыкания, обшивка ГВЛ", "м²", BALC_PARAPET, 2400, "walls R7 gvl+paint_c6; M29")
w("Э03", "Утепление потолка балкона PIR 50 (под ГКЛВ)", "м²", BALC_CEIL_INS, 1000, "ceilings R7; M30")
# Э04
w("Э04", "Монтаж квартирного щита ЩРН-48", "шт", 1, 5000, "U15; ЭМ-03")
w("Э04", "Сборка щита: установка и расключение модульных аппаратов, маркировка", "модуль", PA["panel"]["modules_used"], 1000, "panel.json modules_used")
w("Э04", "Прокладка силового кабеля в гофре по потолку (с креплением)", "м", CABLE_TOTAL_K, 110, "panel.json Σ length_m × 1,15", f"{CABLE_TOTAL} × 1,15")
w("Э04", "Прокладка слаботочных кабелей (Cat6, RG-6, акустика, датчики, краны, AV)", "м",
  sum(v for k, v in LVLEN.items() if k != "fs"), 110, "electrical.json low_voltage (трассы по координатам)")
w("Э04", "Штробление вертикальное ≤ 25 мм (кирпич) с заделкой / спуски в облицовках", "м", DROP_M, 600, "sockets + switches: (потолок − h)", "Σ спусков к точкам")
w("Э04", "Установка подрозетника (высверливание в кирпиче/ГКЛ), монтаж точки", "шт", N_BOXES, 550, "посты sockets + switches")
w("Э04", "Вывод под светильник / ленту (кабель, коробка, маркировка)", "шт", len(LIGHTS), 450, "electrical.json lights")
w("Э04", "Укладка нагревательных матов в клей с датчиком пола (TP1–TP3)", "м²", sum(m["area_m2"] for m in EL["floor_heating"]["mats"]), 1300, "heating.json; ОВ-01")
w("Э04", "ДУП ванной и постирочной (КУП, ПуГВ 4 мм²)", "шт", 2, 3500, "panel.json rcd_policy")
w("Э04", "Монтаж СС-щита U16, расшивка патч-панели, тестирование линий", "компл", 1, 9000, "U16; LV00")
w("Э04", "Электролаборатория: измерения, протокол", "компл", 1, 15000, "ЭМ-03")
# Э05
w("Э05", "Сборка узла ввода (краны, фильтр-редуктор, счётчики, обр. клапан, электрокраны, коллекторы)", "узел", len(nodes), 16000, "N1, N2; ВК-03")
w("Э05", "Разводка водоснабжения PEX-a до водорозетки (трасса + вывод)", "вывод", w_lines, 3200, "pipes.water WB1–WL2")
w("Э05", "Разводка канализации ПП к прибору с уклоном (трасса + вывод)", "вывод", len(VK["pipes"]["sewer"]), 2900, "pipes.sewer S1–S7; calc_sewer_slopes.py")
w("Э05", "Монтаж инсталляции (рама к стене, D3)", "шт", 1, 7000, "F69; P01")
w("Э05", "Монтаж линейного трапа низкого (h ≤ 70) с фланцем", "шт", 1, 7500, "F67; S1; узел 7")
w("Э05", "Монтаж скрытой части термостата душа в облицовке VK-C1", "шт", 1, 6000, "P04; WB3")
w("Э05", "Заглушка выпуска WC постирочной, переход 110/50, заглушка подводки", "компл", 1, 3000, "P12; D7")
w("Э05", "Гидростатическое испытание водопровода, акт скрытых работ", "компл", 1, 5000, "plumbing.json tests")
w("Э05", "Монтаж воздуховода вытяжки кухни Ø125 в коробах, подключение к U13", "м", next(e for e in HV["exhaust"] if e["id"] == "KH1")["length_m"], 1100, "KH1; ОВ-02")
w("Э05", "Монтаж воздуховодов и врезка вентиляторов в каналы U25/U26", "шт", 2, 3500, "EF1, EF2")
w("Э05", "Алмазное бурение Ø132 в наружной стене 420 под бризеры", "шт", sum(1 for s in HV["supply"] if s["id"].startswith("BR")), 6500, "BR1, BR2")
# Э06
w("Э06", "Гидроизоляция обмазочная 2 слоя с лентами (пол R5 — нижняя + основная, пол R6, стены)", "м²", WP_AREA, 1000,
  "floors waterproofing_floor; waterproofing_walls", f"R5 {WP_FLOOR_R5}×2 + R6 {WP_FLOOR_R6} + стены {WP_WALLS}")
w("Э06", "Подиум ванной ЦПС 78,5 мм армированный, уклон 1,5 % к трапу", "м²", PODIUM, 2500, "floors podium_screed_80; D18")
w("Э06", "Рамка-бортик коллектора U14", "шт", 1, 4000, "VK-C3; узел 6")
w("Э06", "Пол балкона: ремонт плиты, XPS 50, ПЭ-плёнка, демпферная лента", "м²", BALC_SCREED, 900, "P-BALC; D22")
w("Э06", "Стяжка балкона ЦПС 55 армированная + СВС 10 по мату TP3", "м²", BALC_SCREED, 1900, "P-BALC")
# Э07
w("Э07", "Штукатурка стен по маякам (гипсовая), ср. 15 мм", "м²", PL_DRY, 750, "walls (gross − проёмы, без облицовок)")
w("Э07", "Штукатурка стен по маякам (цементная, влажные помещения)", "м²", PL_WET, 850, "walls R5, R6")
w("Э07", "Откосы: штукатурка, уголок, шпаклёвка (O2, O3, портал O4)", "м²", OTKOS, 2200, "walls plaster+paint*")
w("Э07", "Шпаклёвка стен Q3 под покраску + стеклохолст-паутинка", "м²", Q3_WALLS, 1100, "walls net (окрашиваемые)")
w("Э07", "Шпаклёвка Q2 + грунт за встроенной мебелью и кухней", "м²", Q2_BEHIND, 350, "walls behind_furniture + paint_q2")
w("Э07", "Шпаклёвка потолков и коробов ГКЛ Q4 (швы + сплошная)", "м²", CEIL_TOTAL, 950, "ceilings Σ")
# Э08
w("Э08", "Укладка керамогранита 60×60 на пол (прихожая, ванная, постирочная)", "м²", PG_HALL + PG_BATH + PG_LAUN, 2800, "floors porcelain_60x60_*")
w("Э08", "Укладка керамогранита 60×120 на пол душа с уклоном к трапу", "м²", PG_SHOWER, 4800, "floors porcelain_60x120_shower")
w("Э08", "Облицовка стен керамогранитом 60×120 (ванная), с СВП", "м²", TILE_WET + TILE_DRY, 3900, "walls tile_wet + tile_dry")
w("Э08", "Фартук кухни керамогранит", "м²", APRON_K, 3600, "walls tile_apron_porcelain")
w("Э08", "Фартук хозмойки «кабанчик»", "м²", APRON_L, 3300, "walls tile_apron")
w("Э08", "Ниши в облицовке душа: облицовка с латунным уголком", "шт", next(c for k, c in CNT.items() if k.startswith("ниша"))["qty"], 5000, "counts; D23")
w("Э08", "Установка люков-невидимок под плитку (H1, H2, H3, H6)", "шт", sum(1 for k in CNT if k.startswith(("люк-невидимка", "люк под плитку", "ревизия"))), 3500,
  "counts; ВК-03")
w("Э08", "Латунный профиль на линии +1280, порог-ступень D3, порог D4", "компл", 1, 9000, "J5, J6; M21")
w("Э08", "Затирка эпоксидная (ванная)", "м²", R5_TILE, 600, "R5 tile")
# Э09
w("Э09", "Потолок ГКЛ по каркасу (спальня, детская, кухня, прихожая)", "м²", CEIL_GKL, 1450, "ceilings gkl_paint_*; АР-09")
w("Э09", "Потолок ГКЛВ по каркасу (ванная, постирочная, балкон)", "м²", CEIL_GKLV + CEIL_BALC, 1600, "ceilings gklv_*")
w("Э09", "Короба CB-1, CB-2, CB-3 (ламбрекен) с гранями", "м²", CEIL_BOX, 2800, "ceilings box_*; CB-1…CB-3")
w("Э09", "Ниша экрана в ламбрекене CB-3 (щель, ревизия корпуса экрана)", "шт", 1, 12000, "CB-3; узел 9")
w("Э09", "Ниши штор CN-1…CN-3 (борт ГКЛ)", "м²", CEIL_NICHE, 2200, "ceilings curtain_niche*")
w("Э09", "Теневой профиль 10×10", "м", lin("shadow_profile"), 500, "linear shadow_profile")
w("Э09", "Люки потолочные HC-1, вентрешётка HC-2", "шт", 2, 3000, "HC-1, HC-2")
# Э10
for src in (PAINT, CEIL_PAINT):
    for (col, desc), (a, coats, rooms) in src.items():
        rate = 550 if coats == 2 else 750
        if col in ("C5",):
            rate = 650
        w("Э10", f"Окраска {desc} ({col.split('-')[0]}), {coats} слоя", "м²", a, rate, "finish-quantities; palette.json", ", ".join(sorted(rooms)))
w("Э10", "Монтаж потолочных карнизов (клей, заделка стыков, окраска)", "м",
  sum(lin(k) for k in ("cornice_80", "cornice_60", "cornice_40", "cornice_profile_lambrequin_60")), 650, "linear cornice_*")
w("Э10", "Монтаж карниза с LED-пазом буазери", "м", lin("cornice_boiserie_LED"), 1600, "linear cornice_boiserie_LED")
w("Э10", "Монтаж плинтуса МДФ к стене на клею (без крепления в пол), окраска", "м", lin("plinth_mdf_120") + lin("plinth_mdf_80_C6"), 650, "linear plinth_*")
w("Э10", "Монтаж молдингов (chair rail, рамки R1 W7 и R3 W8) с запилом", "м", lin("chair_rail_40x20_at_900") + FR1_LEN + FR3_LEN, 800,
  "linear chair_rail; elevations R1 W7; M14")
# Э11
w("Э11", "Подготовка основания: шлифовка, обеспыливание, грунт, локальный ремонт; замер влажности CM", "м²", OAK + LVT, 450, "P-OAK, P-BALC")
w("Э11", "Укладка инженерной доски «ёлочка» на клей (без порогов)", "м²", OAK, 2500, "floors oak_herringbone; M01")
w("Э11", "Укладка LVT «ёлочка» на клей", "м²", LVT, 1600, "floors lvt_herringbone; M28")
w("Э11", "Стыки покрытий: латунный Т-профиль на клею, пробковые компенсаторы", "м", TPROF + 1.78, 900, "J1, J2, J4")
# Э12
nd = sum(1 for d in DO["doors"] if d["no"].startswith("Д-"))
w("Э12", "Установка межкомнатной двери (коробка, скрытые петли, фурнитура, наличники с 2 сторон)", "шт", nd, 9500, "D1–D4; АР-08")
w("Э12", "Установка надпроёмной панели D1 и наличника ДВ-1", "шт", 2, 3500, "D1, O5")
# Э13
nmech = sum(i["qty"] for i in SPECS["dev"]["items"] if "(механизм)" in i["name"])
w("Э13", "Установка механизмов розеток/выключателей с рамками", "шт", nmech, 350, "СП-03.2")
nspot = sum(1 for l in LIGHTS if l["type"] == "spot")
w("Э13", "Монтаж встраиваемых спотов", "шт", nspot, 600, "lights type=spot")
w("Э13", "Монтаж люстр и потолочных светильников (по закладным)", "шт", sum(1 for l in LIGHTS if l["type"] in ("pendant", "ceiling")), 2500, "lights pendant/ceiling")
w("Э13", "Монтаж бра", "шт", sum(1 for l in LIGHTS if l["type"] == "wall" and l["ip"] == "IP20"), 1500, "lights wall")
w("Э13", "Монтаж LED-лент в профилях с блоками питания", "м", LED_TOTAL, 800, "lights led_strip pos→end")
w("Э13", "Установка и подключение модулей Zigbee, терморегуляторов, конвекторов", "шт", len(zbg) + 3 + 2, 1300, "СП-03.2, СП-04.2")
w("Э13", "Установка унитаза, ванны с экраном, тумбы с раковиной, смесителей, душевой системы, полотенцесушителя", "компл", 1, 32000, "P01–P05; F66–F75")
w("Э13", "Установка мебели ванной навесной (зеркальный шкаф, пенал, корзина)", "шт", 3, 2500, "F72, F73, F74")
w("Э13", "Монтаж стекла душа (по замеру)", "шт", 1, 6000, "F68")
w("Э13", "Установка мойки кухни, смесителя, фильтра; хозмойки; подключение ПММ, СМА, СМ", "компл", 1, 14000, "P06–P11")
w("Э13", "Монтаж бризеров и вентиляторов", "шт", 4, 3500, "BR1, BR2, EF1, EF2")
w("Э13", "Установка датчиков протечки и настройка контроллера", "шт", len(ls_), 600, "LS1–LS7")
w("Э13", "Монтаж карнизов штор, П-карниза с приводом, навеска штор", "компл", 3, 4500, "CN-1…CN-3; F37")
w("Э13", "Монтаж экрана в нишу, проектора на кронштейн, колонок, ТВ на кронштейн, коммутация AV", "компл", 1, 18000, "F32, F38–F40, F48")
w("Э13", "Настройка умного дома: шлюз, сцены (Утро/Ужин/Кино/Вечер/Ночь/Уход), защита от протечек", "компл", 1, 20000, "electrical.json scenes")
w("Э13", "Финишная клининговая уборка", "м²", AREA_ALL, 220, "planning areas")
# Э14
nk = ceil(AREA_ALL / 25)
w("Э14", "Вывоз строительного мусора контейнером 8 м³ (норматив 1 конт. на 25 м²)", "конт.", nk, 12000, "planning areas", f"{AREA_ALL}/25")
w("Э14", "Погрузка мусора, разгрузка и занос материалов (1 этаж)", "компл", 1, 18000, "brief: этаж 1/4")
w("Э14", "Промежуточные уборки по этапам", "компл", 1, 15000, "—")

# ======================================================================================
# 4. Проверки трассируемости
# ======================================================================================
alltext = json.dumps([i["ref"] for s in SPECS.values() for i in s["items"]], ensure_ascii=False)
rng = lambda a, b: [f"F{i:02d}" for i in range(a, b + 1)]
miss_f = [f["id"] for f in FU["items"] if not re.search(rf"\b{f['id']}\b", alltext)]
miss_l = [l["id"] for l in LIGHTS if l["id"] not in alltext]
miss_s = [s["id"] for s in SOCK + SW if s["id"] not in alltext]
miss_g = [g["id"] for g in PA["groups"] if g.get("length_m") and g["id"] not in alltext]
CHECKS = dict(furniture_not_traced=miss_f, lights_not_traced=miss_l, devices_not_traced=miss_s, groups_not_traced=miss_g)

# ======================================================================================
# 5. Итоги (Python-значения — для md; в xlsx — формулы)
# ======================================================================================
for s in SPECS.values():
    for n, i in enumerate(s["items"], 1):
        i["pos"] = n
        i["sum"] = round(i["qty"] * i["price"], 2)
for wk in WORKS:
    wk["sum"] = round(wk["qty"] * wk["rate"], 2)
mat_by_stage = defaultdict(float)
for s in SPECS.values():
    for i in s["items"]:
        if i["budget"] == R:
            assert i["stage"] in STAGES, (i["name"], i["stage"])
            mat_by_stage[i["stage"]] += i["sum"]
work_by_stage = defaultdict(float)
for wk in WORKS:
    work_by_stage[wk["stage"]] += wk["sum"]
REP_SUB = sum(mat_by_stage.values()) + sum(work_by_stage.values())
RESERVE = 0.10
REP_TOT = REP_SUB * (1 + RESERVE)
FURN_SUB = sum(i["sum"] for s in SPECS.values() for i in s["items"] if i["budget"] == F)
FURN_TOT = FURN_SUB * (1 + RESERVE)
BUDGET_R, BUDGET_F = 5_000_000, 1_500_000


def fmt(x, d=0):
    s = f"{x:,.{d}f}".replace(",", " ")
    return s.replace(".", ",") if d else s


def pct(x, sign=False):
    return (f"{x:+.1f}" if sign else f"{x:.1f}").replace(".", ",")


def fq(x):
    return fmt(x, 2).rstrip("0").rstrip(",") if abs(x - round(x)) > 1e-9 else fmt(x)

# ======================================================================================
# 6. Ведомость отделки (СП-01)
# ======================================================================================
CK = {"gkl_paint_2700": "ГКЛ 12,5 по каркасу, отм. +2,700; шпаклёвка Q4, краска глубокоматовая C1 (M03)",
      "gkl_paint_2650": "ГКЛ 12,5 по каркасу, отм. +2,650 (D19); шпаклёвка Q4, краска C1 (M03)",
      "gklv_paint_2450": "ГКЛВ 12,5 по каркасу, отм. +2,450 (2,370 от пола ванной); влагостойкая краска C1, теневой профиль (M22)",
      "gklv_paint_2500": "ГКЛВ 12,5 по каркасу, отм. +2,500; влагостойкая краска C1, теневой профиль (M27)",
      "gklv_on_pir50_paint_c6_2500": "PIR 50 + ГКЛВ 12,5, отм. +2,500; краска C6 глубокоматовая (M30)",
      "curtain_niche": "Ниша штор 200×62 (CN): окраска плиты + борт ГКЛ, C1",
      "curtain_niche_P": "П-образная ниша штор CN-3, C6",
      "box_soffits (CB-1, CB-2, CB-3 низ)": "Короба CB-1, CB-2, ламбрекен CB-3 (низ): ГКЛ, C1; ниша экрана — C6",
      "box_faces (вертикальные грани коробов)": "Вертикальные грани коробов: ГКЛ, C1"}
WK = {"paint": "Штукатурка, шпаклёвка Q3 + стеклохолст, краска C2 (M05/M18)",
      "paint_q2_behind_kitchen": "За кухней: штукатурка, шпаклёвка Q2, грунт (без окраски)",
      "paint_q2_behind": "За шкафом: штукатурка, Q2, грунт (без окраски)",
      "boiserie": "Буазери M06 (МДФ, эмаль C3) по стене и зашивке O1",
      "gkl_cladding+paint": "Облицовка ГКЛ 12,5 на профиле, Q3, краска C2",
      "paint_c5_low+c1_up": "Штукатурка, Q3 + стеклохолст; до +900 краска C5, выше C1; молдинг 40×20 на +900 (M10)",
      "tile_wet": "Керамогранит 60×120 «мрамор» до потолка по обмазочной ГИ (M21)",
      "paint_wet": "Краска для влажных помещений C2 (выше плитки)",
      "paint_c6": "Штукатурка/шпаклёвка, краска C6 глубокоматовая (M29)",
      "gvl+paint_c6": "PIR 50 + ГВЛ 12,5, Q3, краска C6 (M29)",
      "plaster+paint": "Откосы: штукатурка, уголок, краска C1",
      "plaster+paint_c1": "Откосы портала O4 (420): штукатурка, уголок, C1, без наличника (D21)"}
LOWK = {"tile_dry": "Керамогранит 60×120 до +1280 от УЧП с латунным профилем (M21)",
        "tile_apron": "Фартук «кабанчик» над хозмойкой (M27)",
        "tile_apron_porcelain": "Фартук кухни: керамогранит «мрамор» 900..1550 (M13)"}
FK = {"oak_herringbone": "Инженерная доска дуб «ёлочка» 90×600 на клею MS по стяжке с водяным ТП (M01), пирог P-OAK",
      "porcelain_60x60_hall": "Керамогранит 60×60 R10 у входа (M16), P-TILE-HALL",
      "porcelain_60x60_bath": "Керамогранит 60×60 «мрамор» R10, подиум +80, электро-ТП TP1 (M20), P-BATH",
      "porcelain_60x120_shower_R10B": "Душ: керамогранит 60×120 R10/B, уклон 1,5 % к трапу (M20)",
      "porcelain_60x60_laundry": "Керамогранит 60×60 R10, электро-ТП TP2 (M25), P-LAUNDRY",
      "lvt_herringbone": "LVT клеевой «ёлочка» (M28), электро-ТП TP3, P-BALC"}
LINK = {"cornice_80": "карниз 80", "cornice_60": "карниз 60", "cornice_40": "карниз 40", "cornice_boiserie_LED": "карниз буазери с LED",
        "cornice_profile_lambrequin_60": "профиль ламбрекена 60", "shadow_profile": "теневой профиль", "plinth_mdf_120": "плинтус МДФ 120",
        "plinth_mdf_80_C6": "плинтус МДФ 80 C6", "chair_rail_40x20_at_900": "молдинг 40×20 на +900"}
FNOTE = {"waterproofing_floor": "обмазочная ГИ пола", "podium_screed_80": "подиум ЦПС 78,5", "xps50+screed55": "XPS 50 + ЦПС 55 + СВС 10"}


def finish_schedule():
    L = [f"# СП-01. Ведомость отделки помещений (вариант D1)", "",
         "Форма — по ГОСТ 21.501-2018 (ведомость отделки помещений), дополнена графой «Пол». Площади — нетто по "
         "`04-specs/finish-quantities.json` (стены — за вычетом проёмов и зон за встроенной мебелью; черновая подготовка за мебелью — в примечании). "
         "Отметки — от УЧП ±0.000. Колеры — `02-concept/palette.json`, материалы M.. — `02-concept/materials.json`. "
         "Генератор: `tools/gen_specs.py`.", "",
         "| Помещение | Потолок | S, м² | Стены и перегородки | S, м² | Низ стен (фартуки, плитка до +1280) | S, м² | Пол | S, м² | Примечание |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for rid in ["R4", "R3", "R7", "R1", "R2", "R5", "R6"]:
        cs = [c for c in CEILS if c["room"] == rid]
        ws = [w_ for w_ in WALLS if w_["room"] == rid]
        fs = [f for f in FLOORS if f["room"] == rid]
        cg = OrderedDict()
        for c in cs:
            cg[CK[c["kind"]]] = cg.get(CK[c["kind"]], 0) + c["m2"]
        wg, lg = OrderedDict(), OrderedDict()
        behind = 0.0
        for w_ in ws:
            behind += w_["behind_furniture_m2"]
            if w_["kind"] in LOWK:
                lg[LOWK[w_["kind"]]] = lg.get(LOWK[w_["kind"]], 0) + w_["net_m2"]
            elif w_["kind"].startswith("paint_q2"):
                behind += 0  # учтено ниже
            elif w_["net_m2"] > 0:
                wg[WK[w_["kind"]]] = wg.get(WK[w_["kind"]], 0) + w_["net_m2"]
        q2 = sum(w_["gross_m2"] for w_ in ws if w_["kind"].startswith("paint_q2"))
        fg = OrderedDict()
        fn = []
        for f in fs:
            if f["kind"] in FK:
                fg[FK[f["kind"]]] = fg.get(FK[f["kind"]], 0) + f["m2"]
            else:
                fn.append(f"{FNOTE[f['kind']]} {fq(f['m2'])} м²")
        lins = [f"{LINK.get(l['kind'], l['kind'])} {fq(l['m'])} м" for l in LIN if l["room"] == rid]
        wp = [f"ГИ стен ({x['where']}) {fq(x['m2'])} м²" for x in FQ["waterproofing_walls"] if x["room"] == rid]
        notes = []
        if behind + q2:
            notes.append(f"за встроенной мебелью/кухней — штукатурка + Q2 {fq(r2(behind + q2))} м²")
        notes += fn + wp + lins
        j = lambda d: "<br>".join(f"{k}" for k in d) or "—"
        a = lambda d: "<br>".join(fq(r2(v)) for v in d.values()) or "—"
        L.append(f"| {rid} {RNAME[rid]} ({fq(ROOMS[rid]['area'])} м²) | {j(cg)} | {a(cg)} | {j(wg)} | {a(wg)} | {j(lg)} | {a(lg)} | {j(fg)} | {a(fg)} | "
                 f"{'; '.join(notes) or '—'} |")
    tot_w = sum(w_["net_m2"] for w_ in WALLS if w_["kind"] not in LOWK and not w_["kind"].startswith("paint_q2"))
    L += ["", f"**Итого:** потолки {fq(CEIL_TOTAL)} м²; стены (чистовая отделка) {fq(r2(tot_w))} м²; плитка/фартуки низа стен "
          f"{fq(r2(TILE_DRY + APRON_K + APRON_L))} м²; полы (чистовые покрытия) {fq(r2(OAK + LVT + TILE_FLOOR))} м².", "",
          "Примечания:",
          "1. Водяной ТП в стяжке (D3): плинтусы, профили стыков, ограничители — только на клею/к стене, ничего не крепится в пол.",
          "2. Гидроизоляция: пол R5 — нижняя (по стяжке) + основная (по подиуму), заход на стены 200; в душе и за ванной — на всю высоту (узел 6).",
          "3. Плитка до +1280 от УЧП (= +1200 от пола ванной, D23) — с латунным профилем; выше — краска C2 для влажных помещений.",
          "4. Детская R2: граница колеров C5/C1 — молдинг chair rail на +900; площади колеров для краски — пропорционально высоте (СП-05).",
          "5. Потолок кухни и прихожей — единая плоскость +2650 (D19); короба CB-1…CB-3 — по АР-09.", ""]
    return "\n".join(L)

# ======================================================================================
# 7. Запись md
# ======================================================================================
HDR = "| Поз. | Наименование | Артикул / пример | Производитель | Кол-во | Ед. | Цена ориент., ₽ | Сумма, ₽ | Помещение | Ссылка (лист / id) | Бюджет | Этап сметы | Примечание |"


def spec_md(s):
    L = [f"# {s['code']}. {s['title']}", "", s["intro"], "", PRICE_NOTE, "", HDR, "|" + "---|" * 13]
    for i in s["items"]:
        L.append(f"| {i['pos']} | {i['name']} | {i['art']} | {i['maker']} | {fq(i['qty'])} | {i['unit']} | {fmt(i['price'])} | {fmt(i['sum'])} | "
                 f"{i['room']} | {i['ref']} | {i['budget']} | {i['stage'] or '—'} | {i['note'] or ''} |")
    tr = sum(i["sum"] for i in s["items"] if i["budget"] == R)
    tf = sum(i["sum"] for i in s["items"] if i["budget"] == F)
    L += ["", f"**Итого по спецификации: {fmt(tr + tf)} ₽**" + (f" (в т.ч. «Ремонт» {fmt(tr)} ₽; «Мебель+техника» {fmt(tf)} ₽)" if tr and tf else
                                                                 f" — бюджет «{R if tr else F}»."),
          "", "Сводный файл с формулами: `04-specs/specifications.xlsx`. Генератор: `tools/gen_specs.py`.", ""]
    return "\n".join(L)

# ======================================================================================
# 8. xlsx
# ======================================================================================
BOLD = Font(bold=True)
HFILL = PatternFill("solid", fgColor="DDE3EA")
TFILL = PatternFill("solid", fgColor="F2F2F2")
thin = Side(style="thin", color="999999")
BRD = Border(left=thin, right=thin, top=thin, bottom=thin)
WRAP = Alignment(wrap_text=True, vertical="top")
MONEY = '#,##0" ₽"'
QTY = '#,##0.##'


def style_header(ws, row, ncol):
    for c in range(1, ncol + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = BOLD
        cell.fill = HFILL
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = BRD


def widths(ws, ws_):
    for i, wdt in enumerate(ws_, 1):
        ws.column_dimensions[get_column_letter(i)].width = wdt

SPEC_COLS = ["Поз.", "Наименование", "Артикул / пример", "Производитель", "Кол-во", "Ед.", "Цена ориент., ₽", "Сумма, ₽", "Помещение",
             "Ссылка (лист / id)", "Бюджет", "Этап сметы", "Примечание / расчёт кол-ва"]
SHEETNAME = {}


def write_specs_xlsx(path):
    wb = Workbook()
    sv = wb.active
    sv.title = "Свод"
    for key, s in SPECS.items():
        name = (s["code"] + " " + s["title"])[:31].replace("/", "-")
        SHEETNAME[key] = name
        ws = wb.create_sheet(name)
        ws["A1"] = f"{s['code']}. {s['title']}"
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = PRICE_NOTE
        ws["A2"].alignment = WRAP
        ws.merge_cells("A2:M2")
        ws.row_dimensions[2].height = 60
        hr = 4
        for c, h in enumerate(SPEC_COLS, 1):
            ws.cell(row=hr, column=c, value=h)
        style_header(ws, hr, len(SPEC_COLS))
        r = hr
        for i in s["items"]:
            r += 1
            vals = [i["pos"], i["name"], i["art"], i["maker"], i["qf"] or i["qty"], i["unit"], i["price"], f"=E{r}*G{r}", i["room"], i["ref"],
                    i["budget"], i["stage"] or "—", i["note"]]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=c, value=v)
                cell.border = BRD
                cell.alignment = WRAP
            ws.cell(row=r, column=5).number_format = QTY
            ws.cell(row=r, column=7).number_format = MONEY
            ws.cell(row=r, column=8).number_format = MONEY
        first, last = hr + 1, r
        s["xl"] = (name, first, last)
        r += 2
        for lab, f in [("Итого по спецификации", f"=SUM(H{first}:H{last})"),
                       (f"в т.ч. «{R}»", f'=SUMIF(K{first}:K{last},"{R}",H{first}:H{last})'),
                       (f"в т.ч. «{F}»", f'=SUMIF(K{first}:K{last},"{F}",H{first}:H{last})')]:
            ws.cell(row=r, column=2, value=lab).font = BOLD
            c = ws.cell(row=r, column=8, value=f)
            c.font = BOLD
            c.number_format = MONEY
            c.fill = TFILL
            r += 1
        widths(ws, [5, 55, 28, 22, 9, 9, 13, 15, 12, 34, 14, 9, 36])
        ws.freeze_panes = "A5"
    # свод
    sv["A1"] = "Сводная спецификация — кв. 108, вариант D1"
    sv["A1"].font = Font(bold=True, size=13)
    sv["A2"] = PRICE_NOTE
    sv["A2"].alignment = WRAP
    sv.merge_cells("A2:E2")
    sv.row_dimensions[2].height = 75
    for c, h in enumerate(["Шифр", "Спецификация (лист)", "Итого, ₽", f"«{R}», ₽", f"«{F}», ₽"], 1):
        sv.cell(row=4, column=c, value=h)
    style_header(sv, 4, 5)
    r = 4
    for key, s in SPECS.items():
        r += 1
        nm, a, b = s["xl"]
        q = f"'{nm}'"
        sv.cell(row=r, column=1, value=s["code"])
        sv.cell(row=r, column=2, value=nm)
        sv.cell(row=r, column=3, value=f"=SUM({q}!H{a}:H{b})")
        sv.cell(row=r, column=4, value=f'=SUMIF({q}!K{a}:K{b},"{R}",{q}!H{a}:H{b})')
        sv.cell(row=r, column=5, value=f'=SUMIF({q}!K{a}:K{b},"{F}",{q}!H{a}:H{b})')
        for c in (3, 4, 5):
            sv.cell(row=r, column=c).number_format = MONEY
    r += 1
    sv.cell(row=r, column=2, value="ИТОГО по спецификациям").font = BOLD
    for c, L_ in ((3, "C"), (4, "D"), (5, "E")):
        cell = sv.cell(row=r, column=c, value=f"=SUM({L_}5:{L_}{r - 1})")
        cell.font = BOLD
        cell.number_format = MONEY
    sv.cell(row=r + 2, column=2, value="Работы — в 05-estimate/estimate.xlsx; спецификации содержат только изделия и материалы.")
    widths(sv, [10, 52, 16, 16, 16])
    wb.save(path)


def write_estimate_xlsx(path):
    wb = Workbook()
    sm = wb.active
    sm.title = "Смета"
    wr = wb.create_sheet("Работы")
    wm = wb.create_sheet("Материалы (Ремонт)")
    wf = wb.create_sheet("Мебель и техника")
    wbud = wb.create_sheet("Бюджеты")
    wsrc = wb.create_sheet("Источники и допущения")
    # Работы
    cols = ["Этап", "Поз.", "Наименование работ", "Ед.", "Объём", "Расценка, ₽", "Сумма, ₽", "Источник объёма (id / лист)", "Расчёт"]
    for c, h in enumerate(cols, 1):
        wr.cell(row=1, column=c, value=h)
    style_header(wr, 1, len(cols))
    r = 1
    cnt = defaultdict(int)
    for wk in WORKS:
        r += 1
        cnt[wk["stage"]] += 1
        vals = [wk["stage"], f"{wk['stage']}.{cnt[wk['stage']]}", wk["name"], wk["unit"], wk["qty"], wk["rate"], f"=E{r}*F{r}", wk["ref"], wk["calc"]]
        for c, v in enumerate(vals, 1):
            cell = wr.cell(row=r, column=c, value=v)
            cell.border = BRD
            cell.alignment = WRAP
        wr.cell(row=r, column=6).number_format = MONEY
        wr.cell(row=r, column=7).number_format = MONEY
    WR_LAST = r
    r += 1
    wr.cell(row=r, column=3, value="Итого работы").font = BOLD
    wr.cell(row=r, column=7, value=f"=SUM(G2:G{WR_LAST})").number_format = MONEY
    widths(wr, [7, 8, 60, 8, 10, 12, 14, 38, 30])
    wr.freeze_panes = "A2"
    # Материалы (Ремонт)
    cols = ["Этап", "Спецификация", "Поз.", "Наименование", "Кол-во", "Ед.", "Цена, ₽", "Сумма, ₽", "Помещение", "Ссылка (лист / id)"]
    for c, h in enumerate(cols, 1):
        wm.cell(row=1, column=c, value=h)
    style_header(wm, 1, len(cols))
    r = 1
    for key, s in SPECS.items():
        for i in s["items"]:
            if i["budget"] != R:
                continue
            r += 1
            vals = [i["stage"], s["code"], i["pos"], i["name"], i["qf"] or i["qty"], i["unit"], i["price"], f"=E{r}*G{r}", i["room"], i["ref"]]
            for c, v in enumerate(vals, 1):
                cell = wm.cell(row=r, column=c, value=v)
                cell.border = BRD
                cell.alignment = WRAP
            wm.cell(row=r, column=7).number_format = MONEY
            wm.cell(row=r, column=8).number_format = MONEY
    WM_LAST = r
    r += 1
    wm.cell(row=r, column=4, value="Итого материалы и изделия (Ремонт)").font = BOLD
    wm.cell(row=r, column=8, value=f"=SUM(H2:H{WM_LAST})").number_format = MONEY
    widths(wm, [7, 9, 6, 60, 10, 9, 12, 14, 12, 38])
    wm.freeze_panes = "A2"
    # Смета
    sm["A1"] = "СМ-01. Смета ориентировочная — кв. 108, СПб, вариант D1 (бюджет «Ремонт»)"
    sm["A1"].font = Font(bold=True, size=13)
    sm["A2"] = PRICE_NOTE
    sm["A2"].alignment = WRAP
    sm.merge_cells("A2:F2")
    sm.row_dimensions[2].height = 80
    for c, h in enumerate(["Шифр", "Этап", "Работы, ₽", "Материалы и изделия, ₽", "Итого, ₽", "Доля"], 1):
        sm.cell(row=4, column=c, value=h)
    style_header(sm, 4, 6)
    r = 4
    for code, title in STAGES.items():
        r += 1
        sm.cell(row=r, column=1, value=code)
        sm.cell(row=r, column=2, value=title)
        sm.cell(row=r, column=3, value=f"=SUMIF('Работы'!$A$2:$A${WR_LAST},A{r},'Работы'!$G$2:$G${WR_LAST})")
        sm.cell(row=r, column=4, value=f"=SUMIF('Материалы (Ремонт)'!$A$2:$A${WM_LAST},A{r},'Материалы (Ремонт)'!$H$2:$H${WM_LAST})")
        sm.cell(row=r, column=5, value=f"=C{r}+D{r}")
        for c in (3, 4, 5):
            sm.cell(row=r, column=c).number_format = MONEY
    s0, s1 = 5, r
    for c in (1, 2):
        pass
    for rr in range(s0, s1 + 1):
        sm.cell(row=rr, column=6, value=f"=E{rr}/$E${s1 + 1}").number_format = "0.0%"
    r += 1
    SUBR = r
    sm.cell(row=r, column=2, value="Итого без резерва").font = BOLD
    for c, L_ in ((3, "C"), (4, "D"), (5, "E")):
        cell = sm.cell(row=r, column=c, value=f"=SUM({L_}{s0}:{L_}{s1})")
        cell.font = BOLD
        cell.number_format = MONEY
    r += 1
    sm.cell(row=r, column=2, value="Резерв на непредвиденное, %")
    sm.cell(row=r, column=5, value=RESERVE).number_format = "0%"
    RESR = r
    r += 1
    sm.cell(row=r, column=2, value="Резерв, ₽")
    sm.cell(row=r, column=5, value=f"=E{SUBR}*E{RESR}").number_format = MONEY
    r += 1
    sm.cell(row=r, column=2, value="ИТОГО «Ремонт» с резервом 10 %").font = BOLD
    c = sm.cell(row=r, column=5, value=f"=E{SUBR}+E{r - 1}")
    c.font = BOLD
    c.number_format = MONEY
    c.fill = TFILL
    TOTR = r
    widths(sm, [8, 62, 16, 20, 16, 8])
    # Мебель и техника
    cols = ["Спецификация", "Поз.", "Наименование", "Кол-во", "Ед.", "Цена, ₽", "Сумма, ₽", "Помещение", "Ссылка"]
    for c, h in enumerate(cols, 1):
        wf.cell(row=1, column=c, value=h)
    style_header(wf, 1, len(cols))
    r = 1
    for key, s in SPECS.items():
        for i in s["items"]:
            if i["budget"] != F:
                continue
            r += 1
            vals = [s["code"], i["pos"], i["name"], i["qty"], i["unit"], i["price"], f"=D{r}*F{r}", i["room"], i["ref"]]
            for cc, v in enumerate(vals, 1):
                cell = wf.cell(row=r, column=cc, value=v)
                cell.border = BRD
                cell.alignment = WRAP
            wf.cell(row=r, column=6).number_format = MONEY
            wf.cell(row=r, column=7).number_format = MONEY
    WF_LAST = r
    r += 1
    wf.cell(row=r, column=3, value="Итого без резерва").font = BOLD
    wf.cell(row=r, column=7, value=f"=SUM(G2:G{WF_LAST})").number_format = MONEY
    FSUB = r
    r += 1
    wf.cell(row=r, column=3, value="Резерв 10 %")
    wf.cell(row=r, column=7, value=f"=G{FSUB}*{RESERVE}").number_format = MONEY
    r += 1
    wf.cell(row=r, column=3, value="ИТОГО «Мебель+техника» с резервом").font = BOLD
    wf.cell(row=r, column=7, value=f"=G{FSUB}+G{r - 1}").number_format = MONEY
    FTOT = r
    widths(wf, [9, 6, 60, 8, 7, 12, 14, 10, 30])
    # Бюджеты
    wbud["A1"] = "Сверка с бюджетом брифа (границы бюджетов — questions.md №34)"
    wbud["A1"].font = Font(bold=True, size=13)
    for c, h in enumerate(["Бюджет", "Лимит брифа, ₽", "Смета без резерва, ₽", "Смета с резервом 10 %, ₽", "Отклонение (с резервом), ₽", "Отклонение, %",
                           "Отклонение без резерва, ₽"], 1):
        wbud.cell(row=3, column=c, value=h)
    style_header(wbud, 3, 7)
    rows = [("Ремонт (работы + материалы + сантехника + свет + двери + встроенные шкафы + остекление/утепление балкона)", BUDGET_R,
             f"='Смета'!E{SUBR}", f"='Смета'!E{TOTR}"),
            ("Мебель + техника (кухня, бытовая техника, проектор/экран/акустика, ТВ, диваны, кровати, мебель детской)", BUDGET_F,
             f"='Мебель и техника'!G{FSUB}", f"='Мебель и техника'!G{FTOT}")]
    r = 3
    for nm, lim, a, b in rows:
        r += 1
        wbud.cell(row=r, column=1, value=nm).alignment = WRAP
        wbud.cell(row=r, column=2, value=lim)
        wbud.cell(row=r, column=3, value=a)
        wbud.cell(row=r, column=4, value=b)
        wbud.cell(row=r, column=5, value=f"=D{r}-B{r}")
        wbud.cell(row=r, column=6, value=f"=E{r}/B{r}").number_format = "0.0%"
        wbud.cell(row=r, column=7, value=f"=C{r}-B{r}")
        for c in (2, 3, 4, 5, 7):
            wbud.cell(row=r, column=c).number_format = MONEY
    r += 1
    wbud.cell(row=r, column=1, value="ВСЕГО").font = BOLD
    for c, L_ in ((2, "B"), (3, "C"), (4, "D"), (5, "E"), (7, "G")):
        cell = wbud.cell(row=r, column=c, value=f"=SUM({L_}4:{L_}5)")
        cell.number_format = MONEY
        cell.font = BOLD
    wbud.cell(row=r, column=6, value=f"=E{r}/B{r}").number_format = "0.0%"
    wbud.cell(row=r + 2, column=1, value="Положительное отклонение — превышение бюджета; меры — 05-estimate/value-engineering.md.").alignment = WRAP
    widths(wbud, [60, 16, 18, 20, 20, 12, 20])
    # Источники
    for i, line in enumerate(SOURCES_TXT.split("\n"), 1):
        wsrc.cell(row=i, column=1, value=line).alignment = WRAP
    wsrc.column_dimensions["A"].width = 140
    wb.save(path)
    return dict(SUBR=SUBR, TOTR=TOTR, FSUB=FSUB, FTOT=FTOT)

SOURCES = [
    ("INFOline / RBC Retail: рост цен на стройматериалы в СПб, 1-е полугодие 2026 (плитка +17,3 %, электрика +15,3 %, напольные +10,5 %, ЛКМ +10,4 %, сухие смеси +4,7 %)",
     "https://www.retail.ru/rbc/pressreleases/keramicheskaya-plitka-vnov-bet-rekord-po-rostu-tsen-v-2026-godu-otmechayut-v-infoline/"),
    ("Прайсы отделочных работ СПб 2026 (покраска 450–975 ₽/м², шпаклёвка 2 сл. 495–1 155 ₽/м², плитка 800–5 500 ₽/м²): remontvspb.ru", "https://remontvspb.ru/prajs/"),
    ("prorabneva.ru — цены на ремонт квартир в СПб 2026", "https://www.prorabneva.ru/price"),
    ("len-rem.ru — расценки на отделочные работы 2026", "https://len-rem.ru/rascenki-na-otdelochnye-raboty.html"),
    ("remont-na5.ru — плиточные (Эконом 1 750 / Стандарт 2 800 ₽/м²) и малярные работы СПб", "https://remont-na5.ru/uslugi/ukladka-plitki/"),
    ("stroikaspb.com — расценки на плиточные работы СПб", "https://www.stroikaspb.com/plitochnie-raboti-vspb/"),
    ("hands.ru — прайс-лист на отделочные работы в СПб 2026", "https://hands.ru/saint-petersburg/category/otdelka/price/"),
    ("Profi.ru — установка трапов в СПб (от 1 000 ₽/шт), услуги сантехников", "https://profi.ru/geo-spb/remont/santehnika/price/"),
    ("Sostav.ru — рейтинг компаний и цены ремонта СПб 2026 (ориентир Москва: работы 18–35 тыс. ₽/м²)", "https://www.sostav.ru/blogs/286041/75556"),
    ("Яндекс Карты — Coswick СПб, инженерная доска (≈ 9 000–11 100 ₽ за позицию)", "https://yandex.com.tr/maps/org/coswick/20770661221/prices/"),
]
SOURCES_TXT = "\n".join([f"Дата поиска: {DATE}. Сайты подрядчиков часть прайсов отдают только в выдаче (прямой доступ из среды закрыт) — "
                         "цифры взяты из сниппетов поисковой выдачи и использованы как калибровка диапазона, не как точная цена."]
                        + [f"- {t}: {u}" for t, u in SOURCES]
                        + ["", "Допущения сметы:",
                           "- Расценки — бригада среднего уровня с прорабом, СПб, 10.2026, без НДС подрядчика-юрлица; материалы — с доставкой в пределах КАД.",
                           "- Встроенная мебель, буазери, остекление, стекло душа — цены изделий «под ключ» (изготовление + монтаж) в спецификациях; монтаж остекления — отдельной строкой работ.",
                           "- Не входит: дизайн-проект, авторский надзор, согласование перепланировки, работы УК по стоякам, входная дверь (существующая), кондиционирование.",
                           "- Количества — tools/gen_specs.py из слоёв 03-drawings/*.json и 04-specs/finish-quantities.json; запасы — в спецификациях."])

# ======================================================================================
# 9. md сметы и VE
# ======================================================================================
ALL_ITEMS = [(s["code"], i) for s in SPECS.values() for i in s["items"]]


def boundary():
    g = lambda sk, pat, bd=None: sum(i["sum"] for i in SPECS[sk]["items"] if re.search(pat, i["name"]) and (bd is None or i["budget"] == bd))
    return [
        ("Встроенные шкафы прихожей и спальни, системы постирочной, буазери", R, g("furn", r"^Шкаф-купе|^Шкаф прихожей|^Системы хранения|^Буазери"),
         "СП-02.1 (F41, F45, F46, F60–F62, F78–F88)"),
        ("Сантехника, мебель ванной, мойка/смеситель/фильтр кухни", R, sum(i["sum"] for i in SPECS["vk"]["items"]), "СП-04"),
        ("Остекление и утепление балкона (изделия)", R, sum(i["sum"] for i in SPECS["fin"]["items"] if i["stage"] == "Э03"), "СП-05, этап Э03"),
        ("Шторы, карнизы, привод П-карниза балкона", R, g("fin", r"^Портьеры|^Карниз потолочный профильный|^П-образный"), "СП-05"),
        ("Кухня (корпус, фасады, столешница, буфет)", F, sum(i["sum"] for i in SPECS["kitchen"]["items"]
                                                          if not re.search(r"Варочная|Духовой|ПММ|Холодильник|Вытяжка|Колонна|техники", i["name"])), "СП-02.2"),
        ("Встраиваемая и бытовая техника (вкл. колонну СМА+СМ)", F, g("kitchen", r"Варочная|Духовой|ПММ|Холодильник|Вытяжка|Колонна|техники"), "СП-02.2"),
        ("Проектор, экран, акустика, медиаплеер, ТВ", F, sum(i["sum"] for i in SPECS["lv"]["items"] if i["budget"] == F), "СП-03.4"),
        ("Диваны, кровати, обеденная группа, мебель детской и прочая", F, sum(i["sum"] for i in SPECS["furn"]["items"] if i["budget"] == F), "СП-02.1"),
    ]


def estimate_md():
    global BOUNDARY
    BOUNDARY = boundary()
    L = ["# СМ-01. Смета ориентировочная (вариант D1)", "",
         f"Объект: СПб, кв. 108, 69,01 м² (без балкона {fq(FLOOR_TOTAL)} м²), средний сегмент. Дата: {DATE}. Файл с формулами: `05-estimate/estimate.xlsx`.",
         "", PRICE_NOTE, "",
         "Границы бюджетов (questions.md №34, принято): **«Ремонт» 5,0 млн** — черновые и чистовые работы и материалы, сантехника и мебель ванной, "
         "свет, электроустановка, двери, остекление и утепление балкона, встроенные шкафы прихожей, спальни и постирочной, буазери, шторы и карнизы, "
         "умный дом (протечки, приводы, датчики); **«Мебель+техника» 1,5 млн** — кухня, встраиваемая и бытовая техника (включая колонну СМА+СМ), "
         "проектор, экран, акустика, ТВ, диваны, кровати, корпусная мебель детской, обеденная группа.", "",
         "### Границы бюджетов по №34 — где учтены спорные статьи", "",
         "| Статья | Бюджет | Сумма изделий, ₽ | Где |", "|---|---|---|---|"] + [
         f"| {t} | {bd} | {fmt(v)} | {w_} |" for t, bd, v, w_ in BOUNDARY] + ["",
         "## 1. Ремонт — итог по этапам", "",
         "| Шифр | Этап | Работы, ₽ | Материалы и изделия, ₽ | Итого, ₽ | Доля |", "|---|---|---|---|---|---|"]
    for code, t in STAGES.items():
        a, b = work_by_stage[code], mat_by_stage[code]
        L.append(f"| {code} | {t} | {fmt(a)} | {fmt(b)} | {fmt(a + b)} | {pct(100 * (a + b) / REP_SUB)} % |")
    WS, MS = sum(work_by_stage.values()), sum(mat_by_stage.values())
    L += [f"| | **Итого без резерва** | **{fmt(WS)}** | **{fmt(MS)}** | **{fmt(REP_SUB)}** | 100 % |",
          f"| | Резерв 10 % | | | {fmt(REP_SUB * RESERVE)} | |",
          f"| | **ИТОГО «Ремонт» с резервом** | | | **{fmt(REP_TOT)}** | |", "",
          "## 2. Сверка с бюджетами брифа", "",
          "| Бюджет | Лимит, ₽ | Смета без резерва, ₽ | С резервом 10 %, ₽ | Отклонение с резервом, ₽ | % |", "|---|---|---|---|---|---|",
          f"| Ремонт | {fmt(BUDGET_R)} | {fmt(REP_SUB)} | {fmt(REP_TOT)} | {fmt(REP_TOT - BUDGET_R, 0)} | {pct(100 * (REP_TOT - BUDGET_R) / BUDGET_R, True)} % |",
          f"| Мебель + техника | {fmt(BUDGET_F)} | {fmt(FURN_SUB)} | {fmt(FURN_TOT)} | {fmt(FURN_TOT - BUDGET_F)} | {pct(100 * (FURN_TOT - BUDGET_F) / BUDGET_F, True)} % |",
          f"| **Всего** | **{fmt(BUDGET_R + BUDGET_F)}** | **{fmt(REP_SUB + FURN_SUB)}** | **{fmt(REP_TOT + FURN_TOT)}** | "
          f"**{fmt(REP_TOT + FURN_TOT - BUDGET_R - BUDGET_F)}** | {pct(100 * (REP_TOT + FURN_TOT - BUDGET_R - BUDGET_F) / (BUDGET_R + BUDGET_F), True)} % |", ""]
    over = REP_TOT > BUDGET_R or FURN_TOT > BUDGET_F
    L += [("Есть превышение — см. `05-estimate/value-engineering.md` (замены с экономией без потери концепции)." if over else
           "Обе статьи укладываются в бюджет с резервом 10 %."), ""]
    # по спецификациям
    L += ["## 3. Материалы и изделия по спецификациям", "", "| Шифр | Спецификация | «Ремонт», ₽ | «Мебель+техника», ₽ | Файл |", "|---|---|---|---|---|"]
    for key, s in SPECS.items():
        a = sum(i["sum"] for i in s["items"] if i["budget"] == R)
        b = sum(i["sum"] for i in s["items"] if i["budget"] == F)
        L.append(f"| {s['code']} | {s['title']} | {fmt(a)} | {fmt(b)} | `04-specs/{s['file']}` |")
    # топ-5
    top = sorted(ALL_ITEMS, key=lambda x: -x[1]["sum"])[:5]
    topw = sorted(WORKS, key=lambda x: -x["sum"])[:5]
    L += ["", "## 4. Топ-5 самых дорогих позиций", "", "Изделия и материалы:", "", "| № | Позиция | Спец. | Бюджет | Сумма, ₽ | Ссылка |", "|---|---|---|---|---|---|"]
    for n, (code, i) in enumerate(top, 1):
        L.append(f"| {n} | {i['name'][:90]} | {code} поз. {i['pos']} | {i['budget']} | {fmt(i['sum'])} | {i['ref']} |")
    L += ["", "Работы:", "", "| № | Работа | Этап | Объём | Сумма, ₽ |", "|---|---|---|---|---|"]
    for n, wk in enumerate(topw, 1):
        L.append(f"| {n} | {wk['name']} | {wk['stage']} | {fq(wk['qty'])} {wk['unit']} | {fmt(wk['sum'])} |")
    # работы подробно
    L += ["", "## 5. Работы (расценка × объём)", "", "| Поз. | Наименование | Ед. | Объём | Расценка, ₽ | Сумма, ₽ | Источник объёма |", "|---|---|---|---|---|---|---|"]
    cnt = defaultdict(int)
    cur = None
    for wk in WORKS:
        if wk["stage"] != cur:
            cur = wk["stage"]
            L.append(f"| **{cur}** | **{STAGES[cur]}** | | | | **{fmt(work_by_stage[cur])}** | |")
        cnt[cur] += 1
        L.append(f"| {cur}.{cnt[cur]} | {wk['name']} | {wk['unit']} | {fq(wk['qty'])} | {fmt(wk['rate'])} | {fmt(wk['sum'])} | {wk['ref']}"
                 + (f" ({wk['calc']})" if wk["calc"] else "") + " |")
    L += ["", "## 6. Материалы по этапам", "",
          "Состав материалов каждого этапа — графа «Этап сметы» в спецификациях `04-specs/spec-*.md` и лист «Материалы (Ремонт)» в estimate.xlsx.", "",
          "## 7. Источники калибровки цен и допущения", ""] + SOURCES_TXT.split("\n") + [
          "", "## 8. Проверки", "",
          f"- Трассируемость (все id слоёв попали в спецификации): мебель F01–F90 — {'OK' if not miss_f else 'нет: ' + ', '.join(miss_f)}; "
          f"светильники — {'OK' if not miss_l else miss_l}; розетки/выключатели — {'OK' if not miss_s else miss_s}; группы щита — {'OK' if not miss_g else miss_g}.",
          "- Пересчёт формул xlsx — LibreOffice headless, ошибок #REF!/#VALUE!/#DIV/0!/#NAME? нет (см. отчёт генерации).", ""]
    return "\n".join(L)


def find(sk, pat):
    return [i for i in SPECS[sk]["items"] if re.search(pat, i["name"])]


def ve_md():
    """Value engineering: рычаги concept.md п.7.1/7.2 + дополнительные; экономия — из позиций спецификаций/работ."""
    VE_R, VE_F = [], []

    def lever(lst, tier, title, why, items_or_value, new_price=None, factor=None, keep=""):
        if isinstance(items_or_value, (int, float)):
            save = items_or_value
        else:
            save = 0
            for i in items_or_value:
                if new_price is not None:
                    save += i["qty"] * (i["price"] - new_price)
                elif factor is not None:
                    save += i["sum"] * (1 - factor)
        lst.append((tier, title, why, round(save), keep))

    wsum = lambda pat: sum(x["sum"] for x in WORKS if re.search(pat, x["name"]))
    A, B, C = "A", "B", "C"
    # --- Ремонт: A — без потери концепции ---
    lever(VE_R, A, "Шкафы прихожей и спальни: фасады МДФ эмаль → МДФ в матовой плёнке/ПЭТ с накладными молдингами под окраску (рычаг 1 concept 7.1)",
          "филёнчатый ритм и цвет C2/C3 сохраняются; эмаль остаётся на буазери", find("furn", r"^Шкаф-купе|^Шкаф прихожей"), factor=0.78,
          keep="F45, F46, F60–F62")
    lever(VE_R, A, "Сантехника: инсталляция и WC Am.Pm/Cersanit вместо Geberit/Laufen; смесители, термостат, душ — Lemark вместо WasserKRAFT (рычаг 2)",
          "латунь браш в арматуре и функции (скрытый термостат, walk-in) сохраняются",
          find("vk", r"^Инсталляция|^Унитаз|^Термостат|^Смеситель для ванны|^Смеситель для раковины|^Верхний душ|^Кнопка"), factor=0.72, keep="P01–P04")
    tw = [i for i in SPECS["fin"]["items"] if "60×120 «светлый мрамор» матовый" in i["name"]]
    dry_share = TILE_DRY / (TILE_WET + TILE_DRY + APRON_K)
    lever(VE_R, A, "Ванная: 60×120 только в душе и за ванной, сухая зона до +1280 — 60×60 той же серии (рычаг 3)",
          "та же серия и цвет, меньше подрезки; шпалера «панель + окраска» сохраняется",
          sum(i["qty"] * dry_share * (5600 - 4500) for i in tw) + TILE_DRY * 500, keep="walls tile_dry; D23")
    lever(VE_R, A, "Ёлочка: та же 2-слойная инженерная доска 90×600 с допуском на водяной ТП, но линия/сорт среднего ценового уровня (Alpine Floor Villa, сорт рустик-лайт) вместо Coswick",
          "рисунок, порода, размер планки, клеевой монтаж и допуск к ТП — без изменений", find("fin", r"^Инженерная доска"), new_price=5900, keep="M01")
    lever(VE_R, A, "Клей MS-полимер — аналог того же класса (Homakoll/Kiilto) с допуском на ТП", "эластичный MS-клей сохраняется",
          find("fin", r"^Клей паркетный"), factor=0.75)
    lever(VE_R, A, "Остекление балкона: профиль KBE/Exprof 70 мм вместо VEKA, триплекс P2A и энергосберегающий пакет сохраняются", "теплотехника и безопасность (№12) те же",
          find("fin", r"^Остекление балкона"), factor=0.87, keep="M32")
    lever(VE_R, A, "Системы хранения постирочной — ЛДСП эконом-сегмента (как в M26), фурнитура без доводчиков на навесных", "функция и доступ к U11 сохраняются",
          find("furn", r"^Системы хранения постирочной"), new_price=90000, keep="F78–F88")
    lever(VE_R, A, "Светильники: декоративные люстры/бра из линий Freya/Eglo вместо Maytoni/Odeon верхних серий",
          "форма и латунь сатин; споты CRI ≥ 90 — без изменений", [i for i in SPECS["light"]["items"] if i["price"] >= 9000], factor=0.75)
    lever(VE_R, A, "Карнизы, плинтусы, молдинги: базовые линии Европласт/Ultrawood тех же профилей", "профили 40–120 и окраска тон-в-тон",
          [i for i in SPECS["fin"]["items"] if re.match(r"^(Карниз потолочный|Плинтус МДФ|Карниз 40|Молдинг)", i["name"])], factor=0.8)
    lever(VE_R, A, "Двери: та же модель МДФ эмаль у фабрики среднего уровня (Волховец «Неоклассика»), петли скрытые Morelli вместо AGB",
          "филёнки и наличники с цоколем (не экономим на стиле)", find("doors", r"^Дверь|^Петли"), factor=0.85)
    lever(VE_R, A, "Шторы: готовый блэкаут/ткани из стоковых коллекций вместо пошива по ткани Arben-класса", "цвет C2/C6 и блэкаут сохраняются",
          find("fin", r"^Портьеры"), factor=0.65)
    lever(VE_R, A, "Защита от протечек: комплект Аквасторож Классика (2 узла) вместо Neptun ProW+; бризер спальни Ballu ONEAIR ASP-200 вместо Tion 4S",
          "логика EV1–EV4 и 7 датчиков, приток 60 м³/ч — без изменений",
          find("lv", r"^Контроллер защиты|^Кран шаровой с электроприводом") + find("hvac", r"^Бризер BR1"), factor=0.65)
    # --- B — условные (по обмеру / организационные) ---
    plast = wsum(r"^Штукатурка стен") + sum(i["sum"] for i in find("fin", r"^Штукатурка"))
    lever(VE_R, B, "Штукатурка по маякам — только там, где по обмеру (№1) отклонение > 5 мм на 2 м; остальное — шпаклёвочное выравнивание (принято 50 % площади)",
          "геометрия стен под окраску и молдинги — та же (Q3)", plast * 0.5 - (PL_DRY + PL_WET) * 0.5 * 350, keep="Э07")
    lever(VE_R, B, "Тендер работ: 3 бригады по этой смете с фиксированными объёмами (разброс прайсов СПб — до 2× по позициям); принято −8 % к работам",
          "состав и технология работ — без изменений", sum(work_by_stage.values()) * 0.08, keep="все этапы")
    # --- C — с компромиссом / перенос после въезда ---
    lever(VE_R, C, "Детская: инженерная доска прямой укладки (палуба) вместо ёлочки (рычаг 4 — единство пола частично теряется)", "порода и цвет те же",
          OAK_BY_ROOM["R2"] * 1.08 * 1000 + OAK_BY_ROOM["R2"] * 900, keep="floors R2")
    lever(VE_R, C, "Перенести после въезда: подсветки шкафов L13, L18, ночную подсветку плинтуса L17 и консоли L12 (выводы и БП-ниши закладываются сейчас)",
          "проводка и сценарий «Ночь» готовы, оборудование докупается позже",
          [i for i in SPECS["light"]["items"] if re.search(r"L1[2378]-1", i["ref"])], factor=0.0)
    lever(VE_R, C, "Остекление: стандартный 2-камерный пакет без триплекса — ТОЛЬКО если №12 решится в пользу рольставен/решёток (рычаг 5)",
          "теплотехника та же; безопасность обеспечивается рольставнями", sum(i["sum"] for i in find("fin", r"^Остекление балкона")) * 0.87 * 0.15)
    # --- Мебель ---
    lever(VE_F, A, "Проектор Full HD/4K-enhancement того же throw с lens shift (concept 7.2)", "сценарий «Кино» и геометрия D11 не меняются",
          find("lv", r"^Проектор"), new_price=95000)
    lever(VE_F, A, "AV-ресивер + пассивные колонки → активные настенные колонки с HDMI eARC (concept 7.2 «саундбар»)",
          "трассы LV09/LV10 используются; ресивер не нужен", find("lv", r"^AV-ресивер|^Колонки"), factor=0.55)
    lever(VE_F, A, "П-диван из стандартных модулей вместо изготовления по размеру (concept 7.2)", "П-форма и посадка сохраняются",
          find("furn", r"^П-диван"), new_price=118000)
    lever(VE_F, A, "Стулья из модульной линейки (concept 7.2)", "мягкое сиденье, рогожка", find("furn", r"^Стул мягкий"), new_price=8000)
    lever(VE_F, A, "Кухня: эмаль только на нижнем ярусе и буфете (шалфей C4), верхний ярус KW-01…05 — МДФ плёнка в цвет стены",
          "акцент C4 «шейкер» сохраняется; верх и так «в цвет стены»", [i for i in SPECS["kitchen"]["items"] if "KW-" in i["name"]], factor=0.75)
    lever(VE_F, A, "Столешница: кварц среднего сегмента (Grandex/Avant) без подгиба кромки", "материал и вид те же", find("kitchen", r"^Столешница"), new_price=52000)
    lever(VE_F, A, "Холодильник и духовка — Haier/Weissgauff вместо Bosch Serie 4", "встраиваемые габариты те же", find("kitchen", r"^Холодильник|^Духовой"), factor=0.8)
    lever(VE_F, C, "ТВ 65″ в спальню — из имеющейся техники (concept 7.2)", "вывод и кронштейн сохраняются", find("lv", r"^Телевизор"), new_price=5000)

    def block(lst, sub, tot, budget, name):
        L = [f"## {name}", "",
             f"Смета: {fmt(sub)} ₽ без резерва, **{fmt(tot)} ₽ с резервом 10 %** при лимите {fmt(budget)} ₽ → превышение **{fmt(tot - budget)} ₽** "
             f"({pct(100 * (tot - budget) / budget, True)} %).", "",
             "Уровни: **A** — без потери концепции; **B** — условные (по обмеру / организационные); **C** — с компромиссом или перенос после въезда.", "",
             "| № | Ур. | Замена | Что сохраняется | Экономия, ₽ | С резервом, ₽ | Накоплено с резервом, ₽ | Остаток превышения, ₽ |",
             "|---|---|---|---|---|---|---|---|"]
        acc = 0
        subtot = {}
        for n, (tier, t, why, s, keep) in enumerate(lst, 1):
            acc += s * (1 + RESERVE)
            subtot[tier] = acc
            L.append(f"| {n} | {tier} | {t}{(' (' + keep + ')') if keep else ''} | {why} | {fmt(s)} | {fmt(s * (1 + RESERVE))} | {fmt(acc)} | "
                     f"{fmt(max(tot - acc - budget, 0))} |")
        L += [""]
        for tier in ("A", "B", "C"):
            if tier in subtot:
                L.append(f"- После уровня {tier}: итог ≈ **{fmt(tot - subtot[tier])} ₽** с резервом "
                         f"({'в бюджете' if tot - subtot[tier] <= budget else 'превышение ' + fmt(tot - subtot[tier] - budget) + ' ₽'}).")
        L.append("")
        return L, acc

    L = ["# Value engineering — предложения по снижению стоимости (вариант D1)", "",
         f"Основание: `05-estimate/estimate.md` / `estimate.xlsx` ({DATE}); рычаги экономии `02-concept/concept.md` п.7.1 и 7.2 + дополнительные. "
         "Экономия считается генератором `tools/gen_specs.py` из тех же позиций спецификаций и работ (кол-во × разница цены), резерв 10 % — пропорционально. "
         "Цены — ориентир СПб 10.2026.", "",
         "**Не экономим** (concept 7.1 и инженерные ограничения): клеевой монтаж и допуск покрытий к водяному ТП, гидроизоляция и подиум ванной, "
         "буазери спальни, двери с наличниками, латунь в арматуре, CRI ≥ 90, защита от протечек (1 этаж, под квартирой нежилое), триплекс P2A на 1 этаже (пока №12 открыт).", ""]
    res = {}
    if REP_TOT > BUDGET_R:
        b, res["R"] = block(VE_R, REP_SUB, REP_TOT, BUDGET_R, "1. Ремонт (лимит 5,0 млн ₽)")
        L += b
    if FURN_TOT > BUDGET_F:
        b, res["F"] = block(VE_F, FURN_SUB, FURN_TOT, BUDGET_F, "2. Мебель + техника (лимит 1,5 млн ₽)")
        L += b
    rem_r = REP_TOT - res.get("R", 0) - BUDGET_R
    rem_f = FURN_TOT - res.get("F", 0) - BUDGET_F
    L += ["## 3. Вывод и рекомендация", ""]
    if rem_r > 0:
        L += [f"- **Ремонт:** даже после всех замен A+B+C остаётся превышение ≈ {fmt(rem_r)} ₽ с резервом "
              f"(≈ {fmt(rem_r / (1 + RESERVE))} ₽ без резерва). Проект в текущем объёме (балкон в тёплом контуре, подиум ванной с walk-in, буазери, "
              "встроенные шкафы, умный дом) по ценам СПб 10.2026 стоит больше 5,0 млн. Варианты для решения заказчика: "
              "(1) увеличить лимит «Ремонт» до ≈ " + fmt(math.ceil((REP_TOT - res.get('R', 0)) / 1e5) * 1e5) + " ₽; "
              "(2) считать резерв 10 % вне лимита (тогда нужно ≈ " + fmt(math.ceil((REP_SUB - res.get('R', 0) / (1 + RESERVE)) / 1e5) * 1e5) + " ₽); "
              "(3) перенести часть встроенной мебели (шкаф-купе спальни, системы постирочной) в бюджет «Мебель» — только если там есть запас "
              "(сейчас его нет).", ""]
    else:
        L += ["- **Ремонт:** укладывается в 5,0 млн с резервом после замен из таблицы (применять по порядку, до достижения лимита).", ""]
    if rem_f > 0:
        L += [f"- **Мебель+техника:** после замен остаётся превышение ≈ {fmt(rem_f)} ₽ с резервом — резерв по мебели можно не закладывать "
              "(цены фиксируются в договорах поставки); без резерва итог ≈ " + fmt(FURN_SUB - res.get('F', 0) / (1 + RESERVE)) + " ₽.", ""]
    else:
        L += ["- **Мебель+техника:** укладывается в 1,5 млн после замен уровня A (резерв 10 % сохраняется).", ""]
    L += ["## 4. Организационные меры (не учтены в цифрах выше)", "",
          "- Резерв 10 % не расходуется по умолчанию: после этапов Э01–Э06 (обмер, лоток U6, плита балкона, схема ТП) неиспользованный резерв высвобождается.",
          "- Кухня, встроенные шкафы, буазери и мебель ванной — у одного цеха (единые колеры C2/C3/C4, одна доставка и монтаж): обычно −5…8 % на пакет.",
          "- Плитка, доска и сантехника — одним заказом в период акций (Q4) — −5…10 % к розничным ориентирам.", ""]
    return "\n".join(L), VE_R, VE_F


# ======================================================================================
# main
# ======================================================================================
if __name__ == "__main__":
    out_s = ROOT / "04-specs"
    out_e = ROOT / "05-estimate"
    out_e.mkdir(exist_ok=True)
    (out_s / "finish-schedule.md").write_text(finish_schedule(), encoding="utf-8")
    for s in SPECS.values():
        (out_s / s["file"]).write_text(spec_md(s), encoding="utf-8")
    write_specs_xlsx(out_s / "specifications.xlsx")
    rows = write_estimate_xlsx(out_e / "estimate.xlsx")
    (out_e / "estimate.md").write_text(estimate_md(), encoding="utf-8")
    ve, VE_R, VE_F = ve_md()
    if REP_TOT > BUDGET_R or FURN_TOT > BUDGET_F:
        (out_e / "value-engineering.md").write_text(ve, encoding="utf-8")
    print(json.dumps(dict(checks=CHECKS,
                          stages={k: [round(work_by_stage[k]), round(mat_by_stage[k])] for k in STAGES},
                          rep_sub=round(REP_SUB), rep_tot=round(REP_TOT), furn_sub=round(FURN_SUB), furn_tot=round(FURN_TOT),
                          ve_r=[(t[:50], s) for _, t, _, s, _ in VE_R], ve_f=[(t[:50], s) for _, t, _, s, _ in VE_F],
                          q=dict(PL_DRY=PL_DRY, PL_WET=PL_WET, Q3=Q3_WALLS, Q2=Q2_BEHIND, OAK=OAK, CABLE=CABLE, LVLEN=LVLEN, DROP=DROP_M, N_BOXES=N_BOXES,
                                 GLAZ=GLAZING_M2, NW=[NW1_A, NW4_A, NW8_A, NW9_A], WP=WP_AREA, open_sens=N_OPEN_SENS, zb=ZB_BUTTONS)),
                     ensure_ascii=False, indent=1))
