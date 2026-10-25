/** Подписи метрик и значений отчёта — для предпринимателя, без жаргона. */
import type { QualityMetrics } from '@/api/types';

export type Target = 'shortfall' | 'negative'

/** Метки правды отчёта ml.evaluation.control: CF (основная) и strict */
export const TARGETS: { value: Target, label: string }[] = [
  { value: 'shortfall', label: 'Минус без денег владельца (основная)' },
  { value: 'negative', label: 'Фактический минус на счёте' },
]

export type Segment = 'all' | 'holdout'

export const SEGMENTS: { value: Segment, label: string }[] = [
  { value: 'all', label: 'Все компании' },
  { value: 'holdout', label: 'Новые для модели (холдаут)' },
]

export const METRICS: { key: keyof Omit<QualityMetrics, 'confusion'>, label: string, hint: string, kind: 'share' | 'score' }[] = [
  { key: 'accuracy', label: 'Accuracy', hint: 'Доля верных ответов «будет / не будет нехватки»', kind: 'share' },
  { key: 'precision', label: 'Precision', hint: 'Сколько предупреждений оправдались', kind: 'share' },
  { key: 'recall', label: 'Recall', hint: 'Сколько реальных проблем сервис заметил заранее', kind: 'share' },
  { key: 'f1', label: 'F1', hint: 'Баланс точности и полноты: чем ближе к 100%, тем лучше', kind: 'share' },
  { key: 'roc_auc', label: 'ROC-AUC', hint: 'Насколько хорошо сервис отличает рискованные ситуации: 0,5 — наугад, 1 — идеально', kind: 'score' },
  { key: 'brier', label: 'Brier', hint: 'Ошибка вероятностей: чем меньше, тем честнее проценты', kind: 'score' },
]

export const MODEL_NAMES: Record<string, string> = {
  naive_s5: 'Как неделю назад (naive_s5)',
  dow_mean: 'Среднее по дню недели (dow_mean)',
  zero: 'Без изменений (zero)',
  ets: 'Сглаживание (ets)',
  lgbm: 'Наша модель (lgbm)',
  lgbm_net: 'Наша модель (lgbm_net)',
  'v2 P50': 'Наша модель (P50)',
}

export const COLUMN_NAMES: Record<string, string> = {
  model: 'Модель',
  horizon: 'Горизонт, дн.',
  mae: 'MAE',
  mse: 'MSE',
  rmse: 'RMSE',
  coverage_p10_p90: 'Покрытие P10–P90',
  mae_d1: 'MAE, 1 день',
  mae_d7: 'MAE, 7 дней',
  mae_d14: 'MAE, 14 дней',
  mae_d30: 'MAE, 30 дней',
  precision: 'Precision',
  recall: 'Recall',
  f1: 'F1',
  brier: 'Brier',
  roc_auc: 'ROC-AUC',
}

export const IMAGE_CAPTIONS: [RegExp, string][] = [
  [/confusion/i, 'Матрицы ошибок: предупредили и было, ложные тревоги, пропуски'],
  [/threshold/i, 'Как точность и полнота предупреждений зависят от порога тревоги'],
  [/reliab/i, 'Надёжность вероятностей: когда сервис говорит «60%», проблема случается примерно в 60% случаев'],
  [/compan|example/i, 'Примеры компаний: прогноз и то, что было на самом деле'],
  [/horizon/i, 'Ошибка прогноза в зависимости от горизонта'],
  [/pr|precision/i, 'Точность и полнота предупреждений'],
]

const shareFormat = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 })
const scoreFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })

export const formatShare = (value: number) => shareFormat.format(value)
export const formatScore = (value: number) => scoreFormat.format(value)

export const imageCaption = (name: string) =>
  IMAGE_CAPTIONS.find(([pattern]) => pattern.test(name))?.[1] ?? name.replace(/\.png$/, '').replace(/[_-]/g, ' ')
