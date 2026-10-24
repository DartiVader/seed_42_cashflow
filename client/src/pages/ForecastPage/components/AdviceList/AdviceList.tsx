import Button from '@/components/Button';
import Card from '@/components/Card';
import type { ActionDetail, Forecast, ForecastEvent, Gap } from '@/api/types';
import { percent, shortMoney } from '@/utils/format';
import styles from './AdviceList.module.css';

const ADVICE_ICONS: Record<string, string> = {
  postpone: '⇢',
  negotiate_supplier: '🤝',
  speed_up_receivable: '⇠',
  cut_discretionary: '✂',
  overdraft: '🏦',
}

const ADVICE_TITLES: Record<string, string> = {
  postpone: 'Перенести необязательный платёж',
  negotiate_supplier: 'Договориться с поставщиком',
  speed_up_receivable: 'Ускорить оплату клиента',
  cut_discretionary: 'Сократить необязательные расходы',
  overdraft: 'Кредитный лимит',
}

const adviceToEvent = (detail: ActionDetail, forecast: Forecast): ForecastEvent | null => {
  if (!detail.stream_id || !detail.date_to) {
    return null
  }
  const original = forecast.events.find((item) => item.stream_id === detail.stream_id)
  if (!original) {
    return null
  }
  return { ...original, date: detail.date_to, source: 'manual', label: original.label ?? null }
}

interface AdviceListProps {
  gap: Gap
  forecast: Forecast
  onApply: (event: ForecastEvent, text: string) => void
}

const AdviceList = ({ gap, forecast, onApply }: AdviceListProps) => {
  if (gap.actions.length === 0) {
    return null
  }
  const details = gap.actions_detail ?? []

  return (
    <Card
      title="Что сделать"
      tour="advice"
      aside={<span className={styles.badge} title="Каждый совет пересчитан: показываем только те, что снижают риск">проверено пересчётом</span>}
    >
      <ol className={styles.list}>
        {gap.actions.map((text, index) => {
          const detail: ActionDetail | undefined = details[index]
          const event = detail ? adviceToEvent(detail, forecast) : null
          const before = detail?.prob_window_before ?? detail?.prob_before
          const after = detail?.prob_window_after ?? detail?.prob_after
          const hasEffect = before !== undefined && after !== undefined && detail?.type !== 'overdraft'
          return (
            <li key={text} className={styles.item}>
              <div className={styles.icon} aria-hidden="true">{ADVICE_ICONS[detail?.type ?? ''] ?? '•'}</div>
              <div className={styles.body}>
                {detail && <div className={styles.title}>{ADVICE_TITLES[detail.type] ?? 'Совет'}</div>}
                <p className={styles.text}>{text}</p>
                {hasEffect && (
                  <div className={styles.effect}>
                    <progress className={styles.before} max={1} value={before} />
                    <progress className={styles.after} max={1} value={after} />
                    <span className={styles.effectText}>риск {percent(before)} → <b>{percent(after)}</b></span>
                  </div>
                )}
                {detail?.categories && detail.categories.length > 0 && (
                  <div className={styles.tags}>
                    {detail.categories.map((category) => (
                      <span key={category.name} className={styles.tag}>{category.name}: −{shortMoney(category.amount)}</span>
                    ))}
                  </div>
                )}
              </div>
              {event && (
                <Button size="sm" variant="secondary" onClick={() => onApply(event, text)}>Применить</Button>
              )}
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

export default AdviceList
