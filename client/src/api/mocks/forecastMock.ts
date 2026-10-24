import type {
  ActionDetail, Company, DailyPoint, Forecast, ForecastEvent, ForecastRequest, Gap, Scenario,
} from '@/api/types';
import {
  addDays, addMonths, approxMoney, categoryName, isWeekend, parseIso, percent, shortDate, shortMoney,
} from '@/utils/format';

interface Profile {
  company: Company
  balance: number
  inMean: number
  outMean: number
  sigma: number
  discretionary: { name: string, share: number }[]
  events: ForecastEvent[]
  historyDays: number
}

interface Options {
  threshold: number
  events: ForecastEvent[]
  outFactorUntil?: { factor: number, until: string }
  scenario?: Scenario | null
}

interface Deficit {
  mid: number
  low: number
  high: number
}

interface Assessed {
  daily: DailyPoint[]
  events: ForecastEvent[]
  gapIndex: number
  probability: number
  atGap: Deficit
  total: Deficit
}

const HORIZON_DAYS = 30
const GAP_PROBABILITY = 0.3
const Z_10 = 1.2816
const Z_25 = 0.6745
const OPTIONAL_CATEGORIES = ['capex', 'suppliers', 'marketing']
const IRREGULAR_CONFIDENCE_FACTOR = 0.75

const PERIOD_MONTHS: Record<string, number> = {
  monthly: 1,
  monthly_irregular: 1,
  bimonthly: 2,
  quarterly: 3,
  seasonal: 1,
}

const TAX_COUNTERPARTY = 'Казначейство России (ФНС России)'

const event = (date: string, amount: number, category: string, extra: Partial<ForecastEvent> = {}): ForecastEvent => ({
  date,
  amount,
  category,
  source: 'regular',
  confidence: 1,
  mandatory: amount < 0 && !OPTIONAL_CATEGORIES.includes(category),
  stream_id: `${category}|${date.slice(8)}`,
  ...extra,
})

