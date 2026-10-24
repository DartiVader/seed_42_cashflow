import Card from '@/components/Card';
import Icon from '@/components/Icon';
import type { PlanFact as PlanFactData } from '@/api/types';
import { longDate, shortDate, shortMoney } from '@/utils/format';
import { isProblem, planFactEventName } from '@/utils/planFactText';
import MissedPaymentItem from '@/pages/ForecastPage/components/MissedPaymentItem';
import type { EventChange } from '@/pages/ForecastPage/components/PaymentList';
import PlanFactChart from '@/pages/ForecastPage/components/PlanFactChart';
import styles from './PlanFact.module.css';

interface PlanFactProps {
  data: PlanFactData | null
  isLoading: boolean
  isDemo: boolean
  error: string | null
  resolvedStreams: Set<string>
  onChange: (change: EventChange) => void
}

const leadText = (problemsCount: number, total: number, lastDiff: number) => {
  const problems = problemsCount === 0
    ? `Все ${total} ожидаемых платежа прошли вовремя. Прогноз подтверждается.`
    : `Из ${total} ожидаемых платежей ${problemsCount} ${problemsCount === 1 ? 'прошёл' : 'прошли'} не так, как ждали. `
      + 'Мы уже учли это в прогнозе — проверьте даты ниже.'
  return `${problems} Остаток сегодня ${lastDiff >= 0 ? 'выше' : 'ниже'} плана на ${shortMoney(Math.abs(lastDiff))}.`
}

const PlanFact = ({ data, isLoading, isDemo, error, resolvedStreams, onChange }: PlanFactProps) => {
  if (error) {
    return <p className={styles.error}>{error}</p>
  }
  if (!data) {
    return <div className={styles.skeleton}>{isLoading ? 'Сверяем прогноз с выпиской…' : 'Нет данных для сверки'}</div>
  }

  const daysWithFact = data.daily.filter((day) => day.fact !== null)
  const daysInside = daysWithFact.filter((day) => !day.outside).length
  const lastDay = daysWithFact[daysWithFact.length - 1]
  const lastDiff = lastDay && lastDay.fact !== null ? lastDay.fact - lastDay.plan_p50 : 0
  const problems = data.events.filter(isProblem)
  const paid = data.events.filter((event) => !isProblem(event))

  return (
    <div className={styles.layout}>
      <Card
        title={`Как сбылся прогноз от ${longDate(data.as_of_plan)}`}
        tour="planfact"
        aside={isDemo ? <span className={styles.demo}>демо-данные</span> : undefined}
      >
        <p className={styles.lead}>{leadText(problems.length, data.events.length, lastDiff)}</p>
        <div className={styles.kpis}>
          <div className={styles.kpi}>
            <span>Платежей прошло по плану</span>
            <b>{paid.length} из {data.events.length}</b>
          </div>
          <div className={styles.kpi} data-bad={data.summary.missed_in > 0}>
            <span>Не поступило денег</span>
            <b>{shortMoney(data.summary.missed_in)}</b>
          </div>
          <div className={styles.kpi} data-bad={data.summary.missed_out > 0}>
            <span>Не оплачено</span>
            <b>{shortMoney(data.summary.missed_out)}</b>
          </div>
          <div className={styles.kpi}>
            <span>Дней в ожидаемом разбросе</span>
            <b>{daysInside} из {daysWithFact.length}</b>
          </div>
        </div>
      </Card>

      <Card
        title="План и факт по дням"
        aside={<span className={styles.muted}>макс. отклонение {shortMoney(data.summary.max_deviation)}</span>}
      >
        <PlanFactChart data={data} />
      </Card>

      {problems.length > 0 && (
        <Card
          title="Ожидали — не прошло"
          tour="planfact-missed"
          aside={<span className={styles.muted}>укажите, когда ждать, и прогноз пересчитается</span>}
        >
          <ul className={styles.list}>
            {problems.map((event) => (
              <MissedPaymentItem
                key={`${event.stream_id}-${event.date}`}
                event={event}
                asOf={data.as_of}
                isResolved={resolvedStreams.has(event.stream_id ?? '')}
                onChange={onChange}
              />
            ))}
          </ul>
        </Card>
      )}

      {paid.length > 0 && (
        <Card title="Прошли как ожидали">
          <ul className={styles.list}>
            {paid.map((event) => (
              <li key={`${event.stream_id}-${event.date}`} className={styles.paidRow}>
                <span className={styles.paidIcon}><Icon name="check" /></span>
                <span>{planFactEventName(event)}</span>
                <span className={styles.muted}>{shortDate(event.date)}</span>
                <span className={styles.amount}>{shortMoney(event.amount_fact ?? event.amount_plan, true)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

export default PlanFact
