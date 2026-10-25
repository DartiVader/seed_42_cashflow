# ML-сервис Seed 42 (шлюз + воркеры)

Реализует `ML_API_CONTRACT.md`. Модули `ml/` не менялись: сервис вызывает `forecast()` и `plan_fact()`.

## Устройство
- `main.py` — FastAPI: токен `X-Internal-Token`, `X-Request-Id`, ошибки `{code, message}`, маршруты `/ml/*`.
- Пул воркеров прогноза (`ML_WORKERS`, процессы spawn): у каждого свой `ForecastContext`. Переполнение очереди
  (`ML_QUEUE_MAX`) → 429, модель не загружена или воркер упал → 503.
- Отдельный пул фоновых задач (`ML_JOB_WORKERS`): `process` и `retrain`; очередь, статусы и прогресс — в `ml_jobs`.
- `store.py` — таблицы `ml_jobs`, `ml_categories`, `ml_streams` в SQLite на volume `/var/lib/ml`.
- `registry.py` — версии `models/<имя>-vN`, метрики, отчёты `reports/*.csv`, переобучение.
- Смена модели (`POST /ml/models/{v}/activate`): воркеры перегружают контекст на ближайшем запросе.

## Запуск
```bash
# из server/
docker build -f service/Dockerfile -t seed42-ml .
docker run -p 8000:8000 -e INTERNAL_TOKEN=... \
  -v $PWD/cashflow_data/cashflow_dataset_participants:/data:ro -v ml-state:/var/lib/ml seed42-ml
```
Пример compose — `docker-compose.example.yml`, переменные — `.env.example`. Память: ~600 МБ на воркер.
Локально: `PYTHONPATH=. uvicorn service.main:app`; тесты: `python -m pytest service/tests`.

## Что пока не так, как в контракте
- Операции для `/forecast` и `/plan-fact`: при `DATABASE_URL` — из PostgreSQL бэкенда функцией
  `get_operations_period(company_id, start, end)` (`db.py`, только чтение); без неё — из CSV (`ML_DATA_DIR`).
  Нет компании ни в БД, ни в CSV → 404; БД недоступна → 503 `db_unavailable`. `process` по-прежнему по датасету.
- Категоризация — правила кода Влада (`category_source = rules`); эмбеддингов и LLM-класса в `ml/` нет.
- Ручная категория сохраняется и отдаётся в `/operations`, но на `forecast()` пока не влияет.
- `counterparty_name` в событиях `/forecast` — `null` (в `ForecastResult` его нет).
- `retrain` запускает `python -m ml.train --events mandatory` в подпроцессе (отчёты — в state/retrain/<job>); не прогонялся целиком.
- Задачи, висевшие в момент рестарта, помечаются `failed` (`service_restarted`).
