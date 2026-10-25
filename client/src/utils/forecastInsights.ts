import type { DailyPoint, Forecast } from '@/api/types';
import {
  approxMoney, categoryName, daysBetween, longDate, naturalFrequency, percent, pluralDays, probabilityLevel, shortDate,
  shortMoney,
} from '@/utils/format';

export type RiskTone = 'ok' | 'warn' | 'bad'

export const balanceNow = (forecast: Forecast) => forecast.balance_now ?? forecast.daily[0]?.p50 ?? 0

export const safeToSpend = (forecast: Forecast, cushion: number) => {
  if (forecast.daily.length === 0) {
    return 0
  }
  let minP10 = forecast.daily[0].p10
  for (const day of forecast.daily) {
    minP10 = Math.min(minP10, day.p10)
  }
  return Math.max(0, Math.min(minP10, balanceNow(forecast)) - cushion)
}

export const runwayDays = (forecast: Forecast, cushion: number) => {
  const firstDayBelow = forecast.daily.find((day) => day.p50 < cushion)
  return firstDayBelow ? daysBetween(forecast.as_of, firstDayBelow.date) : null
}

export const estimateBelow = (day: DailyPoint, level: number) => {
  const p25 = day.p25 ?? (day.p10 + day.p50) / 2
  const p75 = day.p75 ?? (day.p50 + day.p90) / 2
  const points: [number, number][] = [[day.p10, 0.1], [p25, 0.25], [day.p50, 0.5], [p75, 0.75], [day.p90, 0.9]]
  if (level <= day.p10) {
    const spread = Math.max(1, day.p50 - day.p10)
    return Math.max(0, 0.1 * Math.exp((level - day.p10) / (spread / 1.28)))
  }
  if (level >= day.p90) {
    return 0.9 + 0.1 * (1 - Math.exp(-(level - day.p90) / Math.max(1, day.p90 - day.p50)))
  }
  for (let index = 0; index < points.length - 1; index++) {
    const [x0, y0] = points[index]
    const [x1, y1] = points[index + 1]
    if (level >= x0 && level <= x1) {
      return y0 + ((level - x0) / Math.max(1, x1 - x0)) * (y1 - y0)
    }
  }
  return 0.5
}

export const dayRisk = (day: DailyPoint) => day.prob_below ?? estimateBelow(day, 0)

export const riskTone = (risk: number): RiskTone => {
  if (risk >= 0.3) {
    return 'bad'
  }
  if (risk >= 0.1) {
    return 'warn'
  }
  return 'ok'
}

export interface WeekRisk {
  from: string
  to: string
  risk: number
  minP50: number
}

export const weekRisks = (daily: DailyPoint[]): WeekRisk[] => {
  const weeks: WeekRisk[] = []
  for (let start = 0; start < daily.length; start += 7) {
    const chunk = daily.slice(start, start + 7)
    let risk = 0
    let minP50 = chunk[0].p50
    for (const day of chunk) {
      risk = Math.max(risk, dayRisk(day))
      minP50 = Math.min(minP50, day.p50)
    }
    weeks.push({ from: chunk[0].date, to: chunk[chunk.length - 1].date, risk, minP50 })
  }
  return weeks
}

const lowerFirst = (text: string) => `${text.charAt(0).toLowerCase()}${text.slice(1)}`

export const templateSummary = (forecast: Forecast) => {
  const gap = forecast.gaps[0]
  const end = forecast.daily[forecast.daily.length - 1]
  if (forecast.status === 'already_negative' && gap) {
    return `Счёт уже в минусе. До ${shortDate(end.date)} без действий минус сохранится — `
      + `${gap.actions[0] ?? 'нужен кредитный лимит или поступление денег'}.`
  }
  if (forecast.status === 'gap_expected' && gap) {
    const level = probabilityLevel(gap.probability)
    const mainReason = gap.reasons.find((reason) => /—|не уплачен/.test(reason) && !reason.startsWith('С ')) ?? gap.reasons[1]
    const parts = [`${longDate(gap.date)} денег может не хватить — ${level.word} (${naturalFrequency(gap.probability)}).`]
    if (gap.shortfall_at_gap !== undefined) {
      parts.push(`Нужно найти ${approxMoney(gap.shortfall_at_gap)}.`)
    }
    if (mainReason) {
      parts.push(`Главная причина: ${lowerFirst(mainReason)}.`)
    }
    if (gap.actions[0]) {
      parts.push(`Что поможет: ${lowerFirst(gap.actions[0])}.`)
    }
    return parts.join(' ')
  }
  let minDay = forecast.daily[0]
  for (const day of forecast.daily) {
    if (day.p50 < minDay.p50) {
      minDay = day
    }
  }
  const biggestPayment = forecast.events.filter((event) => event.amount < 0).sort((a, b) => a.amount - b.amount)[0]
  const afterPayment = biggestPayment
    ? `, после платежа «${categoryName(biggestPayment.category)}» ${shortDate(biggestPayment.date)}`
    : ''
  return `Денег на ближайшие ${pluralDays(daysBetween(forecast.as_of, end.date))} хватает. `
    + `Меньше всего на счёте будет около ${longDate(minDay.date)} — ${approxMoney(minDay.p50)}${afterPayment}.`
}

export const scenarioTemplate = (base: Forecast, scenario: Forecast, title: string) => {
  const baseGap = base.gaps[0]
  const scenarioGap = scenario.gaps[0]
  if (!baseGap && !scenarioGap) {
    return `${title}: денег всё равно хватает, к концу месяца на счёте будет около `
      + `${shortMoney(scenario.daily[scenario.daily.length - 1].p50)}.`
  }
  if (!baseGap && scenarioGap) {
    return `${title}: появится риск нехватки ${longDate(scenarioGap.date)} (${percent(scenarioGap.probability)}), `
      + `нужно будет найти около ${shortMoney(scenarioGap.shortfall_at_gap ?? scenarioGap.shortfall)}.`
  }
  if (baseGap && !scenarioGap) {
    return `${title}: риск нехватки исчезнет.`
  }
  if (baseGap && scenarioGap) {
    let shift = `останется на ${longDate(scenarioGap.date)}`
    if (scenarioGap.date < baseGap.date) {
      shift = `наступит раньше — ${longDate(scenarioGap.date)}, а не ${longDate(baseGap.date)}`
    } else if (scenarioGap.date > baseGap.date) {
      shift = `сдвинется на ${longDate(scenarioGap.date)}`
    }
    return `${title}: нехватка ${shift}, риск ${percent(baseGap.probability)} → ${percent(scenarioGap.probability)}, `
      + `сумма ${shortMoney(baseGap.shortfall_at_gap ?? baseGap.shortfall)} → `
      + `${shortMoney(scenarioGap.shortfall_at_gap ?? scenarioGap.shortfall)}.`
  }
  return title
}
