"""payment_categories.py — категории операций и метод categorizer для analyze_payments.py.

Один файл, без зависимостей от папки categorizer:
  * справочник категорий (GROUPS, CATEGORIES, MANDATORY, SPECIAL);
  * правила по назначению платежа (RULES, apply_rules);
  * categorizer(df, ...) — правила -> контрагент -> d1-omni (опционально).

Использование:
    from payment_categories import categorizer, CATEGORIES, MANDATORY
    res = categorizer(df)   # df: direction ('in'/'out' или 'Поступление'/'Списание'),
                            #     payment_purpose, counterparty_name, [counterparty_key]
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import pandas as pd


# =============================== КАТЕГОРИИ ==================================
GROUPS = {
    "revenue":   "Выручка",
    "staff":     "Персонал",
    "taxes":     "Налоги и взносы",
    "premises":  "Помещение и связь",
    "suppliers": "Поставщики",
    "services":  "Услуги и подрядчики",
    "finance":   "Кредиты и банк",
    "owner":     "Собственник",
    "technical": "Служебные",
}

# code: (group, name, direction, description для модели)
CATEGORIES = {
    # --- выручка
    "revenue_acquiring":  ("revenue", "Эквайринг", "in", "Зачисление выручки по операциям с банковскими картами, эквайринг"),
    "revenue_sbp":        ("revenue", "Оплата через СБП", "in", "Поступления через систему быстрых платежей, QR-код"),
    "revenue_cash":       ("revenue", "Наличная выручка", "in", "Взнос наличных, инкассация торговой выручки"),
    "revenue_marketplace":("revenue", "Выплаты маркетплейсов", "in", "Перечисление от маркетплейса по договору оферты за период продаж"),
    "revenue_client":     ("revenue", "Оплата от клиентов", "in", "Оплата покупателем по счёту, УПД или договору за товары, работы, услуги, предоплата"),
    "income_subsidy":     ("revenue", "Субсидии и возмещения", "in", "Государственные субсидии, страховое возмещение"),
    # --- персонал
    "salary":             ("staff", "Зарплата", "out", "Перечисление заработной платы сотрудникам, аванс, окончательный расчёт, отпускные"),
    "contractor_gph":     ("staff", "Договоры ГПХ", "out", "Оплата физлицам и самозанятым по договору гражданско-правового характера"),
    # --- налоги
    "tax_enp":            ("taxes", "Единый налоговый платёж", "out", "Единый налоговый платёж, ЕНП"),
    "tax_other":          ("taxes", "Прочие налоги и взносы", "out", "Налоги, страховые взносы, НДФЛ, платежи в ФНС и казначейство кроме ЕНП"),
    # --- помещение
    "rent":               ("premises", "Аренда", "out", "Арендная плата за помещение, склад, оборудование"),
    "utilities":          ("premises", "Коммунальные услуги", "out", "Электроэнергия, тепло, вода, вывоз мусора и ТКО"),
    "telecom":            ("premises", "Связь и интернет", "out", "Услуги связи, интернет, телефония"),
    # --- поставщики
    "suppliers":          ("suppliers", "Закупки у поставщиков", "out", "Оплата поставщику за товары, продукты, сырьё, материалы, запчасти по счёту или УПД"),
    "capex":              ("suppliers", "Оборудование и ремонт", "out", "Покупка оборудования, автомобиля, ремонт помещения — разовые крупные вложения"),
    # --- услуги
    "software":           ("services", "ПО и подписки", "out", "Лицензии, право использования программного обеспечения, подписки"),
    "marketing":          ("services", "Реклама", "out", "Пополнение рекламного кабинета, маркетинг, продвижение"),
    "transport":          ("services", "Транспорт и топливо", "out", "Топливные карты, Платон, провоз по дорогам, транспортно-экспедиционные услуги"),
    "services_other":     ("services", "Прочие услуги", "out", "Бухгалтерские услуги, уборка, охрана и другие услуги подрядчиков"),
    # --- финансы
    "loan_received":      ("finance", "Получение кредита", "in", "Получение кредита или займа от банка"),
    "loan_repayment":     ("finance", "Погашение кредита", "out", "Погашение основного долга и процентов по кредиту, проценты по овердрафту"),
    "leasing":            ("finance", "Лизинг", "out", "Лизинговые платежи"),
    "bank_fee":           ("finance", "Комиссии банка", "out", "Комиссия за ведение счёта, обслуживание, переводы"),
    # --- собственник
    "owner_injection":    ("owner", "Вложения собственника", "in", "Пополнение счёта собственными средствами, займ от учредителя, взнос в уставный капитал"),
    "owner_withdrawal":   ("owner", "Вывод средств собственником", "out", "Выплата дивидендов, перевод на личный счёт или карту предпринимателя, возврат займа учредителю"),
    # --- служебные
    "own_transfer":       ("technical", "Перевод между своими счетами", "both", "Перевод собственных средств между своими расчётными счетами в разных банках"),
    "refund":             ("technical", "Возврат платежа", "both", "Возврат ошибочно перечисленных средств"),
    "other":              ("technical", "Прочее", "both", "Не подходит ни под одну категорию"),
}

# Сквозные категории: ставятся ВДОБАВОК к основной, только для списаний.
# Регулярный определяется по датам (regular.py), обязательный — по основной категории.
SPECIAL = {
    "regular_payment":   "Регулярный платёж",
    "mandatory_payment": "Обязательный платёж",
}

# обязательные платежи — для детектора кассового разрыва
MANDATORY = {"salary", "contractor_gph", "tax_enp", "tax_other", "rent", "utilities",
             "telecom", "loan_repayment", "leasing", "bank_fee"}


def allowed_for(direction: str) -> dict:
    """Категории, допустимые для направления 'in' или 'out'."""
    return {c: v for c, v in CATEGORIES.items() if v[2] in (direction, "both")}

# =============================== ПРАВИЛА ====================================
# (code, direction | None, regex). Регэкспы применяются к тексту в нижнем регистре.
RULES = [
    # служебные и собственник — первыми, чтобы «перевод собственных средств» не ушёл в выручку
    ("refund",           None,  r"возврат (ошибочно|излишне|неверно)|ошибочно (перечисл|зачисл)"),
    ("own_transfer",     None,  r"перевод собственных средств (с|на) расч[её]тн\w* сч[её]т"),
    ("owner_injection",  "in",  r"собственными средствами|взнос в уставный капитал|займ\w* (от )?учредител|заем\w* (от )?учредител"),
    ("owner_withdrawal", "out", r"дивиденд|на личн\w+ (сч[её]т|карт)|на сч[её]т физическ\w+ лиц|возврат\w* .*займ\w* учредител"),
    # финансы
    ("loan_repayment",   "out", r"погашение (основного долга|кредит)|процент\w* (по|за) (кредит|договору кредит|пользование)|овердрафт"),
    ("leasing",          "out", r"лизинг"),
    ("loan_received",    "in",  r"кредит|выдача займ|предоставление займ"),
    ("bank_fee",         "out", r"комисси"),
    # выручка
    ("revenue_acquiring","in",  r"эквайринг"),
    ("revenue_sbp",      "in",  r"\bсбп\b|qr-код"),
    ("revenue_cash",     "in",  r"взнос наличных|инкассир"),
    ("revenue_marketplace","in",r"договор\w* оферты.*за период|маркетплейс"),
    ("income_subsidy",   "in",  r"субсиди|грант|страхового возмещения"),
    ("capex",            "out", r"купли-продажи|ремонт помещения|за оборудование|за автомобиль"),
    # налоги: «без налога (ндс)» и «ндс не облагается» не считаются
    ("tax_enp",          "out", r"\bенп\b|единый налоговый плат"),
    ("tax_other",        "out", r"(уплата|перечисление) .*налог|страхов\w+ взнос|\bндфл\b|\bуфк\b"),
    # персонал
    ("salary",           "out", r"заработн\w+ плат|зарплат|отпускн|больничн"),
    ("contractor_gph",   "out", r"\bгпх\b|самозанят"),
    # помещение
    ("rent",             "out", r"аренд"),
    ("utilities",        "out", r"электроэнерг|теплоснаб|водоснаб|водоотвед|коммунальн|\bтко\b|вывоз мусор"),
    ("telecom",          "out", r"услуг\w* связи|интернет|телефони"),
    # услуги
    ("software",         "out", r"использования по\b|программн\w+ обеспечен|лиценз|подписк"),
    ("marketing",        "out", r"реклам"),
    ("transport",        "out", r"топливн|\bазс\b|платон|провоз|транспортно-экспедиц|грузоперевоз"),
    ("services_other",   "out", r"субподряд|выполненные работы|бухгалтерск|уборк|охран|клининг|услуг"),
    # поставщики / клиенты — самые общие, в конце
    ("suppliers",        "out", r"\bупд\b|товар|продукц|поставк|закуп|сырь|материал|продукт|запчаст|издели"),
    ("suppliers",        "out", r"оплата по сч[её]ту .* за "),   # «оплата по счёту … за бакалею/семена/бетон»
    ("revenue_client",   "in",  r"\bупд\b|сч[её]т|договор|предоплат|расч[её]т|оплата"),
]
_COMPILED = [(c, d, re.compile(rx)) for c, d, rx in RULES]


def normalize(text) -> str:
    if not isinstance(text, str):   # None / NaN из pandas
        return ""
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()


def template(text: str | None) -> str:
    """Шаблон назначения: цифры и названия в кавычках убраны. ~1400 шаблонов на 222 тыс. строк."""
    t = normalize(text)
    t = re.sub(r"«[^»]*»|\"[^\"]*\"", "«x»", t)
    t = re.sub(r"\d+", "#", t)
    return t


def apply_rules(text: str | None, direction: str) -> str | None:
    """direction: 'in' / 'out'. Возвращает код категории или None."""
    t = normalize(text)
    if not t:
        return None
    for code, d, rx in _COMPILED:
        if d is not None and d != direction:
            continue
        if rx.search(t):
            return code
    return None

# =============================== КАТЕГОРИЗАЦИЯ ==============================
log = logging.getLogger("categorizer")

LLM_INSTRUCTIONS = (
    "Это назначение банковского платежа малого бизнеса в России. "
    "Направление: {direction}. Контрагент: {counterparty}. "
    "К какой категории относится операция?"
)
LLM_MIN_CONFIDENCE = 0.5      # ниже — категория 'other'
CP_MIN_SHARE = 0.9            # доля операций контрагента в одной категории
CP_MIN_COUNT = 3


# ---------- Ступень 2: наследование по контрагенту ----------
def counterparty_profile(df: pd.DataFrame) -> dict:
    """(counterparty_key, direction) -> (category, share), если контрагент однозначен."""
    stats: dict[tuple, Counter] = defaultdict(Counter)
    for key, dr, cat in df.loc[df.method == "rule", ["counterparty_key", "direction", "category"]].itertuples(index=False):
        if key:
            stats[(key, dr)][cat] += 1
    prof = {}
    for k, cnt in stats.items():
        cat, n = cnt.most_common(1)[0]
        total = sum(cnt.values())
        if total >= CP_MIN_COUNT and n / total >= CP_MIN_SHARE:
            prof[k] = (cat, round(n / total, 3))
    return prof


# ---------- Ступень 3: d1-omni ----------
def parse_choice(res) -> tuple[str | None, float]:
    """Достаёт (код, уверенность) из ответа classify. Подстройте под фактический формат клиента."""
    if isinstance(res, dict):
        code = res.get("choice") or res.get("answer") or res.get("label")
        conf = res.get("confidence")
        probs = res.get("probabilities") or res.get("probs")
        if conf is None and isinstance(probs, dict) and code in probs:
            conf = probs[code]
        return code, float(conf if conf is not None else 0.0)
    if isinstance(res, (list, tuple)) and len(res) >= 2:
        return res[0], float(res[1])
    return (res if isinstance(res, str) else None), 0.0


def llm_classify(text: str, direction: str, counterparty: str, classify_fn) -> tuple[str, float]:
    options = allowed_for(direction)
    criteria = {code: f"{v[1]}: {v[3]}" for code, v in options.items()}
    res = classify_fn(
        text=text if isinstance(text, str) and text.strip() else "(назначение не заполнено)",
        qtype="choice",
        instructions=LLM_INSTRUCTIONS.format(
            direction="поступление" if direction == "in" else "списание",
            counterparty=counterparty or "не указан",
        ),
        criteria=criteria,
    )
    code, conf = parse_choice(res)
    if code not in options or conf < LLM_MIN_CONFIDENCE:
        return "other", conf
    return code, conf


# ---------- Конвейер ----------
def categorize(df: pd.DataFrame, classify_fn=None, workers: int = 4) -> pd.DataFrame:
    df = df.copy()
    df["category"] = None
    df["method"] = "none"
    df["confidence"] = 0.0

    # 1. правила
    df["category"] = [apply_rules(t, d) for t, d in zip(df.payment_purpose, df.direction)]
    m = df.category.notna()
    df.loc[m, "method"] = "rule"
    df.loc[m, "confidence"] = 1.0
    log.info("rules: %d / %d (%.1f%%)", m.sum(), len(df), 100 * m.mean())

    # 2. контрагент
    prof = counterparty_profile(df)
    todo = df.category.isna()
    hits = [prof.get((k, d)) for k, d in zip(df.loc[todo, "counterparty_key"], df.loc[todo, "direction"])]
    for idx, h in zip(df.index[todo], hits):
        if h:
            df.at[idx, "category"], df.at[idx, "confidence"] = h
            df.at[idx, "method"] = "counterparty"
    log.info("counterparty: %d", (df.method == "counterparty").sum())

    # 3. модель — один вызов на уникальный (шаблон, направление, контрагент)
    todo = df.category.isna()
    if todo.any() and classify_fn is not None:
        sub = df.loc[todo]
        keys = list(zip(sub.payment_purpose.map(template), sub.direction, sub.counterparty_name.fillna("")))
        uniq = {}
        for k, text in zip(keys, sub.payment_purpose):
            uniq.setdefault(k, text)
        log.info("llm: %d операций, %d уникальных запросов", len(sub), len(uniq))

        def call(item):
            (tpl, dr, cp), text = item
            try:
                return (tpl, dr, cp), llm_classify(text, dr, cp, classify_fn)
            except Exception as e:  # сеть/модель: не валим весь прогон
                log.warning("llm error: %s", type(e).__name__)
                return (tpl, dr, cp), ("other", 0.0)

        with ThreadPoolExecutor(workers) as ex:
            answers = dict(ex.map(call, uniq.items()))
        for idx, k in zip(sub.index, keys):
            code, conf = answers[k]
            df.at[idx, "category"], df.at[idx, "confidence"], df.at[idx, "method"] = code, round(conf, 3), "llm"

    df["category"] = df.category.fillna("other")
    return df

# =============================== ОБЁРТКА ДЛЯ analyze_payments ===============
def _to_io(direction) -> str:
    d = str(direction).lower()
    return "in" if d in ("in", "1") or "поступл" in d else "out"


def categorizer(df: pd.DataFrame, use_llm: bool = False, classify_fn=None, workers: int = 4) -> pd.DataFrame:
    """Категории для DataFrame операций в любом формате направления.

    Нужны колонки: direction, payment_purpose, counterparty_name.
    counterparty_key / counterparty_inn / operation_id — необязательны.
    use_llm=True без classify_fn — берётся classify из client.py (d1-omni на :8300).

    Возвращает DataFrame с тем же индексом и колонками:
        category, category_name, category_group, method, confidence
    """
    name = df["counterparty_name"].fillna("").astype(str)
    if "counterparty_key" in df:
        key = df["counterparty_key"].fillna("").astype(str)
    elif "counterparty_inn" in df:
        key = df["counterparty_inn"].fillna("").astype(str) + "|" + name
    else:
        key = name
    purpose = df["payment_purpose"].where(
        df["payment_purpose"].astype(str).str.strip().ne("") & df["payment_purpose"].notna())
    src = pd.DataFrame({
        "operation_id":      df["operation_id"] if "operation_id" in df else df.index.astype(str),
        "direction":         df["direction"].map(_to_io),
        "counterparty_key":  key,
        "counterparty_name": name,
        "payment_purpose":   purpose,
    }, index=df.index)

    if use_llm and classify_fn is None:
        from client import classify
        classify_fn = classify

    res = categorize(src, classify_fn, workers)
    return pd.DataFrame({
        "category":       res["category"],
        "category_name":  res["category"].map(lambda c: CATEGORIES[c][1]),
        "category_group": res["category"].map(lambda c: GROUPS[CATEGORIES[c][0]]),
        "method":         res["method"],
        "confidence":     res["confidence"],
    }, index=df.index)
