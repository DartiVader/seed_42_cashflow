import Button from '@/components/Button';
import Card from '@/components/Card';
import type { ActionDetail, ForecastEvent, Gap, Scenario } from '@/api/types';
import { addDays, percent, shortMoney } from '@/utils/format';
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

const scenarioEvent = (date: string, amount: number, category: string, label: string): ForecastEvent => ({
  date, amount: Math.round(amount * 100) / 100, category, source: 'manual', confidence: 1, mandatory: false, label,
})

// Совет → сценарий «что если»: модель пересчитывает прогноз с этим условием, в БД ничего не сохраняется.
// Перенос платежа — сумма уходит с даты date_from на date_to; сокращение расходов — сэкономленное поровну по дням окна
const adviceToScenario = (detail: ActionDetail): Scenario | null => {
  const amount = detail.amount ?? 0
  const from = detail.date_from
  const to = detail.date_to
  if (amount <= 0 || !from || !to) {
    return null
  }
  const category = detail.category ?? 'other'
  if (detail.type === 'postpone' || detail.type === 'negotiate_supplier') {
    return { extra_expenses: [
      scenarioEvent(from, amount, category, 'перенос платежа: не платим в этот день'),
      scenarioEvent(to, -amount, category, 'перенос платежа: платим позже'),
    ] }
  }
  if (detail.type === 'speed_up_receivable') {
    return { extra_expenses: [
      scenarioEvent(from, -amount, category, 'ранняя оплата клиента: не ждём в этот день'),
      scenarioEvent(to, amount, category, 'ранняя оплата клиента'),
    ] }
  }
  if (detail.type === 'cut_discretionary') {
    const days: string[] = []
    for (let day = from; day <= to; day = addDays(day, 1)) {
      days.push(day)
    }
    return { extra_expenses: days.map((day) => scenarioEvent(day, amount / days.length, 'other', 'сокращение необязательных расходов')) }
  }
  return null
}

interface AdviceListProps {
  gap: Gap
  onApply: (scenario: Scenario, text: string) => void
}

const AdviceList = ({ gap, onApply }: AdviceListProps) => {
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
          const scenario = detail ? adviceToScenario(detail) : null
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
              {scenario && (
                <Button size="sm" variant="secondary" onClick={() => onApply(scenario, text)}>Применить</Button>
              )}
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

export default AdviceList