const PROFILES: Profile[] = [
  {
    company: { companyId: 'C044', companyName: 'Гостиница «Приморье»', companyInn: '0061234401', legalForm: 'ООО', industry: 'Гостиницы' },
    balance: 900_000,
    inMean: 190_000,
    outMean: 175_000,
    sigma: 95_000,
    discretionary: [{ name: 'закупки', share: 0.45 }, { name: 'услуги подрядчиков', share: 0.3 }, { name: 'рекламу', share: 0.25 }],
    historyDays: 480,
    events: [
      event('2026-10-05', -300_000, 'rent', { counterparty_name: 'ООО «Арендодатель-664»', stream_id: 'rent|out', periodicity: 'monthly' }),
      event('2026-10-07', -4_300, 'telecom', { counterparty_name: 'ПАО «Телеком-754»', stream_id: 'telecom|out', periodicity: 'monthly' }),
      event('2026-10-12', -461_000, 'salary_settlement', { stream_id: 'salary_settlement|out', periodicity: 'monthly' }),
      event('2026-10-14', -340_000, 'capex', {
        source: 'manual', mandatory: false, counterparty_name: 'ООО «Кухонное оборудование»',
        stream_id: 'capex-oven|out', label: 'Пароконвектомат',
      }),
      event('2026-10-21', 644_000, 'revenue_client', {
        confidence: 0.7, mandatory: false, counterparty_name: 'ООО «Туроператор Южный берег»', stream_id: 'client-tour|in',
        periodicity: 'seasonal',
      }),
      event('2026-10-27', -300_000, 'salary_advance', { stream_id: 'salary_advance|out', periodicity: 'monthly' }),
      event('2026-10-28', -120_000, 'tax_enp', { counterparty_name: TAX_COUNTERPARTY, stream_id: 'tax_enp|out', periodicity: 'monthly' }),
    ],
  },
  {
    company: { companyId: 'C001', companyName: 'ООО «Грузовик-Логистик»', companyInn: '0061234001', legalForm: 'ООО', industry: 'Грузоперевозки' },
    balance: 2_400_000,
    inMean: 265_000,
    outMean: 245_000,
    sigma: 110_000,
    discretionary: [{ name: 'топливо', share: 0.5 }, { name: 'запчасти', share: 0.3 }, { name: 'рекламу', share: 0.2 }],
    historyDays: 495,
    events: [
      event('2026-10-09', -180_000, 'leasing', { counterparty_name: 'АО «Лизинг-Авто»', stream_id: 'leasing|out', periodicity: 'monthly' }),
      event('2026-10-15', -520_000, 'salary_settlement', { stream_id: 'salary_settlement|out', periodicity: 'monthly' }),
      event('2026-10-20', 900_000, 'revenue_client', {
        confidence: 0.8, mandatory: false, counterparty_name: 'ООО «Опт-Маркет»', stream_id: 'client-opt|in',
        periodicity: 'monthly_irregular',
      }),
      event('2026-10-28', -210_000, 'tax_enp', { counterparty_name: TAX_COUNTERPARTY, stream_id: 'tax_enp|out', periodicity: 'quarterly' }),
      event('2026-10-30', -260_000, 'salary_advance', { stream_id: 'salary_advance|out', periodicity: 'monthly' }),
    ],
  },
  {
    company: { companyId: 'C140', companyName: 'Кофейня «Зерно»', companyInn: '0061234140', legalForm: 'ИП', industry: 'Общепит' },
    balance: 46_000,
    inMean: 104_000,
    outMean: 90_000,
    sigma: 38_000,
    discretionary: [{ name: 'закупки', share: 0.6 }, { name: 'рекламу', share: 0.15 }, { name: 'подписки', share: 0.25 }],
    historyDays: 470,
    events: [
      event('2026-10-01', -81_000, 'tax_enp', {
        overdue_from: '2026-09-28', counterparty_name: TAX_COUNTERPARTY, stream_id: 'tax_enp|out',
      }),
      event('2026-10-05', -80_000, 'salary_settlement', { stream_id: 'salary_settlement|out', periodicity: 'monthly' }),
      event('2026-10-12', -107_000, 'rent', { counterparty_name: 'ИП Арендодатель', stream_id: 'rent|out', periodicity: 'monthly' }),
      event('2026-10-20', -60_000, 'salary_advance', { stream_id: 'salary_advance|out', periodicity: 'monthly' }),
      event('2026-10-28', -78_000, 'tax_enp', { counterparty_name: TAX_COUNTERPARTY, stream_id: 'tax_enp-2|out', periodicity: 'monthly' }),
    ],
  },
  {
    company: { companyId: 'C084', companyName: 'Магазин «Продукты у дома»', companyInn: '0061234084', legalForm: 'ООО', industry: 'Продуктовая розница' },
    balance: -1_700_000,
    inMean: 330_000,
    outMean: 305_000,
    sigma: 120_000,
    discretionary: [{ name: 'закупки', share: 0.7 }, { name: 'рекламу', share: 0.1 }, { name: 'услуги подрядчиков', share: 0.2 }],
    historyDays: 495,
    events: [
      event('2026-10-05', -420_000, 'rent', { counterparty_name: 'ООО «ТЦ Восток»', stream_id: 'rent|out', periodicity: 'monthly' }),
      event('2026-10-10', -380_000, 'salary_settlement', { stream_id: 'salary_settlement|out', periodicity: 'monthly' }),
      event('2026-10-25', -250_000, 'salary_advance', { stream_id: 'salary_advance|out', periodicity: 'monthly' }),
      event('2026-10-28', -189_000, 'tax_enp', { counterparty_name: TAX_COUNTERPARTY, stream_id: 'tax_enp|out', periodicity: 'monthly' }),
    ],
  },
]

export const DEMO_COMPANIES: Company[] = PROFILES.map((profile) => profile.company)

export const DEMO_AS_OF = '2026-09-30'

const round1000 = (value: number) => Math.round(value / 1000) * 1000

const hashCode = (text: string) => {
  let hash = 7
  for (const char of text) {
    hash = (hash * 31 + char.charCodeAt(0)) % 2_147_483_647
  }
  return hash
}

const seededRandom = (seed: number) => {
  let state = seed
  return () => {
    state = (state * 48_271) % 2_147_483_647
    return state / 2_147_483_647
  }
}

