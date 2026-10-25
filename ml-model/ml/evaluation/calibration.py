"""Изотоническая калибровка вероятности разрыва: учится на tune-фолдах, проверяется на report."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import isotonic_regression


@dataclass
class Calibrator:
    x: list[float]    # сырая вероятность (узлы, по возрастанию)
    y: list[float]    # откалиброванная
    label: str

    def __call__(self, p):
        return np.interp(p, self.x, self.y)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"x": self.x, "y": self.y, "label": self.label}, indent=1))

    @classmethod
    def load(cls, path: str | Path) -> "Calibrator":
        d = json.loads(Path(path).read_text())
        return cls(d["x"], d["y"], d["label"])


def fit_calibrator(prob: np.ndarray, truth: np.ndarray, label: str) -> Calibrator:
    order = np.argsort(prob, kind="stable")
    p, t = np.asarray(prob)[order], np.asarray(truth, dtype=float)[order]
    fitted = isotonic_regression(t).x
    # одинаковые сырые значения → одно значение (среднее), иначе interp неоднозначен
    df = pd.DataFrame({"p": p, "f": fitted}).groupby("p", as_index=False)["f"].mean()
    x = np.r_[0.0, df["p"].to_numpy(), 1.0]
    y = np.r_[df["f"].iloc[0], df["f"].to_numpy(), df["f"].iloc[-1]]
    return Calibrator(x.tolist(), y.tolist(), label)


def reliability(prob: np.ndarray, truth: np.ndarray, bins=(0, .05, .1, .2, .4, .6, .8, 1.0)) -> pd.DataFrame:
    """Диаграмма надёжности: средняя предсказанная вероятность против фактической частоты."""
    df = pd.DataFrame({"prob": prob, "fact": np.asarray(truth, dtype=float)})
    df["bin"] = pd.cut(df["prob"], list(bins), include_lowest=True)
    return df.groupby("bin", observed=True).agg(n=("fact", "size"), prob_mean=("prob", "mean"),
                                                fact_rate=("fact", "mean")).reset_index()


SHORTFALL_KINDS = ("at_gap", "total")   # shortfall_at_gap и shortfall


@dataclass
class LogIsotonic:
    """Изотоническая регрессия log(прогноз) → log(факт). За краями обучающего диапазона — сдвиг
    на ту же величину, что на крае (сумма больше всех виденных не «упирается» в потолок)."""
    x: list[float]
    y: list[float]

    def __call__(self, v):
        lv = np.log(np.maximum(np.asarray(v, dtype=float), 1.0))
        x, y = np.asarray(self.x), np.asarray(self.y)
        out = np.interp(lv, x, y)
        out = np.where(lv < x[0], lv + (y[0] - x[0]), out)
        out = np.where(lv > x[-1], lv + (y[-1] - x[-1]), out)
        return np.exp(out)


def fit_log_isotonic(pred: np.ndarray, fact: np.ndarray) -> LogIsotonic:
    lp, lf = np.log(np.asarray(pred, dtype=float)), np.log(np.asarray(fact, dtype=float))
    order = np.argsort(lp, kind="stable")
    fitted = isotonic_regression(lf[order]).x
    # один узел на блок isotonic (центр блока по x) и линейная интерполяция между ними: ступеньки
    # дали бы разным компаниям одну и ту же сумму в рублях
    block = np.r_[0, np.cumsum(np.diff(fitted) != 0)]
    df = pd.DataFrame({"x": lp[order], "y": fitted, "b": block}).groupby("b").agg(x=("x", "mean"), y=("y", "first"))
    return LogIsotonic(df["x"].tolist(), df["y"].tolist())


@dataclass
class ShortfallCalibrator:
    """Калибровка двух сумм нехватки; bounds[kind] — сдвигать ли границы вместе с медианой."""
    maps: dict[str, LogIsotonic]
    bounds: dict[str, bool]
    label: str

    def apply(self, kind: str, median, *bounds):
        """Числа или массивы: (медиана, *границы) → то же после калибровки.
        Границы сдвигаются тем же коэффициентом, что и медиана (ширина в log сохраняется), если
        bounds[kind]; иначе остаются сырыми и только расширяются до медианы."""
        f = self.maps.get(kind)
        if f is None:
            return (median, *bounds)
        m = f(median)
        if self.bounds.get(kind, False):
            k = m / np.maximum(median, 1.0)
            return (m, *(b * k for b in bounds))
        # пары (нижняя, верхняя): медиана должна остаться внутри
        out = [m]
        for i, b in enumerate(bounds):
            out.append(np.minimum(b, m) if i % 2 == 0 else np.maximum(b, m))
        return tuple(out)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({
            "label": self.label, "bounds": self.bounds,
            "maps": {k: {"x": v.x, "y": v.y} for k, v in self.maps.items()}}, indent=1))

    @classmethod
    def load(cls, path: str | Path) -> "ShortfallCalibrator":
        d = json.loads(Path(path).read_text())
        return cls({k: LogIsotonic(v["x"], v["y"]) for k, v in d["maps"].items()}, d["bounds"], d["label"])
