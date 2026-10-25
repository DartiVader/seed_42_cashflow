# ML-сервис: как подключить прогноз

Для Андрея (FastAPI, Docker, реестр моделей). Всё ниже проверено на `.venv` (Python 3.13, версии — в
`requirements.txt`). Запуск только `.venv/bin/python -m …` из корня репозитория.

## Что нового (24.10)

| что | где | что сделать сервису |
|---|---|---|
| **План-факт** `plan_fact()` — прошлый прогноз против факта по дням и по платежам | п. 2, «План-факт» | новая ручка `POST /plan-fact` |
| Поле `events[].overdue_from` — первая пропущенная дата просроченного платежа | п. 5 | пробросить в Spring/React как есть (необязательное) |
| CLI: `--plan-fact [--lookback 10]` | п. 6 | — |
| Моки `mocks/C044_plan_fact.json`, `mocks/C119_plan_fact.json`; `C140_gap_expected.json` — с `overdue_from` | `mocks/` | отдать Богдану |
| `ForecastContext.carry_overdue_receipts` (по умолчанию `False`) | п. 2 | ничего, флаг не трогать |
| **Поле `trace`** — «Как посчитано»: шаги 1–9 в цифрах, только агрегаты | п. 5, «trace» | пробросить в Spring/React как есть (вкладка «Как посчитано») |
| Все моки прогноза пересобраны с `trace`, остальные поля не изменились | `mocks/` | отдать Богдану |
| В `trace` у каждого шага `ms` — время шага | п. 5, «trace» | показать на вкладке, если нужно |
| Порог тревоги `GapConfig.p_day_min` 0,3 → 0,35 (подбор по F1 на tune, 9.3): чуть меньше ложных тревог | — | ничего; моки пересобраны |

Остальной контракт не менялся: старые поля, коды ошибок и тексты те же.

## 0. Быстрый старт: готовый каркас FastAPI

Проверен (fastapi 0.115.12, `TestClient`): `/forecast` C140 на 30.09 → 200 за 0,46 с, ответ совпадает с
`mocks/C140_gap_expected.json`; сценарий выручки 0,7 — с `mocks/C001_scenario.json`; выписка C140 в `ops` даёт тот же
ответ, что и данные контекста; `/plan-fact` C119 — с `mocks/C119_plan_fact.json`; C999 → 404; выписка без
`balance_eod` → 400 «В выписке не хватает колонок: balance_eod.». fastapi/uvicorn в `requirements.txt` ML-части нет —
добавь в requirements сервиса с версиями.

```python
import os
from contextlib import asynccontextmanager
from datetime import date

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ml.forecast.api import ForecastContext, forecast
from ml.forecast.contracts import (CompanyClosedError, Event, ForecastError, InvalidStatementError,
                                   Scenario)
from ml.forecast.plan_fact import plan_fact

CTX: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    CTX["ctx"] = ForecastContext.load(
        os.environ.get("ML_DATA_DIR", "cashflow_data/cashflow_dataset_participants"),
        os.environ.get("ML_MODELS_DIR", "models"),
        "reports/backtest_residuals.parquet")          # v2 его не читает, нужен только для отката на v1
    yield


app = FastAPI(lifespan=lifespan)


class EventIn(BaseModel):
    date: date
    amount: float                  # + поступление, − списание
    category: str
    source: str = "manual"
    confidence: float = 1.0
    mandatory: bool = False
    stream_id: str | None = None   # тот же stream_id заменяет найденное по истории («применить совет»)


class ScenarioIn(BaseModel):
    revenue_multiplier: float = 1.0
    fixed_cost_multiplier: float = 1.0
    delay_counterparty: dict[str, int] = {}
    extra_expenses: list[EventIn] = []


class ForecastIn(BaseModel):
    company_id: str
    as_of: date
    horizon_days: int = 30
    events: list[EventIn] = []
    scenario: ScenarioIn | None = None
    seed: int = 42
    advice: bool = True
    industry: str | None = None
    ops: list[dict] | None = None  # выписка с сайта: строки с колонками датасета


class PlanFactIn(BaseModel):
    company_id: str
    as_of: date
    lookback_days: int = 10
    seed: int = 42
    ops: list[dict] | None = None


def _ops(rows):
    return None if rows is None else pd.DataFrame(rows)


def _http(e: ForecastError) -> HTTPException:
    if isinstance(e, InvalidStatementError):
        return HTTPException(400, str(e))
    if isinstance(e, CompanyClosedError):
        return HTTPException(422, str(e))
    return HTTPException(404 if str(e).startswith("Нет данных") else 422, str(e))


def _event(e: EventIn) -> Event:
    return Event(**e.model_dump())


@app.post("/forecast")
def post_forecast(r: ForecastIn) -> dict:   # def, не async: forecast() считает CPU ~0,5 с — в пуле потоков
    sc = None
    if r.scenario:
        sc = Scenario(**{**r.scenario.model_dump(exclude={"extra_expenses"}),
                         "extra_expenses": [_event(e) for e in r.scenario.extra_expenses]})
    try:
        res = forecast(r.company_id, r.as_of, r.horizon_days, events=[_event(e) for e in r.events],
                       scenario=sc, seed=r.seed, context=CTX["ctx"], ops=_ops(r.ops),
                       industry=r.industry, advice=r.advice)
    except ForecastError as e:
        raise _http(e)
    return res.to_dict()


@app.post("/plan-fact")
def post_plan_fact(r: PlanFactIn) -> dict:
    try:
        return plan_fact(r.company_id, r.as_of, r.lookback_days, seed=r.seed, context=CTX["ctx"], ops=_ops(r.ops))
    except ForecastError as e:
        raise _http(e)


@app.get("/health")
def health() -> dict:
    return {"model_version": CTX["ctx"].model_version}
```

