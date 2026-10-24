import type { Company, PlanFact, PlanFactDay, PlanFactEvent } from '@/api/types';
import { mockProfileFlows } from '@/api/mocks/forecastMock';
import { addDays, isWeekend } from '@/utils/format';

interface Story {
  drift: number
  noise: number
  events: PlanFactEvent[]
}

const DEFAULT_LOOKBACK_DAYS = 10
const Z_10 = 1.28

const STORIES: Record<string, Story> = {
  C044: {
    drift: 12_000,
    noise: 70_000,
    events: [
      { date: '2026-09-21', category: 'utilities', amount_plan: -58_000, amount_fact: -61_200, status: 'paid', days_late: 0, stream_id: 'utilities|out' },
      {
        date: '2026-09-25', category: 'revenue_client', amount_plan: 420_000, amount_fact: null, status: 'missed', days_late: 3,
        stream_id: 'client-booking|in', counterparty_name: 'ООО «Бронирование Юг»',
      },
      { date: '2026-09-28', category: 'tax_enp', amount_plan: -118_000, amount_fact: -118_000, status: 'paid', days_late: 0, stream_id: 'tax_enp|out' },
      {
        date: '2026-09-29', category: 'revenue_client', amount_plan: 260_000, amount_fact: 150_000, status: 'partial', days_late: 0,
        stream_id: 'client-corp|in', counterparty_name: 'АО «Делегация»',
      },
    ],
  },
  C001: {
    drift: 18_000,
    noise: 90_000,
    events: [
      { date: '2026-09-22', category: 'revenue_client', amount_plan: 640_000, amount_fact: 640_000, status: 'paid', days_late: 0, stream_id: 'client-opt|in' },
      { date: '2026-09-25', category: 'leasing', amount_plan: -180_000, amount_fact: -180_000, status: 'paid', days_late: 0, stream_id: 'leasing|out' },
      { date: '2026-09-28', category: 'tax_enp', amount_plan: -205_000, amount_fact: -209_000, status: 'paid', days_late: 0, stream_id: 'tax_enp|out' },
    ],
  },
  C140: {
    drift: 9_000,
    noise: 22_000,
    events: [
      { date: '2026-09-21', category: 'salary_advance', amount_plan: -60_000, amount_fact: -60_000, status: 'paid', days_late: 0, stream_id: 'salary_advance|out' },
      { date: '2026-09-28', category: 'tax_enp', amount_plan: -81_000, amount_fact: null, status: 'missed', days_late: 2, stream_id: 'tax_enp|out' },
    ],
  },
  C084: {
    drift: 15_000,
    noise: 110_000,
    events: [
      { date: '2026-09-25', category: 'salary_advance', amount_plan: -250_000, amount_fact: -250_000, status: 'paid', days_late: 0, stream_id: 'salary_advance|out' },
      { date: '2026-09-28', category: 'tax_enp', amount_plan: -189_000, amount_fact: null, status: 'missed', days_late: 2, stream_id: 'tax_enp|out' },
    ],
  },
}

const round1000 = (value: number) => Math.round(value / 1000) * 1000

const deterministicNoise = (seed: number) => {
  const value = Math.sin(seed * 9301 + 49297) * 233280
  return value - Math.floor(value) - 0.5
}

const previousWorkday = (isoDate: string) => {
  let date = addDays(isoDate, -1)
  while (isWeekend(date)) {
    date = addDays(date, -1)
  }
  return date
}

const workdaysBefore = (asOf: string, count: number) => {
  const dates: string[] = []
  let date = asOf
  while (dates.length < count) {
    if (!isWeekend(date)) {
      dates.unshift(date)
    }
    date = addDays(date, -1)
  }
  return dates
}

const buildStory = (inMean: number, outMean: number, sigma: number, dates: string[]): Story => ({
  drift: round1000((inMean - outMean) * 0.6),
  noise: round1000(sigma * 0.7),
  events: [
    {
      date: dates[1], category: 'rent', amount_plan: -round1000(inMean * 1.4), amount_fact: -round1000(inMean * 1.4),
      status: 'paid', days_late: 0, stream_id: 'rent|out',
    },
    {
      date: dates[4], category: 'revenue_client', amount_plan: round1000(inMean * 2.5), amount_fact: round1000(inMean * 1.2),
      status: 'partial', days_late: 0, stream_id: 'client|in',
    },
    {
      date: dates[7], category: 'tax_enp', amount_plan: -round1000(inMean * 0.7), amount_fact: -round1000(inMean * 0.7),
      status: 'paid', days_late: 0, stream_id: 'tax_enp|out',
    },
  ],
})

const sumOnDate = (events: PlanFactEvent[], date: string, key: 'amount_plan' | 'amount_fact') => {
  let sum = 0
  for (const item of events) {
    if (item.date === date) {
      sum += item[key] ?? 0
    }
  }
  return sum
}

export const mockPlanFact = (
  companyId: string,
  asOf: string,
  company?: Company,
  lookbackDays = DEFAULT_LOOKBACK_DAYS,
): PlanFact => {
  const dates = workdaysBefore(asOf, lookbackDays)
  const flows = mockProfileFlows(companyId, company, asOf)
  const story = STORIES[companyId] ?? buildStory(flows.inMean, flows.outMean, flows.sigma, dates)

  const factFlows: number[] = []
  let totalFactFlow = 0
  dates.forEach((date, index) => {
    const flow = story.drift + story.noise * 0.8 * deterministicNoise(index + companyId.length) + sumOnDate(story.events, date, 'amount_fact')
    factFlows.push(flow)
    totalFactFlow += flow
  })

  const startBalance = flows.balance - totalFactFlow
  let plan = startBalance
  let fact = startBalance
  let maxDeviation = 0
  const daily: PlanFactDay[] = []
  dates.forEach((date, index) => {
    plan += story.drift + sumOnDate(story.events, date, 'amount_plan')
    fact += factFlows[index]
    const spread = story.noise * Math.sqrt(index + 1) * Z_10
    maxDeviation = Math.max(maxDeviation, Math.abs(fact - plan))
    daily.push({
      date,
      plan_p10: plan - spread,
      plan_p50: plan,
      plan_p90: plan + spread,
      fact,
      outside: fact < plan - spread || fact > plan + spread,
    })
  })

  let missedIn = 0
  let missedOut = 0
  for (const item of story.events) {
    if (item.status === 'paid') {
      continue
    }
    if (item.amount_plan > 0) {
      missedIn += item.amount_plan - (item.amount_fact ?? 0)
    } else {
      missedOut += (item.amount_fact ?? 0) - item.amount_plan
    }
  }

  return {
    as_of_plan: previousWorkday(dates[0]),
    as_of: asOf,
    daily,
    events: story.events,
    summary: { missed_in: missedIn, missed_out: missedOut, max_deviation: maxDeviation },
  }
}
