import json
from pathlib import Path

from ml.forecast.models.base import FlowModel, RowModel
from ml.forecast.models.dow import DowMean
from ml.forecast.models.ets import EtsFlow
from ml.forecast.models.lgbm import LgbmConfig, LgbmFlow
from ml.forecast.models.lgbm_net import LgbmNet
from ml.forecast.models.naive import SeasonalNaive
from ml.forecast.models.zero import ZeroFlow

MODELS = {
    ZeroFlow.name: ZeroFlow,
    SeasonalNaive.name: SeasonalNaive,
    DowMean.name: DowMean,
    EtsFlow.name: EtsFlow,
    LgbmFlow.name: LgbmFlow,
    LgbmNet.name: LgbmNet,
}


def load_model(path: str | Path) -> LgbmFlow:
    """Загружает сохранённую версию; класс берётся из meta.json."""
    name = json.loads((Path(path) / "meta.json").read_text(encoding="utf-8"))["name"]
    return MODELS[name].load(path)


__all__ = ["FlowModel", "RowModel", "DowMean", "EtsFlow", "LgbmConfig", "LgbmFlow", "LgbmNet", "SeasonalNaive", "ZeroFlow", "MODELS", "load_model"]