Сохрани как `app.py` в корне репозитория (рядом с `ml/`), запуск — `uvicorn app:app --workers 2` (под uvicorn
я не запускал, только `TestClient`). Каждый процесс грузит свой контекст ~7 с, ~600 МБ.
Ручки синхронные (`def`) — FastAPI сам уводит их в пул потоков; для нагрузки — больше `--workers`, а не потоков
(п. 4). Docker: в образ нужны `ml/`, `models/lgbm_net-v2/` (и `lgbm_net-v1/` для отката), данные — `make bundle`.

Какая ручка какой экран кормит (подробно — `docs/entrepreneur_service.md`):
- «Деньги на 30 дней», календарь платежей, «Что если» — `/forecast` (`daily`, `events`, `gaps`, `scenario`);
- «Что произошло» (план-факт по дням и платежам) — `/plan-fact`;
- кнопка «применить совет» — `/forecast` с событием из `actions_detail` (п. 2, «Советы»).

## 1. Контекст: загрузить один раз при старте процесса

```python
from ml.forecast.api import ForecastContext, forecast

ctx = ForecastContext.load(
    data_dir="cashflow_data/cashflow_dataset_participants",   # statements/*.csv, companies.csv
    models_dir="models",                                     # реестр версий
    residuals_path="reports/backtest_residuals.parquet",     # нужен только версиям v1 (у v2 ошибки в каталоге)
    model="lgbm_net",                                        # основная; резерв — "lgbm" (только v1)
    version="v2",                                            # по умолчанию; каталог models/<model>-<version>
)
```

- Можно передать путь прямо на каталог версии: `models_dir="models/lgbm-v1"`.
- Что лежит в каталоге версии: бустеры, `meta.json`, `training.json`, `calibration.json` (вероятность),
  `shortfall_calibration.json` (суммы нехватки). У версии с регулярными событиями ещё `events.json`
  (какие категории идут событиями) и `residuals.parquet` (свои ошибки) — тогда `residuals_path` не читается.
- **Основная версия — `lgbm_net-v2`** (с 24.10): регулярные обязательные платежи (налоги, зарплата, аренда,
  кредит, лизинг, коммунальные, связь, комиссии) идут событиями, модель прогнозирует остальное.
  Откат — `version="v1"` (тот же контракт, событий из истории нет).
- Загрузка ~7 с; процесс с контекстом — **~600 МБ RSS** (операции после очистки 71 МБ, панель 17 МБ, модель,
  пул ошибок, плюс pandas/lightgbm).
- **Время `forecast()` (v2, с советами): медиана 0,40 с, P95 0,55 с, максимум 0,62 с** на 143 компаниях
  (разметка регулярных платежей и прогноз модели — один раз на запрос; советы пересчитывают только
  Монте-Карло). v1 — ~0,1 с. Таймаут на стороне сервиса ставьте с запасом (≥ 3 с).