const buildProfile = (company: Company, asOf: string): Profile => {
  const random = seededRandom(hashCode(company.companyId) + 1)
  const inMean = round1000(60_000 + random() * 300_000)
  const outMean = round1000(inMean * (0.88 + random() * 0.1))
  const balance = round1000(inMean * (1.5 + random() * 6))
  return {
    company,
    balance,
    inMean,
    outMean,
    sigma: round1000(inMean * 0.4),
    discretionary: [{ name: 'закупки', share: 0.55 }, { name: 'услуги подрядчиков', share: 0.25 }, { name: 'рекламу', share: 0.2 }],
    historyDays: 400,
    events: [
      event(addDays(asOf, 5), -round1000(inMean * 1.4), 'rent', { stream_id: 'rent|out', periodicity: 'monthly' }),
      event(addDays(asOf, 12), -round1000(inMean * 2.2), 'salary_settlement', { stream_id: 'salary_settlement|out', periodicity: 'monthly' }),
      event(addDays(asOf, 20), round1000(inMean * 3), 'revenue_client', {
        confidence: 0.7, mandatory: false, stream_id: 'client|in', periodicity: 'monthly_irregular',
      }),
      event(addDays(asOf, 26), -round1000(inMean * 1.5), 'salary_advance', { stream_id: 'salary_advance|out', periodicity: 'monthly' }),
      event(addDays(asOf, 28), -round1000(inMean * 0.7), 'tax_enp', {
        counterparty_name: TAX_COUNTERPARTY, stream_id: 'tax_enp|out', periodicity: 'monthly',
      }),
    ],
  }
}

const findProfile = (companyId: string, company: Company | undefined, asOf: string) => {
  const known = PROFILES.find((profile) => profile.company.companyId === companyId)
  if (known) {
    return known
  }
  const fallbackCompany: Company = company ?? {
    companyId, companyName: companyId, companyInn: '', legalForm: 'ООО', industry: '',
  }
  return buildProfile(fallbackCompany, asOf)
}

export const mockProfileFlows = (companyId: string, company: Company | undefined, asOf: string) => {
  const profile = findProfile(companyId, company, asOf)
  return { balance: profile.balance, inMean: profile.inMean, outMean: profile.outMean, sigma: profile.sigma }
}

const erf = (x: number) => {
  const sign = x < 0 ? -1 : 1
  const absX = Math.abs(x)
  const t = 1 / (1 + 0.3275911 * absX)
  const polynomial = ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t
  return sign * (1 - polynomial * Math.exp(-absX * absX))
}

const normalCdf = (z: number) => 0.5 * (1 + erf(z / Math.SQRT2))

const seasonOf = (isoDate: string) => Math.floor(((parseIso(isoDate).getMonth() + 1) % 12) / 3)

export const mergeEvents = (base: ForecastEvent[], user: ForecastEvent[]) => {
  const replacedStreams = new Set<string>()
  for (const userEvent of user) {
    if (userEvent.stream_id) {
      replacedStreams.add(userEvent.stream_id)
    }
  }
  const merged: ForecastEvent[] = []
  for (const baseEvent of base) {
    if (!baseEvent.stream_id || !replacedStreams.has(baseEvent.stream_id)) {
      merged.push(baseEvent)
    }
  }
  for (const userEvent of user) {
    merged.push(userEvent)
  }
  return merged.filter((item) => item.amount !== 0).sort((a, b) => a.date.localeCompare(b.date))
}

export const expandPeriodic = (events: ForecastEvent[], asOf: string) => {
  const horizonEnd = addDays(asOf, HORIZON_DAYS)
  const expanded: ForecastEvent[] = []
  for (const item of events) {
    const step = item.periodicity ? PERIOD_MONTHS[item.periodicity] : undefined
    if (!step) {
      expanded.push(item)
      continue
    }
    const season = seasonOf(item.date)
    for (let index = 0; addMonths(item.date, index * step) <= horizonEnd; index++) {
      const date = addMonths(item.date, index * step)
      if (item.periodicity === 'seasonal' && seasonOf(date) !== season) {
        continue
      }
      const isRepeat = index > 0
      const confidence = isRepeat && item.periodicity === 'monthly_irregular'
        ? item.confidence * IRREGULAR_CONFIDENCE_FACTOR
        : item.confidence
      expanded.push({
        ...item,
        date,
        confidence,
        stream_id: isRepeat ? `${item.stream_id}#${index}` : item.stream_id,
      })
    }
  }
  return expanded.sort((a, b) => a.date.localeCompare(b.date))
}

const applyScenario = (events: ForecastEvent[], scenario?: Scenario | null) => {
  if (!scenario) {
    return events
  }
  const result: ForecastEvent[] = []
  for (const item of events) {
    const delay = scenario.delay_counterparty?.[item.stream_id ?? ''] ?? 0
    result.push(delay ? { ...item, date: addDays(item.date, delay) } : item)
  }
  for (const extra of scenario.extra_expenses ?? []) {
    result.push(extra)
  }
  return result
}

