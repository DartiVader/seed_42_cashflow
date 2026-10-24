import { shortMoney, weekdayDate } from '@/utils/format';
import styles from './PlanFactTooltip.module.css';

export interface PlanFactRow {
  date: string
  label: string
  plan: number
  band: [number, number]
  fact: number | null
  outside: boolean
}

const PlanFactTooltip = ({ row }: { row?: PlanFactRow }) => {
  if (!row) {
    return null
  }

  return (
    <div className={styles.tooltip}>
      <b>{weekdayDate(row.date)}</b>
      <div>
        План: {shortMoney(row.plan)}{' '}
        <span className={styles.muted}>(от {shortMoney(row.band[0])} до {shortMoney(row.band[1])})</span>
      </div>
      {row.fact !== null && (
        <div>Факт: <b>{shortMoney(row.fact)}</b> ({shortMoney(row.fact - row.plan, true)})</div>
      )}
      {row.outside && <div className={styles.warning}>Факт вышел за ожидаемый разброс</div>}
    </div>
  )
}

export default PlanFactTooltip