- Сейчас контекст читает CSV. Чтобы брать данные из PostgreSQL, соберите те же DataFrame (`load_dataset`
  возвращает `ops, companies` в формате `ml/data/loaders.py`) и повторите шаги `load()`: `clean_operations` →
  `build_panel` → `load_model` → `error_pool`. Модули — чистые функции, БД внутри них нет.

## 2. Вызов

```python
def forecast(company_id: str, as_of: date, horizon_days: int = 30,
             events: list[Event] | None = None,
             scenario: Scenario | None = None,
             n_paths: int = 1000, seed: int = 42, *,
             context: ForecastContext,
             ops: pd.DataFrame | None = None,      # выписка из запроса (сайт)
             industry: str | None = None,          # отрасль, если компании нет в справочнике
             advice: bool = True) -> ForecastResult

res = forecast("C140", date(2026, 9, 30), context=ctx)
payload = res.to_dict()          # JSON-контракт, см. п.5
```

### Выписка из запроса (`ops`)

Для выписки, загруженной через сайт, передайте её DataFrame в `ops` — колонки как в датасете:
`operation_date, amount, direction, counterparty_inn, counterparty_name, payment_purpose, balance_eod`
(`company_id`, `operation_id` — необязательны). Тогда панель, разметка регулярных платежей, масштаб, признаки
и история строятся по ней; модель, калибровка и пул ошибок — из контекста.

- Проверка входа: обязательные колонки; дата читается (ГГГГ-ММ-ДД); `amount` > 0 и `balance_eod` — числа;
  `direction` — «Поступление»/«Списание»; **ИНН — строкой** (число теряет ведущие нули — ошибка); операции
  другой компании — ошибка. Операции позже `as_of` отрезаются молча. Ошибка — `InvalidStatementError` с текстом
  для пользователя (**HTTP 400**).
- Компании нет в справочнике (`companies.csv` контекста): передайте `industry` (строка из справочника отраслей).
  Не передали или отрасль модели незнакома — прогноз строится без признака отрасли, пул ошибок — по всем
  отраслям, в `data_quality` появляется `"industry_known": false`.
- Проверено: `forecast("C140", ops=выписка C140 из statements/C140.csv)` совпадает с `forecast("C140")` полностью.

### Советы (`gaps[].actions`, `gaps[].actions_detail`)

Для каждого разрыва пересчитываются варианты действий на тех же траекториях Монте-Карло, что и прогноз
(тот же `seed` → те же цифры). Обязательные платежи (налоги, зарплата, кредит, лизинг, аренда, коммунальные,
связь, банк, ГПХ) не переносятся никогда. **Овердрафт — всегда последним:** «нужен лимит ~P50, с запасом ~P90»
нехватки за горизонт.

| `type` | что | отбор |
|---|---|---|
| `postpone` | отложить необязательное списание (не поставщик) до восстановления остатка + 2 р.д. | риск в окне ±5 р.д. от даты разрыва −0,10 или нехватка −20 % |
| `negotiate_supplier` | договориться с поставщиком о переносе платежа на неделю | так же |
| `speed_up_receivable` | попросить клиента оплатить до даты разрыва (вероятность × 0,7) | так же |
| `cut_discretionary` | сократить на 20 % крупнейшие необязательные категории в окне (по истории) | риск за горизонт −0,10 или нехватка −20 % |
| `combo` | два лучших совета вместе (`parts`), если ни один не убирает разрыв и вместе заметно лучше | |
| `overdraft` | лимит овердрафта и срок | всегда |

Совет не показывается, если после него не снизились ни риск за горизонт, ни ожидаемая глубина минуса. Максимум
3 совета, сортировка по снижению риска. Пример текста переноса: «Попросите клиента ООО «…» оплатить 7,3 млн ₽ до
01.10 (ожидается 12.10) — нехватки 01.10 не будет (риск 66% → 26%), но ближайший риск сместится на 12.10 (~35%)»;
если разрывов на горизонте больше нет — «…разрыва до 30.10 не будет».

