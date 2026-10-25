import { useState, type FormEvent, type Ref } from 'react';
import Button from '@/components/Button';
import Card from '@/components/Card';
import Icon from '@/components/Icon';
import type { ForecastEvent, Periodicity } from '@/api/types';
import { addDays, PERIODICITY_NAMES } from '@/utils/format';
import styles from './PaymentAddForm.module.css';

const CATEGORY_OPTIONS: { value: string, label: string, sign: 1 | -1 }[] = [
  { value: 'revenue_client', label: 'Оплата от клиента', sign: 1 },
  { value: 'income_subsidy', label: 'Субсидия / возмещение', sign: 1 },
  { value: 'suppliers', label: 'Закупка у поставщика', sign: -1 },
  { value: 'capex', label: 'Оборудование, ремонт', sign: -1 },
  { value: 'marketing', label: 'Реклама', sign: -1 },
  { value: 'tax_other', label: 'Налог / взнос', sign: -1 },
  { value: 'salary', label: 'Зарплата / премия', sign: -1 },
  { value: 'other', label: 'Другое', sign: -1 },
]

const CONFIDENCE_OPTIONS = [
  { value: 1, label: 'точно будет' },
  { value: 0.7, label: 'скорее всего' },
  { value: 0.4, label: 'не уверен' },
]

const PERIODICITY_OPTIONS: Periodicity[] = ['once', 'monthly', 'monthly_irregular', 'quarterly', 'bimonthly', 'seasonal']

const PERIODICITY_HINTS: Record<Periodicity, string> = {
  once: 'Платёж будет один раз в выбранную дату.',
  monthly: 'Повторяется каждый месяц в тот же день.',
  monthly_irregular: 'Обычно каждый месяц, но иногда пропускается — повторы учитываются с меньшей уверенностью.',
  quarterly: 'Повторяется раз в три месяца в тот же день.',
  bimonthly: 'Повторяется раз в два месяца в тот же день.',
  seasonal: 'Повторяется каждый месяц, но только в сезон выбранной даты (например, осенью — сентябрь–ноябрь).',
}

const MANDATORY_CATEGORIES = ['tax_other', 'salary']
const HORIZON_DAYS = 30

interface PaymentAddFormProps {
  asOf: string
  date: string
  onDateChange: (date: string) => void
  onAdd: (event: ForecastEvent) => void
  ref?: Ref<HTMLDivElement>
}

const PaymentAddForm = ({ asOf, date, onDateChange, onAdd, ref }: PaymentAddFormProps) => {
  const [category, setCategory] = useState(CATEGORY_OPTIONS[0].value)
  const [amount, setAmount] = useState('')
  const [confidence, setConfidence] = useState(1)
  const [periodicity, setPeriodicity] = useState<Periodicity>('once')
  const [label, setLabel] = useState('')
  const option = CATEGORY_OPTIONS.find((item) => item.value === category) ?? CATEGORY_OPTIONS[0]

  const handleSubmit = (formEvent: FormEvent<HTMLFormElement>) => {
    formEvent.preventDefault()
    const value = Number(amount)
    if (!value) {
      return
    }
    onAdd({
      date,
      amount: option.sign * Math.abs(value),
      category,
      source: 'manual',
      confidence,
      mandatory: option.sign < 0 && MANDATORY_CATEGORIES.includes(category),
      stream_id: `manual-${Date.now()}`,
      label: label.trim() || option.label,
      periodicity,
    })
    setAmount('')
    setLabel('')
  }

  return (
    <div ref={ref}>
      <Card
        title="Добавить ожидаемый платёж"
        subtitle="Выставили счёт, подписали договор, планируете покупку? Добавьте — сервис учтёт это в прогнозе и в советах."
      >
        <form className={styles.form} data-tour="add-event" onSubmit={handleSubmit}>
          <label>
            Что
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              {CATEGORY_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>{item.sign > 0 ? '＋ ' : '− '}{item.label}</option>
              ))}
            </select>
          </label>
          <label>
            Когда
            <input
              type="date"
              value={date}
              min={addDays(asOf, 1)}
              max={addDays(asOf, HORIZON_DAYS)}
              onChange={(event) => onDateChange(event.target.value)}
              required
            />
          </label>
          <label>
            Сумма, ₽
            <input
              type="number"
              min={1}
              step="any"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              placeholder="300 000"
              required
            />
          </label>
          <label>
            Насколько уверены
            <select value={confidence} onChange={(event) => setConfidence(Number(event.target.value))}>
              {CONFIDENCE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label>
            Периодичность
            <select value={periodicity} onChange={(event) => setPeriodicity(event.target.value as Periodicity)}>
              {PERIODICITY_OPTIONS.map((item) => <option key={item} value={item}>{PERIODICITY_NAMES[item]}</option>)}
            </select>
          </label>
          <label className={styles.wide}>
            Подпись
            <input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="например: счёт №145 от ООО «Ромашка»"
              maxLength={80}
            />
          </label>
          <p className={styles.hint}>
            <Icon name="repeat" />
            {PERIODICITY_HINTS[periodicity]}
          </p>
          <Button type="submit">
            <Icon name="plus" />
            Добавить в прогноз
          </Button>
        </form>
      </Card>
    </div>
  )
}

export default PaymentAddForm
