import { useRef, type KeyboardEvent } from 'react';
import type { DailyPoint, Forecast } from '@/api/types';
import { dayRisk, riskTone } from '@/utils/forecastInsights';
import { isWeekend, parseIso, percent, shortMoney, weekdayDate } from '@/utils/format';
import styles from './MonthGrid.module.css';

const WEEKDAYS = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
const MAX_DOTS = 3

const KEY_STEPS: Record<string, number> = {
  ArrowLeft: -1,
  ArrowRight: 1,
  ArrowUp: -7,
  ArrowDown: 7,
}

const dotKind = (amount: number, mandatory: boolean | undefined) => {
  if (amount > 0) {
    return 'income'
  }
  return mandatory ? 'must' : 'optional'
}

interface MonthGridProps {
  forecast: Forecast
  selectedDate: string | null
  onSelect: (date: string) => void
}

const MonthGrid = ({ forecast, selectedDate, onSelect }: MonthGridProps) => {
  const cellRefs = useRef(new Map<string, HTMLButtonElement>())
  const days = forecast.daily
  if (days.length === 0) {
    return null
  }

  const gapDate = forecast.gaps[0]?.date
  const leadingBlanks = (parseIso(days[0].date).getDay() + 6) % 7
  const blanks: string[] = []
  for (let index = 0; index < leadingBlanks; index++) {
    blanks.push(`blank-${index}`)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = KEY_STEPS[event.key]
    if (step === undefined || !selectedDate) {
      return
    }
    const currentIndex = days.findIndex((day) => day.date === selectedDate)
    const next: DailyPoint | undefined = days[currentIndex + step]
    if (next) {
      event.preventDefault()
      onSelect(next.date)
      cellRefs.current.get(next.date)?.focus()
    }
  }

  return (
    <div className={styles.grid} onKeyDown={handleKeyDown} data-tour="calendar-grid">
      {WEEKDAYS.map((weekday) => <div key={weekday} className={styles.head}>{weekday}</div>)}
      {blanks.map((blank) => <div key={blank} />)}
      {days.map((day) => {
        const risk = dayRisk(day)
        const events = forecast.events.filter((item) => item.date === day.date)
        const isSelected = day.date === selectedDate
        const hint = `${weekdayDate(day.date)}: около ${shortMoney(day.p50)}, риск ${percent(risk)}`
        return (
          <button
            key={day.date}
            ref={(element) => {
              if (element) {
                cellRefs.current.set(day.date, element)
              } else {
                cellRefs.current.delete(day.date)
              }
            }}
            type="button"
            className={styles.cell}
            data-tone={riskTone(risk)}
            data-weekend={isWeekend(day.date)}
            data-gap={day.date === gapDate}
            aria-pressed={isSelected}
            aria-label={hint}
            title={hint}
            tabIndex={isSelected || (!selectedDate && day === days[0]) ? 0 : -1}
            onClick={() => onSelect(day.date)}
          >
            <span className={styles.day}>{parseIso(day.date).getDate()}</span>
            <span className={styles.sum}>{shortMoney(day.p50).replace(' ₽', '')}</span>
            <span className={styles.dots}>
              {events.slice(0, MAX_DOTS).map((item) => (
                <i key={`${item.stream_id}-${item.date}`} className={styles.dot} data-kind={dotKind(item.amount, item.mandatory)} />
              ))}
              {events.length > MAX_DOTS && <span className={styles.more}>+{events.length - MAX_DOTS}</span>}
            </span>
          </button>
        )
      })}
    </div>
  )
}

export default MonthGrid
