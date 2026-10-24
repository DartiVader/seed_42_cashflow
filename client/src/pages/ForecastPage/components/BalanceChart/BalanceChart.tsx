import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import type { Forecast } from '@/api/types';
import { dayRisk } from '@/utils/forecastInsights';
import { shortDate, shortMoney } from '@/utils/format';
import ChartTooltip, { type ChartRow } from '@/pages/ForecastPage/components/ChartTooltip';
import styles from './BalanceChart.module.css';

const COLORS = {
  band: 'var(--color-primary)',
  line: 'var(--color-brand-700)',
  scenario: 'var(--color-scenario)',
  danger: 'var(--color-danger)',
  warning: 'var(--color-warning)',
  income: 'var(--color-primary)',
  grid: 'var(--color-border)',
  axis: 'var(--color-text-muted)',
  surface: 'var(--color-surface)',
}

const BIG_EVENTS_LIMIT = 6

interface BalanceChartProps {
  forecast: Forecast
  cushion: number
  scenario?: Forecast | null
}

const buildRows = (forecast: Forecast, scenario: Forecast | null | undefined): ChartRow[] => {
  const scenarioByDate = new Map((scenario?.daily ?? []).map((day) => [day.date, day]))
  return forecast.daily.map((day) => {
    const scenarioDay = scenarioByDate.get(day.date)
    return {
      date: day.date,
      label: shortDate(day.date),
      outer: [day.p10, day.p90],
      inner: [day.p25 ?? (day.p10 + day.p50) / 2, day.p75 ?? (day.p50 + day.p90) / 2],
      p50: day.p50,
      scenario: scenarioDay?.p50,
      scenarioOuter: scenarioDay ? [scenarioDay.p10, scenarioDay.p90] : undefined,
      risk: dayRisk(day),
      confidence: day.confidence,
      events: forecast.events.filter((item) => item.date === day.date),
      point: day,
    }
  })
}

const eventColor = (amount: number, mandatory: boolean | undefined) => {
  if (amount > 0) {
    return COLORS.income
  }
  return mandatory ? COLORS.danger : COLORS.warning
}

const BalanceChart = ({ forecast, cushion, scenario }: BalanceChartProps) => {
  const rows = buildRows(forecast, scenario)
  const gap = forecast.gaps[0]
  const bigEvents = forecast.events
    .filter((item) => item.amount !== 0 && rows.some((row) => row.date === item.date))
    .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))
    .slice(0, BIG_EVENTS_LIMIT)

  let minY = Math.min(0, cushion)
  let maxY = Math.max(0, cushion)
  for (const row of rows) {
    minY = Math.min(minY, row.outer[0], row.scenarioOuter?.[0] ?? row.outer[0])
    maxY = Math.max(maxY, row.outer[1], row.scenarioOuter?.[1] ?? row.outer[1])
  }
  const padding = (maxY - minY) * 0.08

  return (
    <div className={styles.wrap}>
      <div className={styles.chart}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 16, right: 24, bottom: 4, left: 8 }}>
            <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: COLORS.axis }} interval={3} tickLine={false} />
            <YAxis
              tick={{ fontSize: 11, fill: COLORS.axis }}
              tickFormatter={(value: number) => shortMoney(value).replace(' ₽', '')}
              domain={[minY - padding, maxY + padding]}
              width={72}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              content={(props) => (
                <ChartTooltip
                  row={props.active ? (props.payload?.[0]?.payload as ChartRow | undefined) : undefined}
                  cushion={cushion}
                  hasScenario={Boolean(scenario)}
                />
              )}
            />
            <Area type="monotone" dataKey="outer" stroke="none" fill={COLORS.band} fillOpacity={0.12} isAnimationActive={false} />
            <Area type="monotone" dataKey="inner" stroke="none" fill={COLORS.band} fillOpacity={0.2} isAnimationActive={false} />
            {scenario && (
              <Area
                type="monotone"
                dataKey="scenarioOuter"
                stroke="none"
                fill={COLORS.scenario}
                fillOpacity={0.08}
                isAnimationActive={false}
              />
            )}
            <Line type="monotone" dataKey="p50" stroke={COLORS.line} strokeWidth={2.5} dot={false} isAnimationActive={false} />
            {scenario && (
              <Line
                type="monotone"
                dataKey="scenario"
                stroke={COLORS.scenario}
                strokeWidth={2.5}
                strokeDasharray="6 4"
                dot={false}
                isAnimationActive={false}
              />
            )}
            <ReferenceLine
              y={0}
              stroke={COLORS.danger}
              strokeWidth={1.5}
              label={{ value: '0 ₽', position: 'insideBottomLeft', fill: COLORS.danger, fontSize: 11 }}
            />
            {cushion > 0 && (
              <ReferenceLine
                y={cushion}
                stroke={COLORS.warning}
                strokeDasharray="5 4"
                label={{ value: 'подушка', position: 'insideTopLeft', fill: COLORS.warning, fontSize: 11 }}
              />
            )}
            {gap && (
              <ReferenceLine
                x={shortDate(gap.date)}
                stroke={COLORS.danger}
                strokeDasharray="4 3"
                label={{ value: 'риск', position: 'top', fill: COLORS.danger, fontSize: 11 }}
              />
            )}
            {bigEvents.map((item) => {
              const row = rows.find((candidate) => candidate.date === item.date)
              if (!row) {
                return null
              }
              return (
                <ReferenceDot
                  key={`${item.stream_id}-${item.date}`}
                  x={row.label}
                  y={row.p50}
                  r={5}
                  fill={eventColor(item.amount, item.mandatory)}
                  stroke={COLORS.surface}
                  strokeWidth={1.5}
                />
              )
            })}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className={styles.legend}>
        <span><i className={styles.line} /> скорее всего</span>
        <span><i className={styles.inner} /> в половине случаев</span>
        <span><i className={styles.outer} /> в 8 из 10 случаев</span>
        {scenario && <span><i className={styles.scenario} /> при сценарии</span>}
        <span><i className={styles.dot} data-kind="must" /> обязательный платёж</span>
        <span><i className={styles.dot} data-kind="optional" /> необязательный</span>
        <span><i className={styles.dot} data-kind="income" /> поступление</span>
      </div>
    </div>
  )
}

export default BalanceChart
