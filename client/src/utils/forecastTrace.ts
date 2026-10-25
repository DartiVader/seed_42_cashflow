import type { Forecast } from '@/api/types';
import { categoryName, longDate, percent, shortMoney } from '@/utils/format';

export interface TraceView {
  steps: { step: number, title: string, lines: string[], durationMs?: number }[]
  totalMs: number | null
  /** шаги собраны на фронте из ответа прогноза, а не пришли от ML */
  isTemplate: boolean
}

/** Paths Монте-Карло в ML (ml/forecast/api.py: n_paths=1000) */
const PATHS = 1000

/** Подписи известных ключей values (README_SERVICE.md, таблица шагов); незнакомые ключи не показываем */
const VALUE_LABELS: Record<string, string> = {
  operations: 'Операций в выписке',
  history_days: 'Дней истории',
  gaps_in_data: 'Пропусков в выписке',
  duplicate: 'Дублей',
  own_transfer: 'Переводов между своими счетами',
  founder_financing: 'Денег учредителя',
  error_refund: 'Возвратов ошибочных платежей',
  oneoff_days: 'Дней с разовыми крупными операциями',
  categorized: 'Операций с категорией',
  categories: 'Разных категорий',
  unknown_share: 'Доля «прочее»',
  top: 'Самые частые',
  streams: 'Регулярных платежей',
  mandatory_streams: 'Из них обязательных',
  inflow_streams: 'Регулярных поступлений',
  regular_operations: 'Операций в регулярных платежах',
  regular_share: 'Доля регулярных операций',
  overdue_streams: 'Просроченных регулярных',
  events: 'Событий в календаре',
  mandatory: 'Обязательных',
  from_user: 'Добавлено вами',
  overdue: 'Просроченных',
  inflow_sum: 'Поступления по событиям',
  outflow_sum: 'Списания по событиям',
  expected_net: 'Итого с учётом уверенности',
  left_to_model: 'Оставлено модели',
  model_version: 'Версия модели',
  working_days: 'Рабочих дней в горизонте',
  daily_turnover: 'Обычный дневной оборот',
  irregular_inflow_sum: 'Нерегулярные поступления за горизонт',
  irregular_outflow_sum: 'Нерегулярные списания за горизонт',
  paths: 'Вариантов будущего',
  seed: 'Seed',
  error_pool: 'Ошибки модели — по',
  error_pool_size: 'Размер пула ошибок',
  widen: 'Расширение коридора',
  end_p10: 'Остаток в конце: P10',
  end_p50: 'Остаток в конце: P50',
  end_p90: 'Остаток в конце: P90',
  min_p50: 'Минимум P50',
  threshold: 'Порог (подушка)',
  p_day_min: 'Порог тревоги дня',
  max_p_day: 'Максимум доли провалов за день',
  probability_raw: 'Вероятность до калибровки',
  probability: 'Вероятность разрыва',
  status: 'Итог',
  gap_date: 'Дата разрыва',
  shortfall: 'Может не хватить',
  applied: 'Сценарий применён',
  revenue_multiplier: 'Выручка, множитель',
  fixed_cost_multiplier: 'Постоянные расходы, множитель',
  delayed_counterparties: 'Задержанных контрагентов',
  extra_expenses: 'Дополнительных расходов',
  available: 'Считается в прогнозе',
}

const MONEY_KEYS = new Set(['inflow_sum', 'outflow_sum', 'expected_net', 'daily_turnover', 'irregular_inflow_sum',
  'irregular_outflow_sum', 'end_p10', 'end_p50', 'end_p90', 'min_p50', 'threshold', 'shortfall'])
const SHARE_KEYS = new Set(['unknown_share', 'regular_share', 'p_day_min', 'max_p_day', 'probability_raw', 'probability'])
const VALUE_WORDS: Record<string, string> = {
  industry: 'отрасли', all: 'всем компаниям', ok: 'денег хватает', gap_expected: 'возможен разрыв',
  already_negative: 'счёт уже в минусе', below_cushion: 'ниже подушки',
}

const formatValue = (key: string, value: unknown): string | null => {
  if (value === null || value === undefined) {
    return null
  }
  if (typeof value === 'boolean') {
    return value ? 'да' : 'нет'
  }
  if (typeof value === 'number') {
    if (MONEY_KEYS.has(key)) {
      return shortMoney(value)
    }
    return SHARE_KEYS.has(key) ? percent(value) : value.toLocaleString('ru-RU')
  }
  if (typeof value === 'string') {
    if (key === 'gap_date') {
      return longDate(value)
    }
    return VALUE_WORDS[value] ?? value
  }
  if (key === 'top' && typeof value === 'object') {
    return Object.entries(value as Record<string, number>).slice(0, 5)
      .map(([code, count]) => `${categoryName(code)} ${count}`).join(', ')
  }
  return null
}

