#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Magnitek supplemental feed builder — сварочное оборудование (OpenCart, ru-ru).

Чинит/добавляет по g:id (валюту НЕ трогаем — UAH ок):
  - google_product_category  (two-anchor: тип детали ловится раньше кода аппарата)
  - product_type             (Сварка > Аппараты/Расходники/Защита/Газовое > подтип)
  - title                    чистка + латинизация процессов + нормализация + убрать хвостовой артикул
  - description              генератор паспорта для ~20% огрызков; rich-описания только чистим
  - brand=MAGNITEK + identifier_exists=no всем (тег физически отсутствует в фиде)
  - custom_label_0 тип / _1 ценовой тир / _2 процесс / _3 совместимость-кластер

Бренд MAGNITEK собственный → чужой ТМ нет; совместимость (WP-17/РТ31/ER5356) в title легитимна.
"""
import html, re, os, csv, sys, urllib.request
import xml.etree.ElementTree as ET

FEED_URL = "https://magnitek.ua/index.php?route=extension/feed/remarketing_feed&language=ru-ru"
NS = {"g": "http://base.google.com/ns/1.0"}
OUT_CSV = os.path.join("docs", "magnitek-supplemental.csv")
MIN_ITEMS = 550   # стабильно 613; ниже = обрезанный фид, не публикуем

# ── Категоризация (two-anchor, порядок сверху вниз; первое совпадение побеждает) ──
MASK_M = ["хамелеон", "маска сварщ", "маска зварюв", "сварочная маска", "зварювальна маска",
          "щиток сварщ", "щиток зварюв", "светофильтр", "світлофільтр", "автозатемн",
          "очки-хамелеон", "окуляри-хамелеон"]
EYE_M = ["очки защитн", "очки прозрачн", "окуляри захисн", "окуляри прозор", "защитные очки"]
# тип-детали расходника — ловим РАНЬШЕ аппаратов, чтобы «сопло Р80» не ушло в 1238 по «Р80»
ACC_M = ["сопло", "наконечник", "цанга", "корпус цанги", "газовая линза", "газовий лінз",
         "диффузор", "дифузор", "изолятор", "ізолятор", "завихритель",
         "электрод вольфрам", "електрод вольфрам", "вольфрамовый электрод", "вольфрамовий електрод",
         "wt-20", "wc-20", "wl-15", "wp-17", "wp-18", "wp-26", "54n", "10n", "13n",
         "пруток", "присадочн", "присадков", "проволока", "дріт", "er5356", "er4043", "almg5", "амг5",
         "ролик подающ", "ролик подаюч", "редуктор", "ротаметр", "держатель электрода", "тримач електрода",
         "спираль направля", "спіраль направля", "сменн", "змінн", "запчаст",
         "евроразъем", "евроразьем", "євророз", "заточк",
         "для wp", "для р80", "для р-80", "для рт31", "для а101", "для а141",
         "сопло р80", "электрод р80", "сопло рт31", "наконечник мв", "штекер", "переходник", "гнездо",
         "наконечник e", "нипель", "ниппель", "вентилятор", "крепление для"]
# аппараты и инструмент в сборе
APP_M = ["аппарат", "апарат", "инвертор", "інвертор", "полуавтомат", "напівавтомат",
         "выпрямитель", "випрямляч", "плазморез", "плазморіз", "плазмотрон",
         "спотер", "споттер", "горелка", "пальник", "резак", "різак",
         "mig-", "mag pro", "mma-", "tig/mma", "cut40", "cut-40", "ct-", "zx7", "головка"]

# ── Тип товара (custom_label_0) — дробим мельче, чем gpc ──
def detect_type(t):
    if any(m in t for m in MASK_M) or any(m in t for m in EYE_M) or "спрей" in t or "паста антиприг" in t:
        return "zaschita"
    if t.startswith(("пруток", "проволока", "присадочн", "присадков")):
        return "material"
    if t.startswith(ACC_FIRST):
        return "rashodnik"                                   # деталь первым словом
    if t.startswith(("горелка", "пальник")) or "плазмотрон" in t or "резак" in t or "різак" in t:
        return "gorelka"
    if any(m in t for m in EQUIP_M):
        return "apparat"                                     # оборудование (вкл. блоки/пуско-зарядн/машины)
    if any(m in t for m in ["редуктор", "ротаметр", "переходник", "штекер", "гнездо", "держатель",
                            "вентилятор", "нипель", "ниппель", "крепление", "спираль", "спіраль"]):
        return "aksessuar"
    if any(m in t for m in ["пруток", "проволока", "дріт", "er5356", "er4043"]):
        return "material"
    return "rashodnik"   # дефолт (сопло/наконечник/цанга/электрод где угодно)

TYPE_GPC = {"zaschita": None, "apparat": "1238", "gorelka": "1238",
            "rashodnik": "499947", "material": "499947", "aksessuar": "499947"}


# тип-детали ПЕРВЫМ словом = расходник (сопло Р80 → 499947, а не 1238 по «Р80»)
ACC_FIRST = ("сопло", "наконечник", "цанга", "корпус", "электрод", "електрод", "вольфрам",
             "пруток", "проволока", "присадочн", "присадков", "ролик", "редуктор", "ротаметр",
             "диффузор", "дифузор", "изолятор", "ізолятор", "газовая линза", "газовий лінз",
             "держатель", "тримач", "нипель", "ниппель", "спираль", "спіраль", "штекер",
             "переходник", "гнездо", "крепление", "ремкомплект", "завихритель", "наконечник")
# оборудование в сборе → 1238 (даже если содержит «евроразьем»/«вольфрам» как часть описания)
EQUIP_M = ("аппарат", "апарат", "инвертор", "інвертор", "полуавтомат", "напівавтомат",
           "выпрямитель", "випрямляч", "плазморез", "плазморіз", "плазмотрон",
           "спотер", "споттер", "горелка", "пальник", "резак", "різак", "аргонодугов",
           "блок охлажд", "блок жидкостн", "блок жидкостно", "пуско-зарядн", "пускозарядн",
           "машина для", "пистолет для", "мост для рихтов", "пуллер", "головка")


def detect_gpc(t):
    if any(m in t for m in MASK_M): return "499927"
    if any(m in t for m in EYE_M): return "2227"
    if t.startswith(ACC_FIRST): return "499947"      # деталь первым словом = расходник
    if any(m in t for m in EQUIP_M): return "1238"   # оборудование в сборе (горелка/блок/аппарат)
    if any(m in t for m in ACC_M): return "499947"   # тип-детали где угодно
    return "499947"


PTYPE_SUB = {  # подтип product_type по маркерам
    "плазмор": "Плазморезы CUT", "cut40": "Плазморезы CUT", "cut-40": "Плазморезы CUT",
    "полуавтомат": "Полуавтоматы MIG", "напівавтомат": "Полуавтоматы MIG", "mig-": "Полуавтоматы MIG",
    "tig/mma": "Аргон TIG", "аргонодугов": "Аргон TIG",
    "инвертор": "Инверторы MMA", "mma-": "Инверторы MMA", "zx7": "Инверторы MMA",
    "спотер": "Споттеры", "споттер": "Споттеры",
    "горелка": "Горелки", "пальник": "Горелки", "плазмотрон": "Плазмотроны", "резак": "Резаки",
    "сопло": "Сопла и наконечники", "наконечник": "Сопла и наконечники", "цанга": "Цанги",
    "электрод вольфрам": "Вольфрам TIG", "вольфрамовый электрод": "Вольфрам TIG",
    "пруток": "Присадочный пруток", "присадочн": "Присадочный пруток", "проволока": "Сварочная проволока",
    "редуктор": "Редукторы", "ротаметр": "Редукторы",
    "хамелеон": "Маски", "маска": "Маски", "очки": "Очки",
}
TYPE_BRANCH = {"apparat": "Аппараты", "gorelka": "Аппараты", "rashodnik": "Расходники",
               "material": "Расходники", "aksessuar": "Газовое оборудование", "zaschita": "Защита"}

# ── Совместимость-кластер (custom_label_3) ──
COMPAT = [("wp_tig", ["wp-17", "wp-18", "wp-26", "wp17", "wp18", "wp26"]),
          ("r80_plazma", ["р80", "р-80", "рт31", "р31"]),
          ("a141_plazma", ["а141", "а101", "a141", "a101"]),
          ("mb15_evro", ["мв15", "мв17", "mb15", "mb25", "евроразъем", "евроразьем"]),
          ("mig_provoloka", ["er5356", "er4043", "ролик подающ", "проволока"])]

# процессы (custom_label_2)
def detect_process(t):
    if "плазмор" in t or "cut" in t: return "CUT-plasma"
    if "tig" in t or "аргон" in t or "вольфрам" in t: return "TIG-argon"
    if "mig" in t or "mag" in t or "полуавтомат" in t: return "MIG-MAG"
    if "mma" in t or "мма" in t or "инвертор" in t: return "MMA-arc"
    if "спотер" in t or "споттер" in t: return "spotter"
    return "consumable"

PRICE_TIERS = [(500, "low"), (5000, "mid"), (30000, "high")]
def price_tier(p):
    for lim, name in PRICE_TIERS:
        if p < lim: return name
    return "premium"


def clean(text):
    if not text:
        return ""
    t = html.unescape(html.unescape(text))           # двойное экранирование &amp;quot; -> "
    t = t.replace("\xa0", " ").replace("​", " ")
    t = t.replace('"', "").replace("«", "").replace("»", "")   # кавычки прочь («мама» -> мама, слово остаётся)
    return re.sub(r"\s+", " ", t).strip()


def normalize_tech(t):
    """Латинизация процессов + нормализация размеров."""
    for a, b in [("ММА", "MMA"), ("МИГ", "MIG"), ("МАГ", "MAG"), ("ТИГ", "TIG")]:
        t = t.replace(a, b)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)             # 4,0 -> 4.0
    t = re.sub(r"(\d)\s*[хx]\s*(\d)", r"\1×\2", t)     # 1.6х1м -> 1.6×1м
    t = re.sub(r"\s+", " ", t).strip()
    return t


def strip_artikul(t):
    """Убрать хвостовой артикул (СT.220520 / ARC.50880 / MZV.220) — с точкой, в конце."""
    return re.sub(r"[,;\s]*[A-ZА-Яa-zа-я]{2,5}\.\s*\d{3,}\S*\s*$", "", t).strip(" ,;")


def notes_join(parts):
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return ", ".join(parts[:-1]) + " и " + parts[-1]


def build_rows(xml_bytes):
    root = ET.fromstring(xml_bytes)
    rows = []
    for item in root.iter("item"):
        gid = (item.findtext("g:id", default="", namespaces=NS) or "").strip()
        raw_title = clean(item.findtext("g:title", default="", namespaces=NS))
        raw_desc = clean(item.findtext("g:description", default="", namespaces=NS))
        price_raw = item.findtext("g:price", default="", namespaces=NS) or ""
        if not gid or not raw_title:
            continue

        low = raw_title.lower()
        gpc = detect_gpc(low)
        typ = detect_type(low)
        proc = detect_process(low)
        price_num = float((re.search(r"([\d.]+)", price_raw.replace(",", ".")) or ["", "0"])[1] or 0)

        # ── TITLE: чистка + латинизация + нормализация + убрать хвостовой артикул ──
        title = strip_artikul(normalize_tech(raw_title))[:150]

        # ── product_type ──
        branch = TYPE_BRANCH.get(typ, "Расходники")
        sub = ""
        for k, v in PTYPE_SUB.items():
            if k in low:
                sub = v; break
        ptype = f"Сварка > {branch}" + (f" > {sub}" if sub else "")

        # ── DESCRIPTION: rich (>=120) только чистим; огрызки генерируем паспорт ──
        if len(raw_desc) >= 120 and raw_desc.lower() != raw_title.lower():
            desc = normalize_tech(raw_desc)
        else:
            volt = (re.search(r"(220|380|220/380|380/220)\s*[ВVв]", raw_title) or ["", ""])[0]
            amp = (re.search(r"(\d{2,3})\s*[АA]\b", raw_title) or ["", ""])[0]
            procs = ", ".join(re.findall(r"\b(CUT|TIG|MMA|MIG|MAG|ARC)\b", title.upper())) or ""
            if typ in ("apparat", "gorelka"):
                bits = [f"{title}."]
                if procs: bits.append(f"Процессы: {procs}.")
                if amp: bits.append(f"Максимальный ток: {amp}.")
                if volt: bits.append(f"Питание: {volt}.")
                bits.append("Применение: монтажные, ремонтные и производственные сварочные работы.")
                desc = " ".join(bits)
            else:
                compat = re.findall(r"(WP-\d+|Р-?\d+|РТ\d+|А\d{3}|ER\d{4}|WT-\d+|MB\d+|МВ\d+)", title, re.I)
                bits = [f"{title}."]
                if compat:
                    bits.append("Совместимость: " + notes_join(list(dict.fromkeys(compat))) + ".")
                bits.append("Расходный элемент для сварочного оборудования, заменяемая часть.")
                desc = " ".join(bits)
        desc = re.sub(r"\s+", " ", desc).strip()

        # ── custom_label_3 совместимость ──
        cl3 = ""
        for name, ms in COMPAT:
            if any(m in low for m in ms):
                cl3 = name; break

        rows.append({
            "id": gid,
            "title": title,
            "description": desc,
            "google_product_category": gpc or "",
            "product_type": ptype,
            "brand": "MAGNITEK",
            "identifier_exists": "no",
            "custom_label_0": typ,
            "custom_label_1": price_tier(price_num),
            "custom_label_2": proc,
            "custom_label_3": cl3,
        })
    return rows


SUPP_COLS = ["id", "title", "description", "google_product_category", "product_type",
             "brand", "identifier_exists", "custom_label_0", "custom_label_1",
             "custom_label_2", "custom_label_3"]


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else FEED_URL
    if src.startswith("http"):
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        xml_bytes = urllib.request.urlopen(req, timeout=60).read()
    else:
        xml_bytes = open(src, "rb").read()

    rows = build_rows(xml_bytes)

    if len(rows) < MIN_ITEMS:
        sys.stderr.write(f"СТОП: {len(rows)} товаров (< {MIN_ITEMS}). Битый фид, не публикую.\n")
        sys.exit(1)

    # аномалия: дорогой товар в дефолт-категории расходника = вероятно ошибка детекта
    anomaly = [r for r in rows if r["google_product_category"] == "499947"
               and r["custom_label_1"] in ("high", "premium")]

    os.makedirs("docs", exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(SUPP_COLS)
        for r in rows:
            w.writerow([str(r.get(c, "")) for c in SUPP_COLS])

    from collections import Counter
    print(f"OK: {len(rows)} товаров -> {OUT_CSV}")
    print("  категории:", dict(Counter(r["google_product_category"] for r in rows)))
    print("  типы:", dict(Counter(r["custom_label_0"] for r in rows)))
    print(f"  аномалия (дорогой в дефолт-расходниках): {len(anomaly)} — проверить вручную")
    print("\n--- ОБРАЗЕЦ аппарат (id 40854) ---")
    for r in rows:
        if r["id"] == "40854":
            for c in SUPP_COLS: print(f"  {c:24}: {r[c]}")
            break


if __name__ == "__main__":
    main()
