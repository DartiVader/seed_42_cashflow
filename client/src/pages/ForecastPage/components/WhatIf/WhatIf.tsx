import { useState } from 'react';
import Button from '@/components/Button';
import Card from '@/components/Card';
import Chip from '@/components/Chip';
import type { Explanation, Forecast, ForecastEvent, Scenario } from '@/api/types';
import { addDays, categoryName, longDate, percent, shortDate, shortMoney } from '@/utils/format';
import BalanceChart from '@/pages/ForecastPage/components/BalanceChart';
import styles from './WhatIf.module.css';

const DELAY_OPTIONS = [0, 7, 14, 21, 28]
const HORIZON_DAYS = 30

interface ForecastSummary {
  gapDate: string
  risk: string
  shortfall: string
  min: string
  end: string
}

const summarize = (forecast: Forecast): ForecastSummary => {
  const gap = forecast.gaps[0]
  let minDay = forecast.daily[0]
  for (const day of forecast.daily) {
    if (day.p50 < minDay.p50) {
      minDay = day
    }
  }
  return {
    gapDate: gap ? longDate(gap.date) : 'нет',
    risk: gap ? percent(gap.probability) : '—',
    shortfall: gap?.shortfall_at_gap !== undefined ? shortMoney(gap.shortfall_at_gap) : '—',
    min: `${shortMoney(minDay.p50)} (${shortDate(minDay.date)})`,
    end: shortMoney(forecast.daily[forecast.daily.length - 1].p50),
  }
}

interface Preset {
  title: string
  scenario: Scenario
  description: string
}

const buildPresets = (base: Forecast, inflows: ForecastEvent[]): Preset[] => {
  const presets: Preset[] = [
    { title: 'Выручка −30%', scenario: { revenue_multiplier: 0.7 }, description: 'Если выручка упадёт на 30%' },
  ]
  const firstInflow = inflows[0]
  if (firstInflow?.stream_id) {
    const client = firstInflow.counterparty_name ?? 'Клиент'
    presets.push({
      title: `${client} задержит оплату на 3 недели`,
      scenario: { delay_counterparty: { [firstInflow.stream_id]: 21 } },
      description: `Если ${client} заплатит на 3 недели позже`,
    })
  }
  presets.push({
    title: 'Сломалось оборудование: −200 тыс. через неделю',
    scenario: {
      extra_expenses: [{
        date: addDays(base.as_of, 7), amount: -200_000, category: 'capex', source: 'manual', confidence: 1,
        mandatory: true, stream_id: 'scenario-repair', label: 'Срочный ремонт',
      }],
    },
    description: 'Если через неделю придётся потратить 200 тыс. на ремонт',
  })
  presets.push({ title: 'Аренда и закупки +15%', scenario: { fixed_cost_multiplier: 1.15 }, description: 'Если расходы вырастут на 15%' })
  return presets
}

interface WhatIfProps {
  base: Forecast
  scenarioForecast: Forecast | null
  isLoading: boolean
  cushion: number
  explanation: Explanation
  title: string | null
  onRun: (scenario: Scenario, title: string) => void
  onClear: () => void
}

