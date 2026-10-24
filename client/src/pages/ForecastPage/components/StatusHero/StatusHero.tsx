import type { Explanation, Forecast } from '@/api/types';
import { balanceNow, runwayDays, safeToSpend } from '@/utils/forecastInsights';
import { longDate, naturalFrequency, percent, pluralDays, probabilityLevel, shortMoney } from '@/utils/format';
import styles from './StatusHero.module.css';

const STATUS_META = {
  ok: { title: 'Денег хватает', tone: 'ok', icon: '✓' },
  gap_expected: { title: 'Может не хватить денег', tone: 'warn', icon: '!' },
  already_negative: { title: 'Счёт уже в минусе', tone: 'bad', icon: '✕' },
  below_cushion: { title: 'Остаток ниже вашей подушки', tone: 'warn', icon: '!' },
} as const

interface StatusHeroProps {
  forecast: Forecast
  cushion: number
  explanation: Explanation
  isExplaining: boolean
}

const runwayText = (runway: number | null) => {
  if (runway === null) {
    return '30+ дней'
  }
  if (runway <= 0) {
    return 'нет'
  }
  return pluralDays(runway)
}

const StatusHero = ({ forecast, cushion, explanation, isExplaining }: StatusHeroProps) => {
  const balance = balanceNow(forecast)
  const isBelowCushion = forecast.status === 'ok' && cushion > 0 && balance < cushion
  const meta = STATUS_META[isBelowCushion ? 'below_cushion' : forecast.status]
  const gap = forecast.gaps[0]
  const title = forecast.status === 'gap_expected' && gap ? `${meta.title} ${longDate(gap.date)}` : meta.title

  return (
    <section className={styles.hero} data-tone={meta.tone} data-tour="status">
      <div className={styles.main}>
        <div className={styles.icon} aria-hidden="true">{meta.icon}</div>
        <div>
          <h2 className={styles.title}>{title}</h2>
          <p className={styles.summary} data-tour="summary">{explanation.text}</p>
          <div className={styles.meta}>
            {isExplaining && <span className={styles.badge}>готовим объяснение…</span>}
            {!isExplaining && explanation.source === 'llm' && explanation.verified && (
              <span className={styles.badgeOk} title="Все числа и даты в тексте сверены с расчётом">✓ объяснение проверено</span>
            )}
            {!isExplaining && explanation.source !== 'llm' && (
              <span className={styles.badge} title="Текст собран по шаблону из расчёта">кратко по расчёту</span>
            )}
          </div>
        </div>
      </div>
      <div className={styles.kpis} data-tour="kpis">
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>На счёте сейчас</span>
          <b className={styles.kpiValue} data-negative={balance < 0}>{shortMoney(balance)}</b>
          <span className={styles.kpiHint}>на {longDate(forecast.as_of)}</span>
        </div>
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>Можно потратить без риска</span>
          <b className={styles.kpiValue}>{shortMoney(safeToSpend(forecast, cushion))}</b>
          <span className={styles.kpiHint}>{cushion > 0 ? 'сверх вашей подушки, ' : ''}в 9 из 10 вариантов хватит</span>
        </div>
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>Запас по времени</span>
          <b className={styles.kpiValue}>{runwayText(runwayDays(forecast, cushion))}</b>
          <span className={styles.kpiHint}>{cushion > 0 ? 'до падения ниже подушки' : 'до ухода в минус'} в среднем сценарии</span>
        </div>
        {gap && (
          <div className={styles.kpi}>
            <span className={styles.kpiLabel}>Риск нехватки</span>
            <b className={styles.kpiValue}>{probabilityLevel(gap.probability).word}</b>
            <span className={styles.kpiHint}>{naturalFrequency(gap.probability)} · {percent(gap.probability)}</span>
          </div>
        )}
      </div>
    </section>
  )
}

export default StatusHero
