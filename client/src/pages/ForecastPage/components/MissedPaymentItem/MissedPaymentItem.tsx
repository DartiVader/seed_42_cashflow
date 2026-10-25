import { useState } from 'react';
import Button from '@/components/Button';
import Icon from '@/components/Icon';
import type { ForecastEvent, PlanFactEvent } from '@/api/types';
import { addDays, categoryName, pluralDays, shortDate } from '@/utils/format';
import { missedText, PLAN_FACT_STATUS_NAMES, planFactEventName, planFactRemainder } from '@/utils/planFactText';
import type { EventChange } from '@/pages/ForecastPage/components/PaymentList';
import styles from './MissedPaymentItem.module.css';

const DEFAULT_DELAY_DAYS = 7
const INCOME_CONFIDENCE = 0.8

interface MissedPaymentItemProps {
  event: PlanFactEvent
  asOf: string
  isResolved: boolean
  onChange: (change: EventChange) => void
}

const MissedPaymentItem = ({ event, asOf, isResolved, onChange }: MissedPaymentItemProps) => {
  const [date, setDate] = useState(addDays(asOf, DEFAULT_DELAY_DAYS))
  const rest = planFactRemainder(event)
  const category = categoryName(event.category).toLowerCase()

  const toForecastEvent = (amount: number): ForecastEvent => ({
    date,
    amount,
    category: event.category,
    source: 'manual',
    confidence: amount > 0 ? INCOME_CONFIDENCE : 1,
    mandatory: amount < 0,
    stream_id: event.stream_id ?? `pf-${event.category}-${event.date}`,
    counterparty_name: event.counterparty_name ?? null,
    overdue_from: event.date,
  })

  const handleExpect = () => onChange({ event: toForecastEvent(rest), text: `${category} ожидается ${shortDate(date)}` })

  const handleDrop = () => onChange({ event: toForecastEvent(0), text: `${category} больше не ждём` })

  return (
    <li className={styles.item} data-status={event.status}>
      <div className={styles.head}>
        <span className={styles.status} data-status={event.status}>{PLAN_FACT_STATUS_NAMES[event.status]}</span>
        <b>{planFactEventName(event)}</b>
        <span className={styles.muted}>
          ждали {shortDate(event.date)}{event.days_late ? ` · прошло ${pluralDays(event.days_late)}` : ''}
        </span>
      </div>
      <p className={styles.text}>{missedText(event)}</p>
      {isResolved && (
        <p className={styles.done}>
          <Icon name="check" />
          Новая дата учтена в прогнозе. Изменить можно здесь же или отменить на главной.
        </p>
      )}
      <div className={styles.actions}>
        <label>
          {rest > 0 ? 'Клиент обещал заплатить' : 'Оплачу'}
          <input type="date" value={date} min={addDays(asOf, 1)} onChange={(changeEvent) => setDate(changeEvent.target.value)} />
        </label>
        <Button size="sm" onClick={handleExpect}>Учесть в прогнозе</Button>
        {rest > 0 && <Button size="sm" variant="ghost" onClick={handleDrop}>Не ждать эти деньги</Button>}
      </div>
    </li>
  )
}

export default MissedPaymentItem