const simulate = (profile: Profile, asOf: string, options: Options) => {
  const revenueFactor = options.scenario?.revenue_multiplier ?? 1
  const costFactor = options.scenario?.fixed_cost_multiplier ?? 1
  const events = applyScenario(options.events, options.scenario)
  const turnover = profile.inMean + profile.outMean
  let mean = profile.balance
  let variance = 0
  const daily: DailyPoint[] = []
  for (let dayIndex = 1; dayIndex <= HORIZON_DAYS; dayIndex++) {
    const date = addDays(asOf, dayIndex)
    if (!isWeekend(date)) {
      const outFactor = options.outFactorUntil && date <= options.outFactorUntil.until ? options.outFactorUntil.factor : 1
      mean += profile.inMean * revenueFactor - profile.outMean * costFactor * outFactor
      variance += profile.sigma ** 2
    }
    for (const item of events) {
      if (item.date === date) {
        const confidence = Math.min(1, Math.max(0, item.confidence))
        mean += item.amount * confidence
        variance += item.amount ** 2 * confidence * (1 - confidence)
      }
    }
    const deviation = Math.sqrt(Math.max(variance, 1))
    const width = (2 * Z_10 * deviation) / turnover
    let confidence = 'низкая'
    if (width < 2.5) {
      confidence = 'высокая'
    } else if (width < 5) {
      confidence = 'средняя'
    }
    daily.push({
      date,
      p10: Math.round(mean - Z_10 * deviation),
      p25: Math.round(mean - Z_25 * deviation),
      p50: Math.round(mean),
      p75: Math.round(mean + Z_25 * deviation),
      p90: Math.round(mean + Z_10 * deviation),
      prob_below: normalCdf((options.threshold - mean) / deviation),
      confidence,
    })
  }
  return { daily, events }
}

const horizonProbability = (daily: DailyPoint[]) => {
  let maxProbability = 0
  for (const day of daily) {
    maxProbability = Math.max(maxProbability, day.prob_below ?? 0)
  }
  return Math.min(0.97, maxProbability * 1.1)
}

const deficit = (daily: DailyPoint[], threshold: number): Deficit => {
  let minP10 = daily[0].p10
  let minP25 = daily[0].p25 ?? daily[0].p50
  let minP50 = daily[0].p50
  for (const day of daily) {
    minP10 = Math.min(minP10, day.p10)
    minP25 = Math.min(minP25, day.p25 ?? day.p50)
    minP50 = Math.min(minP50, day.p50)
  }
  const mid = Math.max(0, threshold - minP25)
  return {
    mid,
    low: Math.max(0, threshold - minP50, mid * 0.3),
    high: Math.max(mid * 1.4, threshold - minP10),
  }
}

const assess = (profile: Profile, asOf: string, options: Options): Assessed => {
  const path = simulate(profile, asOf, options)
  const isAlreadyBelow = profile.balance < options.threshold
  const gapIndex = isAlreadyBelow ? 0 : path.daily.findIndex((day) => (day.prob_below ?? 0) >= GAP_PROBABILITY)
  const window = gapIndex >= 0 ? path.daily.slice(gapIndex, gapIndex + 8) : path.daily
  return {
    ...path,
    gapIndex,
    probability: gapIndex >= 0 && isAlreadyBelow ? 1 : horizonProbability(path.daily),
    atGap: deficit(window, options.threshold),
    total: deficit(path.daily, options.threshold),
  }
}

