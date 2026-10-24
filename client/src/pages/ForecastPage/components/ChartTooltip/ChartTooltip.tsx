import type { DailyPoint, ForecastEvent } from '@/api/types';
import { estimateBelow, riskTone } from '@/utils/forecastInsights';
import { categoryName, percent, shortMoney, weekdayDate } from '@/utils/format';
import styles from './ChartTooltip.module.css';

export interface ChartRow {
  date: string
  label: string
  outer: [number, number]
  inner: [number, number]
  p50: number
  scenario?: number
  scenarioOuter?: [number, number]
  risk: number
  confidence?: string
  events: ForecastEvent[]
  point: DailyPoint
}

interface ChartTooltipProps {
  row?: ChartRow
  cushion: number
  hasScenario: boolean
}

const ChartTooltip = ({ row, cushion, hasScenario }: ChartTooltipProps) => {
  if (!row) {
    return null
  }

  return (
    <div className={styles.tooltip}>
      <div className={styles.date}>{weekdayDate(row.date)}</div>
      <div className={styles.main}>Скорее всего <b>{shortMoney(row.p50)}</b></div>
      <div className={styles.row}>в 8 из 10 случаев: {shortMoney(row.outer[0])} … {shortMoney(row.outer[1])}</div>
      <div className={styles.row}>в половине случаев: {shortMoney(row.inner[0])} … {shortMoney(row.inner[1])}</div>
      {hasScenario && row.scenario !== undefined && (
        <div className={styles.scenario}>при сценарии: {shortMoney(row.scenario)}</div>
      )}
      <div className={styles.risk} data-tone={riskTone(row.risk)}>Риск уйти в минус в этот день: {percent(row.risk)}</div>
      {cushion > 0 && (
        <div className={styles.row}>Риск опуститься ниже подушки: {percent(estimateBelow(row.point, cushion))}</div>
      )}
      {row.confidence && <div className={styles.row}>Точность прогноза на этот день: {row.confidence}</div>}
      {row.events.length > 0 && (
        <ul className={styles.events}>
          {row.events.map((item) => (
            <li key={`${item.stream_id}-${item.date}`}>
              <span>{item.label || categoryName(item.category)}</span>
              <b data-sign={item.amount < 0 ? 'out' : 'in'}>{shortMoney(item.amount, true)}</b>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default ChartTooltip
