# ML-сервис Seed 42. Контекст сборки — каталог server/ (нужны ml/, models/, reports/):
#   docker build -f service/Dockerfile -t seed42-ml server
# Данные (statements/*.csv, companies.csv) в образ не входят — монтируются в /data.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    ML_DATA_DIR=/data \
    ML_MODELS_DIR=/app/models \
    ML_REPORTS_DIR=/app/reports \
    ML_STATE_DIR=/var/lib/ml

# libgomp — рантайм OpenMP для LightGBM
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /app ml \
    && mkdir -p /var/lib/ml /data && chown ml /var/lib/ml

WORKDIR /app
COPY service/requirements.txt service/requirements.txt
RUN pip install -r service/requirements.txt

COPY ml ml
COPY service service
COPY models models
# отчёты для /ml/reports и /ml/models; остаток backtest нужен версиям v1
COPY reports/*.csv reports/backtest_residuals.parquet reports/

# исходники из хоста бывают с правами 700 (ml/pipeline/vlad) — сервис работает не от root; битый импорт роняет сборку
RUN chmod -R a+rX /app && python -c "import service.main, ml.train" && python -c "import ml.pipeline.regular" \
    && chown -R ml /app/models

USER ml
VOLUME ["/var/lib/ml"]
EXPOSE 8000

# модель грузится ~7 с на воркер, поэтому большой start-period
HEALTHCHECK --interval=15s --timeout=3s --start-period=90s --retries=3 \
    CMD python -c "import json,sys,urllib.request as u; sys.exit(0 if json.load(u.urlopen('http://127.0.0.1:8000/ml/health', timeout=2))['status']=='ok' else 1)"

# один процесс: воркеры (ML_WORKERS) он порождает сам, поэтому --workers у uvicorn не задаём
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