const valueLines = (values: Record<string, unknown> | undefined): string[] => Object.entries(values ?? {})
  .filter(([key]) => key in VALUE_LABELS && key !== 'endpoint')
  .map(([key, value]) => {
    const text = formatValue(key, value)
    return text === null ? '' : `${VALUE_LABELS[key]}: ${text}`
  })
  .filter(Boolean)

const fromTrace = (forecast: Forecast): TraceView | null => {
  const trace = forecast.trace
  if (!trace) {
    return null
  }
  const steps = Array.isArray(trace) ? trace : trace.steps
  if (!Array.isArray(steps) || steps.length === 0) {
    return null
  }
  return {
    steps: steps.map((item, index) => ({
      step: item.step ?? index + 1,
      title: item.name,
      lines: valueLines(item.values),
      durationMs: item.ms ?? undefined,
    })),
    totalMs: Array.isArray(trace) ? null : trace.took_ms ?? null,
    isTemplate: false,
  }
}

const fromForecast = (forecast: Forecast): TraceView => {
  const quality = forecast.data_quality ?? {}
  const found = forecast.events.filter((event) => event.source === 'regular' || event.source === 'history')
  const added = forecast.events.length - found.length
  const income = forecast.events.filter((event) => event.amount > 0).reduce((sum, event) => sum + event.amount, 0)
  const outcome = forecast.events.filter((event) => event.amount < 0).reduce((sum, event) => sum + event.amount, 0)
  const categories = [...new Set(found.map((event) => categoryName(event.category)))].slice(0, 5)
  const first = forecast.daily[0]
  const last = forecast.daily[forecast.daily.length - 1]
  const gap = forecast.gaps[0]
  const advice = gap ? gap.actions_detail?.length ?? gap.actions.length : 0

  const steps = [
    {
      title: 'Взяли выписку',
      lines: [
        quality.history_days !== undefined ? `История операций: ${quality.history_days} дн.` : 'История операций из выписки',
        `Дата прогноза: ${longDate(forecast.as_of)}`,
      ],
    },
    {
      title: 'Проверили данные',
      lines: [
        `Пропусков в выписке: ${quality.gaps_in_data ?? 0}`,
        quality.days_since_last_operation !== undefined
          ? `Дней с последней операции: ${quality.days_since_last_operation}` : '',
        quality.short_history ? 'История короткая — разброс прогноза шире' : '',
      ].filter(Boolean),
    },
    {
      title: 'Нашли регулярные платежи',
      lines: [
        `Платежей в календаре на 30 дней: ${found.length}`,
        categories.length > 0 ? `Например: ${categories.join(', ')}` : '',
      ].filter(Boolean),
    },
    {
      title: 'Учли известные и ваши платежи',
      lines: [
        `Всего событий: ${forecast.events.length}${added > 0 ? `, из них добавлено вами или по документам: ${added}` : ''}`,
        `Поступления: ${shortMoney(income, true)}, списания: ${shortMoney(outcome)}`,
        `Итого по событиям: ${shortMoney(income + outcome, true)}`,
      ],
    },
    {
      title: 'Спрогнозировали обычные поступления и списания',
      lines: [`Модель: ${forecast.model_version}`, 'Учитывает день недели, сезон и вашу историю'],
    },
    {
      title: 'Просчитали варианты будущего',
      lines: [`${PATHS.toLocaleString('ru-RU')} вариантов на ${forecast.daily.length} дней вперёд`],
    },
    {
      title: 'Посчитали остаток по дням',
      lines: [
        first ? `Завтра скорее всего: ${shortMoney(first.p50)}` : '',
        last ? `Через 30 дней скорее всего: ${shortMoney(last.p50)}` : '',
        last ? `В 8 случаях из 10 — от ${shortMoney(last.p10)} до ${shortMoney(last.p90)}` : '',
      ].filter(Boolean),
    },
    {
      title: 'Искали нехватку денег',
      lines: gap
        ? [`Вероятность: ${percent(gap.probability)}`, `Дата: ${longDate(gap.date)}`,
          `Может не хватить: ${shortMoney(gap.shortfall)}`]
        : ['Нехватки денег в ближайшие 30 дней не нашли'],
    },
    {
      title: 'Подобрали советы',
      lines: [gap ? `Проверенных пересчётом советов: ${advice}` : 'Советы не нужны: риска нет'],
    },
  ]
  return { steps: steps.map((item, index) => ({ ...item, step: index + 1 })), totalMs: null, isTemplate: true }
}

export const buildTrace = (forecast: Forecast): TraceView => fromTrace(forecast) ?? fromForecast(forecast)

export const formatDuration = (ms: number) => (ms < 1000
  ? `${Math.round(ms)} мс`
  : `${(ms / 1000).toFixed(1).replace('.', ',')} с`)