`actions_detail[]`:
- `type, stream_id, category, counterparty_name, amount, date_from, date_to`;
- `prob_before`, `prob_after` (= `prob_horizon_after`) — вероятность разрыва за горизонт, калиброванная;
- `prob_window_before`, `prob_window_after` — доля траекторий с минусом в окне ±5 р.д. от исходной даты разрыва
  (**без калибровки**: isotonic обучен на вероятности за горизонт, его ступеньки съедают разницу в окне);
- `shortfall_before`, `shortfall_after` — нехватка за горизонт (`shortfall`, медиана макс. глубины);
- `gap_date_after` — ближайший разрыв после совета или `null`;
- у `cut_discretionary` — `categories: [{category, name, amount}]` (2–3 крупнейшие необязательные категории
  списаний за 3 месяца и их доля сокращения), у `overdraft` — `amount` (P50) и `amount_high` (P90),
  `*_after` — `null`, у `combo` — `parts`.

**Кнопка «применить совет»** для `postpone` / `negotiate_supplier` / `speed_up_receivable`: передать в `events`
событие с тем же `stream_id`, суммой со знаком и датой `date_to` — оно заменит найденное по истории.
`counterparty_name` — в ответ можно, в логи нельзя. `advice=False` — без пересчёта (в `actions` только овердрафт).

### План-факт (`ml.forecast.plan_fact`)

```python
from ml.forecast.plan_fact import plan_fact
r = plan_fact("C119", date(2026, 9, 30), lookback_days=10, seed=42, context=ctx)   # ops=... — как в forecast
```

- План — тот же `forecast()` на `as_of_plan` = `as_of` минус `lookback_days` рабочих дней, факт — выписка ≤ `as_of`
  (что позже — отрезается до всех расчётов). Возвращает готовый `dict` (JSON), не dataclass. Время ~1 с.
- Сверяются регулярные платежи и поступления плана с датой в (`as_of_plan`, `as_of`]: операции того же потока
  (контрагент, категория, направление) в окне ±3 рабочих дня. Сумма в ±20 % — `paid`, меньше — `partial`,
  ничего — `missed`.
- Ошибки — те же `ForecastError`, что у `forecast()` (на дату плана): нет данных → 404, счёт закрыт → 422;
  `lookback_days` уводит дату плана за начало календаря → `ForecastError` (422).

Пример — C119 на 30.09 (`mocks/C119_plan_fact.json`, `daily` и `events` обрезаны):

```json
{
  "company_id": "C119",
  "as_of": "2026-09-30",
  "as_of_plan": "2026-09-16",
  "model_version": "lgbm_net-v2",
  "daily": [
    {"date": "2026-09-17", "plan_p10": 2904332, "plan_p50": 3120863, "plan_p90": 3425406,
     "fact": 3023966.16, "deviation": -96896.56, "outside": false}
  ],
  "events": [
    {"date": "2026-09-21", "category": "revenue_client", "amount_plan": 398037.29, "amount_fact": 0.0,
     "status": "missed", "days_late": 7, "stream_id": "<ИНН контрагента>|revenue_client|in",
     "mandatory": false, "confidence": 0.69, "window_open": false},
    {"date": "2026-09-21", "category": "leasing", "amount_plan": -144900.0, "amount_fact": -144900.0,
     "status": "paid", "days_late": 0, "stream_id": "<ИНН контрагента>|leasing|out",
     "mandatory": true, "confidence": 1.0, "window_open": false}
  ],
  "summary": {"missed_in": 2, "missed_out": 0, "partial": 1, "paid": 2, "outside_days": 0,
              "max_deviation": 100151.29, "max_deviation_date": "2026-09-23"}
}
```

Поля:
- `daily[]` — по календарным дням (`as_of_plan`, `as_of`]: `plan_p10/p50/p90` — план остатка (целые ₽),
  `fact` — фактический `balance_eod` (в выходной — остаток последнего рабочего дня; после конца выписки `null`),
  `deviation` = факт − P50, `outside` — факт вне P10–P90 (при `fact = null` оба `null`);
- `events[]` — `amount_plan` / `amount_fact` со знаком (+ поступление, − списание; у `missed` факт 0);
  `days_late` — рабочих дней от ожидаемой даты (у платежа, просроченного уже на дату плана, — от первой пропущенной,
  она же `overdue_from`) до последней операции, у `missed` — до `as_of`; < 0 — раньше срока;
  `window_open: true` — окно ±3 р.д. ещё не закрылось, «может ещё прийти»; `confidence` — с какой уверенностью план
  ждал платёж;
