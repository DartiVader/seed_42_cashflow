import Card from '@/components/Card';
import type { Forecast, Gap } from '@/api/types';
import { approxMoney, longDate, naturalFrequency, percent, probabilityLevel, shortMoney } from '@/utils/format';
import styles from './GapCard.module.css';

interface GapCardProps {
  gap: Gap | undefined
  forecast: Forecast
}

const visibleReasons = (reasons: string[]) => {
  const [first, ...rest] = reasons
  if (first && !first.startsWith('С ')) {
    return reasons
  }
  return rest
}

const GapCard = ({ gap, forecast }: GapCardProps) => {
  if (!gap) {
    const end = forecast.daily[forecast.daily.length - 1]
    return (
      <Card title="Разрывов не видно" tour="gap">
        <p className={styles.text}>
          До {longDate(end.date)} остаток не опускается ниже нуля даже в пессимистичных вариантах.
          Следите за крупными платежами в «Календаре» — их можно поправить, если что-то изменится.
        </p>
      </Card>
    )
  }

  const level = probabilityLevel(gap.probability)
  return (
    <Card
      title="Когда и сколько не хватит"
      tour="gap"
      aside={<span className={styles.level} data-tone={level.tone}>{level.word} · {percent(gap.probability)}</span>}
    >
      <div className={styles.numbers}>
        <div className={styles.number}>
          <span className={styles.label}>Дата</span>
          <b className={styles.big}>{longDate(gap.date)}</b>
        </div>
        {gap.shortfall_at_gap !== undefined && (
          <div className={styles.number}>
            <span className={styles.label}>Нужно найти к этой неделе</span>
            <b className={styles.big}>{approxMoney(gap.shortfall_at_gap)}</b>
            {gap.shortfall_at_gap_low !== undefined && gap.shortfall_at_gap_high !== undefined && (
              <span className={styles.hint}>
                от {shortMoney(gap.shortfall_at_gap_low)} до {shortMoney(gap.shortfall_at_gap_high)}
              </span>
            )}
          </div>
        )}
        <div className={styles.number}>
          <span className={styles.label}>Самый глубокий минус за месяц</span>
          <b className={styles.big}>{approxMoney(gap.shortfall)}</b>
          {gap.shortfall_high !== undefined && <span className={styles.hint}>с запасом до {shortMoney(gap.shortfall_high)}</span>}
        </div>
      </div>
      <h4 className={styles.subtitle}>Почему</h4>
      <ul className={styles.reasons}>
        {visibleReasons(gap.reasons).map((reason) => <li key={reason}>{reason}</li>)}
      </ul>
      <p className={styles.footnote}>
        «Не хватит» — значит, остаток уйдёт ниже нуля {naturalFrequency(gap.probability)} при таких же платежах, как обычно.
        Диапазон суммы честный: в 8 из 10 случаев реальная нехватка окажется внутри него.
      </p>
    </Card>
  )
}

export default GapCard
