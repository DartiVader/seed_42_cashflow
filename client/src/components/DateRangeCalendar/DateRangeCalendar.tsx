import { memo, useState } from 'react';
import Button from '@/components/Button';
import styles from './DateRangeCalendar.module.css';

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const DAYS_IN_GRID = 42

const monthFormat = new Intl.DateTimeFormat('ru-RU', { month: 'long' })
const dayFormat = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })

const toIso = (date: Date) => {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

const fromIso = (isoDate: string) => new Date(`${isoDate}T00:00:00`)

const formatIso = (isoDate: string) => dayFormat.format(fromIso(isoDate))

const getMonthTitle = (month: Date) => {
  const name = monthFormat.format(month)
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${month.getFullYear()}`
}

const getGridDays = (month: Date) => {
  const firstDay = new Date(month.getFullYear(), month.getMonth(), 1)
  const mondayOffset = (firstDay.getDay() + 6) % 7
  const days: Date[] = []
  for (let index = 0; index < DAYS_IN_GRID; index++) {
    days.push(new Date(month.getFullYear(), month.getMonth(), 1 - mondayOffset + index))
  }
  return days
}

interface DateRangeCalendarProps {
  from: string | null
  to: string | null
  onChange: (from: string | null, to: string | null) => void
}

const DateRangeCalendar = ({ from, to, onChange }: DateRangeCalendarProps) => {
  const [month, setMonth] = useState(() => {
    const start = from ? fromIso(from) : new Date()
    return new Date(start.getFullYear(), start.getMonth(), 1)
  })
  const [pendingStart, setPendingStart] = useState<string | null>(null)
  const [hoveredDay, setHoveredDay] = useState<string | null>(null)
  const [today] = useState(() => toIso(new Date()))

  let rangeStart = from
  let rangeEnd = to
  if (pendingStart) {
    const previewEnd = hoveredDay ?? pendingStart
    rangeStart = pendingStart < previewEnd ? pendingStart : previewEnd
    rangeEnd = pendingStart < previewEnd ? previewEnd : pendingStart
  }

  const changeMonth = (step: number) => {
    setMonth(new Date(month.getFullYear(), month.getMonth() + step, 1))
  }

  const handleDayClick = (isoDay: string) => {
    if (pendingStart === null) {
      setPendingStart(isoDay)
      return
    }
    const start = pendingStart < isoDay ? pendingStart : isoDay
    const end = pendingStart < isoDay ? isoDay : pendingStart
    setPendingStart(null)
    onChange(start, end)
  }

  const handleReset = () => {
    setPendingStart(null)
    onChange(null, null)
  }

  const getDayClassName = (day: Date, isoDay: string) => {
    const classes = [styles.day]
    if (day.getMonth() !== month.getMonth()) {
      classes.push(styles.outside)
    }
    if (isoDay === today) {
      classes.push(styles.today)
    }
    if (rangeStart && rangeEnd && isoDay > rangeStart && isoDay < rangeEnd) {
      classes.push(styles.inRange)
    }
    if (isoDay === rangeStart || isoDay === rangeEnd) {
      classes.push(styles.selected)
    }
    return classes.join(' ')
  }

  let status = 'Выберите начало периода'
  if (pendingStart) {
    status = 'Выберите конец периода'
  } else if (from && to) {
    status = from === to ? formatIso(from) : `${formatIso(from)} — ${formatIso(to)}`
  }

  return (
    <section className={styles.card}>
      <div className={styles.header}>
        <h2 className={styles.title}>Период</h2>
        <Button variant="ghost" size="sm" onClick={handleReset} disabled={!from && !pendingStart}>Сбросить</Button>
      </div>
      <div className={styles.monthBar}>
        <button type="button" className={styles.arrow} onClick={() => changeMonth(-1)} aria-label="Предыдущий месяц">‹</button>
        <span className={styles.month}>{getMonthTitle(month)}</span>
        <button type="button" className={styles.arrow} onClick={() => changeMonth(1)} aria-label="Следующий месяц">›</button>
      </div>
      <div className={styles.grid} onMouseLeave={() => setHoveredDay(null)}>
        {WEEKDAYS.map((weekday) => <span key={weekday} className={styles.weekday}>{weekday}</span>)}
        {getGridDays(month).map((day) => {
          const isoDay = toIso(day)
          return (
            <button
              key={isoDay}
              type="button"
              className={getDayClassName(day, isoDay)}
              onClick={() => handleDayClick(isoDay)}
              onMouseEnter={() => setHoveredDay(isoDay)}
            >
              {day.getDate()}
            </button>
          )
        })}
      </div>
      <p className={styles.status}>{status}</p>
    </section>
  )
}

export default memo(DateRangeCalendar)