const buildAdvice = (profile: Profile, asOf: string, options: Options, base: Assessed): ActionDetail[] => {
  if (base.gapIndex < 0) {
    return []
  }
  const gapDate = base.daily[base.gapIndex].date
  const windowEnd = addDays(gapDate, 7)
  const horizonEnd = base.daily[base.daily.length - 1].date
  const result: ActionDetail[] = []

  const effect = (alternative: Assessed) => ({
    prob_before: base.probability,
    prob_after: alternative.gapIndex < 0
      ? Math.min(base.probability, horizonProbability(alternative.daily))
      : alternative.probability,
    shortfall_before: round1000(base.atGap.mid),
    shortfall_after: round1000(alternative.gapIndex < 0 ? 0 : alternative.atGap.mid),
    gap_date_after: alternative.gapIndex < 0 ? null : alternative.daily[alternative.gapIndex].date,
  })
  const helps = (detail: ActionDetail) =>
    (detail.prob_before ?? 0) - (detail.prob_after ?? 0) >= 0.1
    || (detail.shortfall_before ?? 0) * 0.8 >= (detail.shortfall_after ?? 0)

  const postponable = base.events
    .filter((item) => item.amount < 0 && !item.mandatory && item.date >= asOf && item.date <= windowEnd)
    .sort((a, b) => a.amount - b.amount)[0]
  if (postponable) {
    const target = addDays(windowEnd, 7) > horizonEnd ? horizonEnd : addDays(windowEnd, 7)
    const moved = options.events.map((item) => (item === postponable ? { ...item, date: target } : item))
    const detail: ActionDetail = {
      type: postponable.category === 'suppliers' ? 'negotiate_supplier' : 'postpone',
      stream_id: postponable.stream_id,
      category: postponable.category,
      counterparty_name: postponable.counterparty_name,
      amount: -postponable.amount,
      date_from: postponable.date,
      date_to: target,
      ...effect(assess(profile, asOf, { ...options, events: moved })),
    }
    if (helps(detail)) {
      result.push(detail)
    }
  }

  const receivable = base.events.find((item) => item.amount > 0 && item.date > gapDate)
  if (receivable) {
    const target = addDays(gapDate, -1)
    const moved = options.events.map((item) => (
      item === receivable ? { ...item, date: target, confidence: item.confidence * 0.9 } : item
    ))
    const detail: ActionDetail = {
      type: 'speed_up_receivable',
      stream_id: receivable.stream_id,
      category: receivable.category,
      counterparty_name: receivable.counterparty_name,
      amount: receivable.amount,
      date_from: receivable.date,
      date_to: target,
      ...effect(assess(profile, asOf, { ...options, events: moved })),
    }
    if (helps(detail)) {
      result.push(detail)
    }
  }

  const workdays = base.daily.filter((day) => day.date <= windowEnd && !isWeekend(day.date)).length
  const cutAmount = round1000(profile.outMean * 0.08 * workdays)
  const cutDetail: ActionDetail = {
    type: 'cut_discretionary',
    amount: cutAmount,
    date_to: windowEnd,
    categories: profile.discretionary.map((category) => ({ name: category.name, amount: round1000(cutAmount * category.share) })),
    ...effect(assess(profile, asOf, { ...options, outFactorUntil: { factor: 0.92, until: windowEnd } })),
  }
  if (helps(cutDetail)) {
    result.push(cutDetail)
  }

  const recovery = base.daily.slice(base.gapIndex).find((day) => day.p50 > options.threshold)
  result.sort((a, b) => (a.prob_after ?? 1) - (b.prob_after ?? 1))
  result.push({
    type: 'overdraft',
    amount: round1000(Math.max(base.total.mid, 10_000)),
    amount_high: round1000(Math.max(base.total.high, 20_000)),
    date_to: recovery?.date ?? horizonEnd,
  })
  return result
}

const effectText = (detail: ActionDetail, horizonEnd: string) => {
  if (detail.gap_date_after === null && (detail.prob_after ?? 1) < 0.15) {
    return `разрыва до ${shortDate(horizonEnd)} скорее всего не будет`
  }
  if ((detail.prob_before ?? 0) - (detail.prob_after ?? 0) < 0.1) {
    return `нехватка уменьшится с ${approxMoney(detail.shortfall_before ?? 0)} до ${approxMoney(detail.shortfall_after ?? 0)}`
  }
  return `риск нехватки снизится с ${percent(detail.prob_before ?? 0)} до ${percent(detail.prob_after ?? 0)}`
}

