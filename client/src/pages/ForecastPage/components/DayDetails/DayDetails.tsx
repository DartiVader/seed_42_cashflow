import Button from '@/components/Button';
import Icon from '@/components/Icon';
import type { Forecast } from '@/api/types';
import { dayRisk, riskTone } from '@/utils/forecastInsights';
import { categoryName, PERIODICITY_NAMES, percent, shortMoney, SOURCE_NAMES, weekdayDate } from '@/utils/format';
import styles from './DayDetails.module.css';

const RISK_WORDS = { ok: 'риск низкий', warn: 'стоит присмотреться', bad: 'высокий риск' } as const

interface DayDetailsProps {
  forecast: Forecast
  date: string
  onSelect: (date: string) => void
}

const DayDetails = ({ forecast, date, onSelect }: DayDetailsProps) => {
  const index = forecast.daily.findIndex((day) => day.date === date)
  const day = forecast.daily[index]
  if (!day) {
    return null
  }
  const previous = forecast.daily[index - 1]
  const next = forecast.daily[index + 1]
  const risk = dayRisk(day)
  const tone = riskTone(risk)
  const events = forecast.events.filter((item) => item.date === date)
  const isGapDay = forecast.gaps[0]?.date === date

  return (
    <section className={styles.details} data-tone={tone} aria-live="polite">
      <div className={styles.head}>
        <Button
          variant="ghost"
          shape="square"
          size="sm"
          onClick={() => previous && onSelect(previous.date)}
          disabled={!previous}
          aria-label="Предыдущий день"
        >
          <Icon name="chevronLeft" />
        </Button>
        <div className={styles.titleBlock}>
          <h4 className={styles.title}>{weekdayDate(date)}</h4>
          {isGapDay && <span className={styles.gapBadge}>первый день риска</span>}
        </div>
        <Button
          variant="ghost"
          shape="square"
          size="sm"
          onClick={() => next && onSelect(next.date)}
          disabled={!next}
          aria-label="Следующий день"
        >
          <Icon name="chevronRight" />
        </Button>
      </div>

      <div className={styles.stats}>
        <div className={styles.stat}>
          <span className={styles.label}>Скорее всего на счёте</span>
          <b className={styles.value} data-negative={day.p50 < 0}>{shortMoney(day.p50)}</b>
        </div>
        <div className={styles.stat}>
          <span className={styles.label}>В 8 из 10 случаев</span>
          <b className={styles.range}>{shortMoney(day.p10)} … {shortMoney(day.p90)}</b>
        </div>
        <div className={styles.stat}>
          <span className={styles.label}>Риск уйти в минус</span>
          <b className={styles.risk}>{percent(risk)} · {RISK_WORDS[tone]}</b>
        </div>
      </div>

      {events.length > 0
        ? (
          <ul className={styles.events}>
            {events.map((item) => (
              <li key={`${item.stream_id}-${item.date}`} className={styles.event}>
                <span className={styles.eventName}>
                  {item.label || categoryName(item.category)}
                  <span className={styles.eventMeta}>
                    {SOURCE_NAMES[item.source] ?? item.source}
                    {item.periodicity && item.periodicity !== 'once' ? ` · ${PERIODICITY_NAMES[item.periodicity].toLowerCase()}` : ''}
                  </span>
                </span>
                <b className={styles.amount} data-sign={item.amount < 0 ? 'out' : 'in'}>{shortMoney(item.amount, true)}</b>
              </li>
            ))}
          </ul>
        )
        : <p className={styles.empty}>Известных платежей в этот день нет — только обычные поступления и расходы.</p>}
    </section>
  )
}

export default DayDetails