- `summary` — `missed_in` / `missed_out` (не пришло / не списано), `partial`, `paid`, `outside_days`, `max_deviation`
  (отклонение, наибольшее по модулю, со знаком) и его дата.

Ограничение: если контрагент одним платежом закрыл несколько своих потоков одной категории (C044, коммунальные
17.09), один поток будет `paid` с переплатой, другой — `missed`.

**Просроченные поступления в текущем прогнозе.** У события `forecast()` с пропущенной датой есть `overdue_from`
(у обязательных платежей — всегда). Поступления клиентов событием в прогноз идут только при
`ForecastContext.carry_overdue_receipts=True`, с уверенностью по истории задержек контрагента. По умолчанию флаг
выключен: на backtest он ухудшает остаток на 7 днях (`reports/overdue_receipts_check.csv`). Решение — за Сергеем,
сервису флаг не трогать.

## 3. Исключения и коды ответа (предложение)

| исключение | когда | текст | HTTP |
|---|---|---|---|
| `CompanyClosedError` (подкласс `ForecastError`) | нет операций > 30 дней до `as_of` или 20 рабочих дней тишины в конце | «По счёту нет операций с 10.04.2026. Похоже, счёт закрыт или не используется — прогноз не строим. Загрузите актуальную выписку.» | 422 |
| `InvalidStatementError` (подкласс `ForecastError`) | выписка из запроса не читается | «В выписке не хватает колонок: balance_eod.», «ИНН контрагента должен быть строкой — числом теряются ведущие нули.» | 400 |
| `ForecastError` | нет данных по компании на дату | «Нет данных по компании C999 на 30.09.2026» | 404 |
| `ForecastError` | в горизонте нет рабочих дней (после `as_of`) | «Горизонт прогноза не содержит рабочих дней…» | 422 |
| `ValueError` при `ForecastContext.load` | набор признаков модели не совпадает с кодом; в каталоге модель другого типа | — | не стартовать |
| прочее | ошибка в коде | — | 500 |

`str(e)` у `ForecastError` — готовый текст для предпринимателя. Ловите подклассы раньше базового:
`InvalidStatementError` → `CompanyClosedError` → `ForecastError` → `ValueError`. CLI (`ml.forecast.cli`) при `ForecastError` печатает
`{"company_id": …, "error": "…"}` и выходит с кодом 2.

## 4. Потокобезопасность

- `forecast()` контекст не меняет: читает панель, операции, модель, пул; свой генератор случайных чисел на
  каждый вызов. Параллельные вызовы на одном контексте дают те же ответы, что и последовательные.
- **Рекомендуемый режим — процессы** (`uvicorn --workers N` / gunicorn), контекст свой в каждом процессе
  (≈ 600 МБ каждый). Потоки внутри процесса допустимы, но:
  - LightGBM в каждом `predict` сам берёт 4 потока (`num_threads=4` в `meta.json`) — при многих потоках
    CPU переподписывается; для потоков лучше `uvicorn --workers` и 1–2 потока на процесс;
  - `ml/pipeline/regular.py` глушит предупреждения кода Влада через `warnings.catch_warnings()`, это глобальное
    состояние интерпретатора (не потокобезопасно). На результат не влияет, но предупреждение из соседнего
    потока может потеряться или напечататься.
- Логи: только `company_id`, количества, метрики, тайминги. ИНН, контрагенты, суммы, назначения не логируются;
  `stream_id` содержит ИНН контрагента — **не логировать**.

## 5. JSON ответа (все поля)

`ForecastResult.to_dict()`, пример — C140 на 30.09.2026 (`mocks/C140_gap_expected.json`, `daily` и `events`
обрезаны):