const WhatIf = ({ base, scenarioForecast, isLoading, cushion, explanation, title, onRun, onClear }: WhatIfProps) => {
  const inflows = base.events.filter((item) => item.amount > 0 && item.stream_id)
  const [revenue, setRevenue] = useState(0)
  const [costs, setCosts] = useState(0)
  const [delayStream, setDelayStream] = useState(inflows[0]?.stream_id ?? '')
  const [delayDays, setDelayDays] = useState(0)
  const [extraAmount, setExtraAmount] = useState('')
  const [extraDate, setExtraDate] = useState(addDays(base.as_of, 7))

  const runCustom = () => {
    const parts: string[] = []
    const scenario: Scenario = {}
    if (revenue !== 0) {
      scenario.revenue_multiplier = 1 + revenue / 100
      parts.push(`выручка ${revenue > 0 ? '+' : ''}${revenue}%`)
    }
    if (costs !== 0) {
      scenario.fixed_cost_multiplier = 1 + costs / 100
      parts.push(`расходы +${costs}%`)
    }
    if (delayStream && delayDays > 0) {
      scenario.delay_counterparty = { [delayStream]: delayDays }
      const inflow = inflows.find((item) => item.stream_id === delayStream)
      parts.push(`${inflow?.counterparty_name ?? 'клиент'} платит на ${delayDays} дн. позже`)
    }
    const amount = Number(extraAmount)
    if (amount > 0) {
      scenario.extra_expenses = [{
        date: extraDate, amount: -amount, category: 'other', source: 'manual', confidence: 1,
        mandatory: false, stream_id: 'scenario-extra', label: 'Непредвиденный расход',
      }]
      parts.push(`расход ${shortMoney(amount)} ${shortDate(extraDate)}`)
    }
    onRun(scenario, parts.length > 0 ? `Если ${parts.join(', ')}` : 'Без изменений')
  }

  const current = summarize(base)
  const changed = scenarioForecast ? summarize(scenarioForecast) : null

  return (
    <div className={styles.layout}>
      <Card
        title="Что будет, если…"
        subtitle="Выберите готовую ситуацию или настройте свою. Ваш текущий прогноз не изменится — сценарий показывается рядом."
        tour="whatif-controls"
      >
        <div className={styles.presets}>
          {buildPresets(base, inflows).map((preset) => (
            <Chip key={preset.title} onClick={() => onRun(preset.scenario, preset.description)}>{preset.title}</Chip>
          ))}
        </div>
        <div className={styles.controls}>
          <label>
            Выручка: <b>{revenue > 0 ? '+' : ''}{revenue}%</b>
            <input type="range" min={-50} max={20} step={5} value={revenue} onChange={(event) => setRevenue(Number(event.target.value))} />
          </label>
          <label>
            Аренда, закупки и прочие расходы: <b>+{costs}%</b>
            <input type="range" min={0} max={40} step={5} value={costs} onChange={(event) => setCosts(Number(event.target.value))} />
          </label>
          {inflows.length > 0 && (
            <label>
              Задержка оплаты клиента
              <span className={styles.row}>
                <select value={delayStream} onChange={(event) => setDelayStream(event.target.value)}>
                  {inflows.map((item) => (
                    <option key={item.stream_id} value={item.stream_id ?? ''}>
                      {item.counterparty_name ?? categoryName(item.category)} · {shortMoney(item.amount)} · {shortDate(item.date)}
                    </option>
                  ))}
                </select>
                <select value={delayDays} onChange={(event) => setDelayDays(Number(event.target.value))}>
                  {DELAY_OPTIONS.map((days) => <option key={days} value={days}>{days ? `на ${days} дн.` : 'без задержки'}</option>)}
                </select>
              </span>
            </label>
          )}
          <label>
            Непредвиденный расход
            <span className={styles.row}>
              <input
                type="number"
                min={0}
                step={10000}
                placeholder="сумма, ₽"
                value={extraAmount}
                onChange={(event) => setExtraAmount(event.target.value)}
              />
              <input
                type="date"
                value={extraDate}
                min={addDays(base.as_of, 1)}
                max={addDays(base.as_of, HORIZON_DAYS)}
                onChange={(event) => setExtraDate(event.target.value)}
              />
            </span>
          </label>
        </div>
        <div className={styles.row}>
          <Button onClick={runCustom} disabled={isLoading}>{isLoading ? 'Считаю…' : 'Посчитать сценарий'}</Button>
          {scenarioForecast && <Button variant="ghost" onClick={onClear}>Убрать сценарий</Button>}
        </div>
      </Card>

      <Card title={title ?? 'Сейчас'}>
        <BalanceChart forecast={base} scenario={scenarioForecast} cushion={cushion} />
        {changed && (
          <>
            <p className={styles.explanation}>{explanation.text}</p>
            <table className={styles.compare}>
              <thead>
                <tr><th /><th>Сейчас</th><th>При сценарии</th></tr>
              </thead>
              <tbody>
                <tr><td>Первая нехватка</td><td>{current.gapDate}</td><td>{changed.gapDate}</td></tr>
                <tr><td>Риск</td><td>{current.risk}</td><td>{changed.risk}</td></tr>
                <tr><td>Нужно найти к этой неделе</td><td>{current.shortfall}</td><td>{changed.shortfall}</td></tr>
                <tr><td>Минимум на счёте</td><td>{current.min}</td><td>{changed.min}</td></tr>
                <tr><td>Через 30 дней</td><td>{current.end}</td><td>{changed.end}</td></tr>
              </tbody>
            </table>
          </>
        )}
      </Card>
    </div>
  )
}

export default WhatIf
