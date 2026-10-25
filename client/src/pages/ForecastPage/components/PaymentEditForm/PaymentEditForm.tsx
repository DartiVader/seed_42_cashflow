import { useState, type FormEvent } from 'react';
import Button from '@/components/Button';
import type { ForecastEvent } from '@/api/types';
import styles from './PaymentEditForm.module.css';

interface PaymentEditFormProps {
  event: ForecastEvent
  onSave: (date: string, amount: number) => void
  onCancel: () => void
}

const PaymentEditForm = ({ event, onSave, onCancel }: PaymentEditFormProps) => {
  const [date, setDate] = useState(event.date)
  const [amount, setAmount] = useState(String(Math.abs(event.amount)))

  const handleSubmit = (formEvent: FormEvent<HTMLFormElement>) => {
    formEvent.preventDefault()
    const sign = event.amount > 0 ? 1 : -1
    onSave(date, Number(amount) * sign)
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <label>
        Дата
        <input type="date" value={date} onChange={(changeEvent) => setDate(changeEvent.target.value)} required />
      </label>
      <label>
        Сумма, ₽
        <input
          type="number"
          min={1}
          step="any"
          value={amount}
          onChange={(changeEvent) => setAmount(changeEvent.target.value)}
          required
        />
      </label>
      <Button type="submit" size="sm">Сохранить</Button>
      <Button size="sm" variant="ghost" onClick={onCancel}>Отмена</Button>
    </form>
  )
}

export default PaymentEditForm