```json
{
  "company_id": "C140",
  "as_of": "2026-09-30",
  "model_version": "lgbm_net-v2",
  "data_quality": {
    "history_days": 495,
    "short_history": false,
    "gaps_in_data": 0,
    "days_since_last_operation": 0
  },
  "status": "gap_expected",
  "daily": [
    {"date": "2026-10-01", "p10": -31698, "p50": 5497, "p90": 37914},
    {"date": "2026-10-02", "p10": -26260, "p50": 20269, "p90": 55543}
  ],
  "events": [
    {"date": "2026-10-01", "amount": -80685.37, "category": "tax_enp", "source": "regular",
     "confidence": 1.0, "stream_id": "<ИНН контрагента>|tax_enp|s1|out", "overdue_from": "2026-09-28"},
    {"date": "2026-10-02", "amount": -990.0, "category": "bank_fee", "source": "regular",
     "confidence": 1.0, "stream_id": "<ИНН контрагента>|bank_fee|out"}
  ],
  "gaps": [
    {
      "date": "2026-10-01",
      "shortfall": 301869,
      "shortfall_low": 133490,
      "shortfall_high": 487674,
      "shortfall_at_gap": 106199,
      "shortfall_at_gap_low": 45468,
      "shortfall_at_gap_high": 221426,
      "probability": 0.73,
      "reasons": [
        "С 01.10 по 07.10 не хватит ~106 тыс. ₽ (от 45 тыс. ₽ до 221 тыс. ₽)",
        "ЕНП за 28.09 (~81 тыс. ₽) ещё не уплачен — учтён в прогнозе на 01.10"
      ],
      "actions": [
        "Чтобы не уйти в минус до 30.10, нужен лимит ~302 тыс. ₽, с запасом ~488 тыс. ₽; овердрафт понадобится примерно на 1 дн. (до 02.10)"
      ],
      "actions_detail": [
        {
          "type": "overdraft",
          "stream_id": null,
          "category": null,
          "counterparty_name": null,
          "amount": 301869,
          "amount_high": 487674,
          "date_from": "2026-10-01",
          "date_to": "2026-10-02",
          "prob_before": 0.73,
          "prob_after": null,
          "shortfall_before": 301869,
          "shortfall_after": null,
          "gap_date_after": null
        }
      ]
    }
  ]
}
```

Поля:
- `status`: `already_negative` (остаток на `as_of` уже ниже порога) · `gap_expected` (разрыв впереди) · `ok`.
- `data_quality.days_since_last_operation` — необязательное (int): сколько календарных дней выписка молчит до `as_of`.
- `daily[].p10/p50/p90` — остаток, ₽, целые.
- `events[]` — события, учтённые в прогнозе (пользовательские и, у версии с событиями, регулярные).
  `stream_id` — только у регулярных; у v2 обычно 5–15 событий на 30 дней, у v1 без пользовательских событий
  список пустой. Необязательные поля: `stream_id`; `overdue_from` (новое, 24.10) — платёж должен был пройти
  с этой даты, но не прошёл, поэтому стоит на ближайший рабочий день (в `reasons` — «ЕНП за 28.09 … ещё не уплачен»).
- `gaps[]` — 0 или 1 элемент:
  - `shortfall` — максимальная глубина минуса за весь горизонт: «какой лимит овердрафта нужен»;
  - `shortfall_at_gap` — нехватка в окне 5 рабочих дней от даты разрыва: «сколько найти к этой дате»;
  - `*_low` / `*_high` — P10 / P90 (необязательные);
  - `probability` — откалиброванная вероятность «придётся искать деньги», значения ступеньками (isotonic);
  - `reasons`, `actions` — готовые тексты для предпринимателя; `actions_detail` — те же советы структурой
    (необязательное поле, см. «Советы»).

- `trace` — «Как посчитано», см. ниже.

### trace — «Как посчитано»

Список из 9 шагов, всегда все девять, в порядке документа «Seed 42 — как всё работает» (3.1–3.9):
`{"step": 1, "name": "Очистка", "ms": 12.3, "values": {...}}`. `ms` — время шага в миллисекундах; категории
(шаг 2) и регулярные (шаг 3) считаются одним проходом, их общее время — в шаге 3, у шага 2 и 9 `ms: null`. `ms` — единственное, что отличается
у двух одинаковых запросов: кэшировать и сравнивать ответы — без него. Только агрегаты: количества, доли, суммы по шагу,
вероятности. Контрагентов, ИНН, назначений и отдельных операций там нет (тест `ml/tests/test_trace.py`).
Суммы — по счёту самой компании, ₽, целые. Пример C001 на 30.09.2026 (`mocks/C001_ok.json`):

