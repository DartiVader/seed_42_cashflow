import numpy as np
import pandas as pd
import pytest

from ml.data.calendar import working_days
from ml.evaluation.splits import holdout_companies
from ml.forecast.models import DowMean, LgbmConfig, LgbmFlow, SeasonalNaive
from ml.forecast.panel import build_panel
from ml.pipeline.clean import clean_operations
from ml.tests.conftest import make_companies, make_ops, rebalance

HORIZON = 23


def small_lgbm() -> LgbmFlow:
    cfg = LgbmConfig(num_boost_round=30)
    cfg.params.update(min_data_in_leaf=20, num_leaves=15)
    return LgbmFlow(cfg)


def panel_of(ops):
    return build_panel(clean_operations(ops), make_companies(ops))


def fit_predict(model, panel, as_of):
    model.fit(panel, as_of)
    return model.predict(panel, as_of, HORIZON).sort_values(["company_id", "h"]).reset_index(drop=True)


def small_lgbm_full() -> LgbmFlow:
    m = small_lgbm()
    m.config.feature_set = "balance_last_year"      # эксперимент 8.1 + 8.2
    return m


@pytest.mark.parametrize("make_model", [SeasonalNaive, DowMean, small_lgbm, small_lgbm_full])
def test_no_leakage_future_changes_do_not_change_forecast(synthetic, make_model):
    ops, _ = synthetic
    as_of = working_days("2025-01-09", "2026-12-31")[220]
    future = ops["operation_date"] > as_of
    changed = ops.copy()
    changed.loc[future, "amount"] *= 3.0
    changed = rebalance(changed)

    a = fit_predict(make_model(), panel_of(ops), as_of)
    b = fit_predict(make_model(), panel_of(changed), as_of)
    pd.testing.assert_frame_equal(a, b)
    assert (a["target_date"] > as_of).all() and len(a) == 3 * HORIZON


def test_lgbm_is_deterministic(synthetic):
    ops, _ = synthetic
    panel = panel_of(ops)
    as_of = panel["date"].iloc[240]
    a = fit_predict(small_lgbm(), panel, as_of)
    b = fit_predict(small_lgbm(), panel, as_of)
    pd.testing.assert_frame_equal(a, b)


def test_lgbm_save_load_roundtrip(synthetic, tmp_path):
    panel = panel_of(synthetic[0])
    as_of = panel["date"].iloc[240]
    m = small_lgbm()
    m.fit(panel, as_of)
    m.save(tmp_path / "m")
    a = m.predict(panel, as_of, HORIZON)
    b = LgbmFlow.load(tmp_path / "m").predict(panel, as_of, HORIZON)
    np.testing.assert_allclose(a["in_hat"], b["in_hat"])


def test_lgbm_net_save_load_roundtrip(synthetic, tmp_path):
    from ml.forecast.models import LgbmNet, load_model

    panel = panel_of(synthetic[0])
    as_of = panel["date"].iloc[240]
    m = LgbmNet(small_lgbm().config)
    m.fit(panel, as_of)
    m.save(tmp_path / "net")
    loaded = load_model(tmp_path / "net")
    assert isinstance(loaded, LgbmNet)
    a, b = m.predict(panel, as_of, HORIZON), loaded.predict(panel, as_of, HORIZON)
    np.testing.assert_allclose(a[["in_hat", "out_hat"]], b[["in_hat", "out_hat"]])
    with pytest.raises(ValueError, match="lgbm_net"):
        LgbmFlow.load(tmp_path / "net")      # резервная версия не должна молча подхватить чужой каталог


def test_short_history_company_gets_forecast(synthetic):
    ops, _ = synthetic
    short = make_ops(company_ids=("C009",), start="2025-11-20", n_days=15, seed=3)
    ops = pd.concat([ops, short], ignore_index=True)
    panel = panel_of(ops)
    as_of = panel.loc[panel["company_id"] == "C009", "date"].max()
    for model in (SeasonalNaive(), DowMean(), small_lgbm()):
        model.fit(panel[panel["company_id"] != "C009"], as_of)
        pred = model.predict(panel, as_of, HORIZON)
        p = pred[pred["company_id"] == "C009"]
        assert len(p) == HORIZON
        assert np.isfinite(p[["in_hat", "out_hat"]]).all().all()
        assert (p[["in_hat", "out_hat"]] >= 0).all().all()


def test_holdout_is_stratified_and_reproducible(synthetic):
    _, companies = synthetic
    a = holdout_companies(companies, seed=42)
    assert a == holdout_companies(companies, seed=42)
    assert companies.set_index("company_id").loc[a, "industry"].nunique() == len(a)


def test_lgbm_net_daily_flows_add_up_to_net_forecast(synthetic):
    from ml.forecast.models import LgbmNet
    from ml.forecast.models.lgbm_net import reconcile

    panel = panel_of(synthetic[0])
    as_of = panel["date"].iloc[240]
    cfg = small_lgbm().config
    m = LgbmNet(cfg)
    m.fit(panel, as_of)
    pred = m.predict(panel, as_of, HORIZON)
    assert (pred[["in_hat", "out_hat"]] >= 0).all().all()

    rows = pred[["company_id", "as_of"]].reset_index(drop=True)
    rng = np.random.default_rng(1)
    in_hat, out_hat = rng.uniform(0, 10, len(rows)), rng.uniform(0, 10, len(rows))
    cum = np.tile(np.arange(1, HORIZON + 1) * -3.0, len(rows) // HORIZON)
    i2, o2 = reconcile(rows, in_hat, out_hat, cum)
    got = pd.Series(i2 - o2).groupby([rows["company_id"], rows["as_of"]]).cumsum().to_numpy()
    np.testing.assert_allclose(got, cum)
    assert (i2 >= 0).all() and (o2 >= 0).all()

