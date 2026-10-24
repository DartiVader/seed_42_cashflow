import type { Forecast } from '@/api/types';
import { weekRisks } from '@/utils/forecastInsights';
import { shortDate, shortMoney } from '@/utils/format';
import styles from './WeekStrip.module.css';

const TONE_WORDS = { ok: 'спокойно', warn: 'внимание', bad: 'опасно' } as const

const weekTone = (risk: number) => {
  if (risk >= 0.5) {
    return 'bad'
  }
  if (risk >= 0.2) {
    return 'warn'
  }
  return 'ok'
}

const WeekStrip = ({ forecast }: { forecast: Forecast }) => {
  const weeks = weekRisks(forecast.daily)

  return (
    <div className={styles.weeks} data-tour="weeks">
      {weeks.map((week, index) => {
        const tone = weekTone(week.risk)
        return (
          <div key={week.from} className={styles.week} data-tone={tone}>
            <span className={styles.name}>{index === 0 ? 'Эта неделя' : `Неделя ${index + 1}`}</span>
            <span className={styles.dates}>{shortDate(week.from)}–{shortDate(week.to)}</span>
            <b className={styles.verdict}>{TONE_WORDS[tone]}</b>
            <span className={styles.dates}>минимум {shortMoney(week.minP50)}</span>
          </div>
        )
      })}
    </div>
  )
}

export default WeekStrip
