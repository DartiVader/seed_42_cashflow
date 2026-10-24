import {
  Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import type { PlanFact } from '@/api/types';
import { shortDate, shortMoney } from '@/utils/format';
import PlanFactTooltip, { type PlanFactRow } from '@/pages/ForecastPage/components/PlanFactTooltip';
import styles from './PlanFactChart.module.css';

const COLORS = {
  plan: 'var(--color-primary)',
  fact: 'var(--color-brand-900)',
  outside: 'var(--color-danger)',
  grid: 'var(--color-border)',
  axis: 'var(--color-text-muted)',
  surface: 'var(--color-surface)',
}

interface FactDotProps {
  cx?: number
  cy?: number
  payload?: PlanFactRow
}

const renderFactDot = ({ cx, cy, payload }: FactDotProps) => {
  if (cx === undefined || cy === undefined || !payload || payload.fact === null) {
    return <g />
  }
  return (
    <circle
      cx={cx}
      cy={cy}
      r={payload.outside ? 5 : 3.5}
      fill={payload.outside ? COLORS.outside : COLORS.fact}
      stroke={COLORS.surface}
      strokeWidth={1.5}
    />
  )
}

const PlanFactChart = ({ data }: { data: PlanFact }) => {
  const rows: PlanFactRow[] = data.daily.map((day) => ({
    date: day.date,
    label: shortDate(day.date),
    plan: day.plan_p50,
    band: [day.plan_p10, day.plan_p90],
    fact: day.fact,
    outside: day.outside,
  }))

  return (
    <div className={styles.wrap}>
      <div className={styles.chart}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 12, fill: COLORS.axis }} tickLine={false} />
            <YAxis
              tickFormatter={(value: number) => shortMoney(value)}
              tick={{ fontSize: 12, fill: COLORS.axis }}
              width={78}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              content={(props) => (
                <PlanFactTooltip row={props.active ? (props.payload?.[0]?.payload as PlanFactRow | undefined) : undefined} />
              )}
            />
            <Area dataKey="band" stroke="none" fill={COLORS.plan} fillOpacity={0.14} isAnimationActive={false} />
            <Line dataKey="plan" stroke={COLORS.plan} strokeDasharray="6 4" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line
              dataKey="fact"
              stroke={COLORS.fact}
              strokeWidth={2.5}
              dot={renderFactDot}
              connectNulls={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className={styles.legend}>
        <span><i className={styles.plan} />план (что ждали)</span>
        <span><i className={styles.band} />ожидаемый разброс</span>
        <span><i className={styles.fact} />факт по выписке</span>
        <span><i className={styles.outside} />вышел за разброс</span>
      </div>
    </div>
  )
}

export default PlanFactChart
