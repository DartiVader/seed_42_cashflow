PY ?= .venv/bin/python
BUNDLE := dist/ml_bundle

.PHONY: bundle test

# Всё, что нужно ForecastContext.load, кроме данных: реестр моделей и ошибки backtest для версий v1
bundle:
	rm -rf $(BUNDLE)
	mkdir -p $(BUNDLE)/reports
	cp -r models $(BUNDLE)/models
	cp reports/backtest_residuals.parquet $(BUNDLE)/reports/
	cp requirements.txt ml/README_SERVICE.md $(BUNDLE)/
	cd $(BUNDLE) && find . -type f ! -name MANIFEST.sha256 | sort | xargs sha256sum > MANIFEST.sha256
	@du -sh $(BUNDLE) && du -sh $(BUNDLE)/* $(BUNDLE)/models/*

test:
	$(PY) -m pytest -q ml/tests