const actionText = (detail: ActionDetail, horizonEnd: string) => {
  const amount = shortMoney(detail.amount ?? 0)
  const dateFrom = shortDate(detail.date_from ?? horizonEnd)
  const dateTo = shortDate(detail.date_to ?? horizonEnd)
  const counterparty = detail.counterparty_name ? ` (${detail.counterparty_name})` : ''
  if (detail.type === 'postpone') {
    return `Перенесите оплату «${categoryName(detail.category)}»${counterparty} ${amount} с ${dateFrom} на ${dateTo} — `
      + effectText(detail, horizonEnd)
  }
  if (detail.type === 'negotiate_supplier') {
    return `Договоритесь с поставщиком ${detail.counterparty_name ?? ''} о переносе ${amount} с ${dateFrom} на ${dateTo} — `
      + effectText(detail, horizonEnd)
  }
  if (detail.type === 'speed_up_receivable') {
    return `Попросите ${detail.counterparty_name ?? 'клиента'} оплатить ${amount} до ${dateTo} (ожидается ${dateFrom}) — `
      + effectText(detail, horizonEnd)
  }
  if (detail.type === 'cut_discretionary') {
    const names = (detail.categories ?? []).map((category) => category.name).join(', ')
    return `Сократите на 20% ${names} до ${dateTo} (${approxMoney(detail.amount ?? 0)}) — ${effectText(detail, horizonEnd)}`
  }
  return `Чтобы не уйти в минус до ${shortDate(horizonEnd)}, нужен лимит ${approxMoney(detail.amount ?? 0)}, `
    + `с запасом ${approxMoney(detail.amount_high ?? 0)}; понадобится примерно до ${dateTo}`
}

const buildReasons = (profile: Profile, base: Assessed, gapDate: string, windowEnd: string) => {
  const reasons: string[] = []
  if (profile.balance < 0) {
    reasons.push(`Счёт уже в овердрафте: ${shortMoney(profile.balance)}`)
  }
  reasons.push(`С ${shortDate(gapDate)} по ${shortDate(windowEnd)} не хватит ${approxMoney(base.atGap.mid)} `
    + `(от ${shortMoney(base.atGap.low)} до ${shortMoney(base.atGap.high)})`)
  for (const item of base.events) {
    if (item.overdue_from) {
      reasons.push(`${categoryName(item.category)} за ${shortDate(item.overdue_from)} (${approxMoney(-item.amount)}) `
        + `ещё не уплачен — учтён в прогнозе на ${shortDate(item.date)}`)
    }
  }
  const mandatoryNearGap = base.events
    .filter((item) => item.mandatory && item.amount < 0 && !item.overdue_from
      && item.date <= windowEnd && item.date >= addDays(gapDate, -7))
    .sort((a, b) => a.amount - b.amount)
    .slice(0, 3)
  for (const item of mandatoryNearGap) {
    reasons.push(`${categoryName(item.category)} ${shortDate(item.date)} — ${approxMoney(-item.amount)}`)
  }
  const weeklyBalance = (profile.inMean - profile.outMean) * 5
  if (weeklyBalance < 0) {
    reasons.push(`Обычно за неделю списаний больше, чем поступлений, примерно на ${shortMoney(-weeklyBalance)}`)
  }
  return reasons
}

export const mockForecast = (companyId: string, request: ForecastRequest, company?: Company): Forecast => {
  const asOf = request.asOf || DEMO_AS_OF
  const profile = findProfile(companyId, company, asOf)
  const threshold = request.threshold ?? 0
  const events = expandPeriodic(mergeEvents(profile.events, request.events ?? []), asOf)
  const options: Options = { threshold, events, scenario: request.scenario }
  const base = assess(profile, asOf, options)
  const horizonEnd = base.daily[base.daily.length - 1].date

  const gaps: Gap[] = []
  if (base.gapIndex >= 0) {
    const gapDate = base.daily[base.gapIndex].date
    const windowEnd = addDays(gapDate, 7)
    const details = buildAdvice(profile, asOf, options, base)
    gaps.push({
      date: gapDate,
      probability: Math.round(base.probability * 100) / 100,
      shortfall: round1000(base.total.mid),
      shortfall_low: round1000(base.total.low),
      shortfall_high: round1000(base.total.high),
      shortfall_at_gap: round1000(base.atGap.mid),
      shortfall_at_gap_low: round1000(base.atGap.low),
      shortfall_at_gap_high: round1000(base.atGap.high),
      reasons: buildReasons(profile, base, gapDate, windowEnd),
      actions: details.map((detail) => actionText(detail, horizonEnd)),
      actions_detail: details,
    })
  }

  let status: Forecast['status'] = 'ok'
  if (profile.balance < 0) {
    status = 'already_negative'
  } else if (gaps.length > 0) {
    status = 'gap_expected'
  }
  return {
    company_id: profile.company.companyId,
    as_of: asOf,
    model_version: 'demo',
    status,
    balance_now: profile.balance,
    data_quality: {
      history_days: profile.historyDays,
      short_history: false,
      gaps_in_data: 0,
      days_since_last_operation: 0,
      industry_known: true,
    },
    daily: base.daily,
    events: base.events,
    gaps,
  }
}
