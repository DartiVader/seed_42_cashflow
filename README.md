# Seed 42 — прогноз денежных потоков для МСБ

Сервис по банковской выписке показывает остаток на месяц вперёд с коридором P10–P90, вероятность и дату
кассового разрыва, советы с проверкой пересчётом, сценарии «что если», план-факт и объяснения простым языком.

![Архитектура](architecture.png)

## Демо

https://github.com/user-attachments/assets/a4d0b54a-5322-4021-b393-ef65b636a07e

https://github.com/user-attachments/assets/20a28927-8fa7-4ace-a125-cf847b43aaf6

https://github.com/user-attachments/assets/f98328e4-1520-4d84-ba65-73707bcdca51

https://github.com/user-attachments/assets/5d3bfd4a-093f-46c6-9ed7-05716d8b337a

## Состав репозитория

| Папка | Что это |
|---|---|
| `app/` | бэкенд на FastAPI: авторизация, компании и операции, импорт, маркетплейсы, прокси к ML и LLM, «Качество модели» |
| `client/` | фронт на React + Vite (PWA) |
| `service/` | ML-шлюз на FastAPI: пул воркеров прогноза, фоновые задачи (классификация, отчёт о качестве) |
| `ml-model/` | код модели (`ml/`), обученные модели (`models/`), отчёты для шлюза и страницы качества (`reports/`) |
| `llm_service/` | сервис объяснений (`POST /explain`), без модели отвечает по шаблону |
| `migrations/` | схема PostgreSQL; применяется при старте бэкенда, идемпотентно |
| `scripts/seed_demo.py` | заливка демо-пользователей и компаний через API |
| `tests/` | тесты бэкенда; `service/tests`, `llm_service/tests` — тесты сервисов |
| `docs/`, `reports/e2e/` | скриншоты и отчёт E2E-проверки |
| `db/` | схема БД команды: миграции `V00x`, представления и `get_operations_period` (`db/migrate.sh`) |
| `mock_marketplace_api.py`, `examples/` | мок API маркетплейсов OZON / WB / Яндекс Маркет с примерами ответов (`MARKETPLACE_URL`) |
| `server/` | первая версия бэкенда на Spring — заменена бэкендом на FastAPI (`app/`), оставлена для истории |

## Запуск

1. Датасет кейса в репозиторий не входит (его выдают организаторы). Положите его так:
   ```
   ml-model/cashflow_data/cashflow_dataset_participants/companies.csv
   ml-model/cashflow_data/cashflow_dataset_participants/all_operations.csv
   ml-model/cashflow_data/cashflow_dataset_participants/statements/*.csv
   ```
2. Настройки и запуск:
   ```bash
   cp .env.example .env    # JWT_SECRET, ML_INTERNAL_TOKEN, ADMIN_EMAIL / ADMIN_PASSWORD; DATABASE_URL — своя БД или локальная
   docker compose up --build
   ```
3. Фронт: http://localhost:5173, Swagger бэкенда: http://localhost:8080/docs. Если порт 8080 занят — `BACKEND_PORT=18081` в `.env`.

Демо: зарегистрироваться → «Данные → Загрузка» → zip датасета (или `companies.csv`, затем выписки) → «Прогноз».

Продакшен-сборка фронта: `cd client && npm ci && npm run build`, папка `client/dist` — статика для nginx;
`/api/*` проксируется на бэкенд (для загрузки датасета — таймаут не меньше 600 с). Для HTTPS в `.env` — `JWT_COOKIE_SECURE=true`.

## Как это работает

- **Данные пользователя.** Компания — общий справочник; связь «пользователь — компания» в `users_company`,
  у каждой операции свой `user_id`. Пользователь видит только свои компании и операции; чужая компания → 404.
- **Импорт CSV/ZIP.** Разделитель (`;`, `,`, табуляция, `|`) определяется по строке заголовков; значения в кавычках
  могут содержать разделитель. Остаток банка на конец дня сохраняется в `operation.balance_eod`; повторная загрузка
  той же выписки дубли не создаёт, а пустой остаток дописывает. Пачка операций вставляется одним запросом.
- **Категории операций** считаются в фоне после каждой загрузки или правки (по сессии): правила → история
  контрагента → нейросеть-классификатор; каждая компания фиксируется отдельной транзакцией.
- **Прогноз.** ML-шлюз берёт операции пользователя из БД функцией `get_operations_period`, где нет остатка банка —
  досчитывает от последнего известного. LightGBM прогнозирует поток, Монте-Карло строит 1000 траекторий
  с реальными ошибками модели из backtest → P10/P50/P90, вероятность и дата разрыва, нехватка, советы.
- **«Применить совет»** превращает совет в сценарий «что если»: модель пересчитывает прогноз, в БД ничего не пишется.
- **«Качество модели»** — два отчёта: по компаниям, загруженным администратором (пересчитывается в фоне после его
  загрузки или кнопкой; `ml.evaluation.control` на данных из БД), и по датасету участников (`ml-model/reports/control`).

## Тесты

```bash
docker run -d --name seed42-pg-test -e POSTGRES_USER=seed -e POSTGRES_PASSWORD=seed -e POSTGRES_DB=seed \
    -p 127.0.0.1:55432:5432 postgres:16-alpine
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

ML и LLM в тестах бэкенда подменены. Другая база — `TEST_DATABASE_ADMIN_URL=postgresql://user:pass@host:port/db`.

## Соглашения API

- Ответы `/api/*` — обёртка `{localDateTime, methodName, success, data, listErrors}`; `data` прогноза — ответ ML как есть.
- Авторизация — JWT в HttpOnly-куке `access_token`. Внутренние вызовы ML и LLM — с заголовком `X-Internal-Token`.
- Ошибки ML → фронту: 429 `busy` → 429; «нет данных», закрытый счёт → 422 с текстом ML; недоступен → 503.
- В логах только user_id, company_id, путь, статус, время, количества и `X-Request-ID` — без ИНН, сумм и названий.
  Секреты — только из `.env` (в репозитории — `.env.example`).