| шаг | `name` | `values` |
|---|---|---|
| 1 | Очистка | `operations` (≤ as_of), `duplicate`, `own_transfer`, `founder_financing`, `error_refund` — сколько помечено; `history_days`, `gaps_in_data` (пропусков в выписке), `oneoff_days` (дней с разовыми крупными) |
| 2 | Категории платежей | `categorized`, `categories` (сколько разных), `unknown_share` (доля «прочее»), `top` — до 8 категорий: число операций |
| 3 | Регулярные платежи | `streams`, `mandatory_streams`, `inflow_streams`, `regular_operations`, `regular_share`, `overdue_streams` |
| 4 | Будущие события | `events`, `mandatory`, `from_user`, `overdue`, `inflow_sum`, `outflow_sum`, `expected_net` (с учётом уверенности), `left_to_model` (регулярные необязательные — их ждёт модель) |
| 5 | Модель прогноза | `model_version`, `model`, `working_days`, `daily_turnover` (масштаб), `irregular_inflow_sum`, `irregular_outflow_sum` — прогноз нерегулярной части за горизонт |
| 6 | Монте-Карло | `paths`, `seed`, `error_pool` (`industry` / `all`), `error_pool_size`, `widen` (1,5 у короткой истории), `end_p10/p50/p90` (остаток в конце горизонта), `min_p50` |
| 7 | Кассовый разрыв | `threshold`, `p_day_min`, `max_p_day`, `probability_raw` (доля траекторий с провалом), `probability` (после калибровки — есть и при `status: ok`), `calibrated`, `status`, `gap_date`, `shortfall` |
| 8 | Сценарий «что если» | `applied`; если сценарий есть — `revenue_multiplier`, `fixed_cost_multiplier`, `delayed_counterparties`, `extra_expenses` |
| 9 | План-факт | `{"available": false, "endpoint": "/plan-fact"}` — в прогнозе не считается, отдельная ручка |

У версий без событий (v1) шаги 2–3 — `{"available": false}`. Ключи внутри `values` могут добавляться — фронту
показывать то, что знает, остальное пропускать. Время прогноза с `trace` не изменилось (~0,5 с).

Моки для фронта (v2, все на 30.09.2026, пересобраны 24.10) — `mocks/`: `C001_ok.json`, `C001_scenario.json`
(выручка −30 %), `C084_already_negative.json`, `C140_gap_expected.json` (разрыв на следующий день, просроченный ЕНП
с `overdue_from`), `C044_gap_expected.json` (разрыв через 12 дней, причина «Зарплата 12.10 — ~461 тыс. ₽»);
план-факт — `C119_plan_fact.json` (2 не пришедших поступления, частичный ЕНП), `C044_plan_fact.json`
(не списанная коммуналка).

## 6. Обучение и реестр

```bash
.venv/bin/python -m ml.train                          # backtest всех моделей + отчёты + финальные lgbm-v1, lgbm_net-v1 (~15 мин)
.venv/bin/python -m ml.train --models zero,lgbm,lgbm_net --skip-final   # только backtest (~3–5 мин без ETS)
.venv/bin/python -m ml.train --final-only             # только финальные lgbm-v1, lgbm_net-v1 (~35 с), калибровка из reports/
.venv/bin/python -m ml.evaluation.ablation            # абляция регулярных событий → reports/ablation.csv (~40 мин)
.venv/bin/python -m ml.train --events mandatory --version v2   # lgbm_net-v2 (основная): модель + регулярные события (~40 с)
.venv/bin/python -m ml.evaluation.gap_metrics reports/backtest_predictions.parquet   # пересчёт метрик разрывов
.venv/bin/python -m ml.forecast.cli C140 2026-09-30 [--revenue 0.7] [--model lgbm] [--models-dir models]
.venv/bin/python -m ml.forecast.cli C119 2026-09-30 --plan-fact [--lookback 10]   # план-факт в JSON
.venv/bin/python -m pytest -q ml/tests
make bundle                                           # dist/ml_bundle/: models/ + нужные parquet, печатает размер
```

Переменные окружения: `ML_DATA_DIR`, `ML_MODELS_DIR` (по умолчанию `cashflow_data/…`, `models`). Секретов нет.
