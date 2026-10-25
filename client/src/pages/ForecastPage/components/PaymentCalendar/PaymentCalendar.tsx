import { useState } from 'react';
import Card from '@/components/Card';
import type { Forecast } from '@/api/types';
import { addDays, shortDate, shortMoney } from '@/utils/format';
import DayDetails from '@/pages/ForecastPage/components/DayDetails';
import MonthGrid from '@/pages/ForecastPage/components/MonthGrid';
import PaymentAddForm from '@/pages/ForecastPage/components/PaymentAddForm';
import PaymentList, { type EventChange } from '@/pages/ForecastPage/components/PaymentList';
import styles from './PaymentCalendar.module.css';

const DEFAULT_ADD_OFFSET_DAYS = 10

interface PaymentCalendarProps {
  forecast: Forecast
  onChange: (change: EventChange) => void
}

const PaymentCalendar = ({ forecast, onChange }: PaymentCalendarProps) => {
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [addDate, setAddDate] = useState(() => addDays(forecast.as_of, DEFAULT_ADD_OFFSET_DAYS))

  const hasSelected = forecast.daily.some((day) => day.date === selectedDate)
  const activeDate = hasSelected ? selectedDate : forecast.gaps[0]?.date ?? forecast.daily[0]?.date ?? null

  return (
    <div className={styles.layout}>
      <Card
        title="Месяц вперёд"
        subtitle="Цвет дня — риск уйти в минус. Под числом — сколько скорее всего будет на счёте. Точки — платежи. Нажмите на день, чтобы увидеть подробности, или листайте стрелками."
      >
        <MonthGrid forecast={forecast} selectedDate={activeDate} onSelect={setSelectedDate} />
        <div className={styles.legend}>
          <span><i className={styles.dot} data-kind="must" /> обязательный</span>
          <span><i className={styles.dot} data-kind="optional" /> необязательный</span>
          <span><i className={styles.dot} data-kind="income" /> поступление</span>
          <span><i className={styles.gap} /> первый день риска</span>
        </div>
        {activeDate && (
          <DayDetails forecast={forecast} date={activeDate} onSelect={setSelectedDate} />
        )}
      </Card>

      <PaymentList
        events={forecast.events}
        selectedDate={activeDate}
        onChange={onChange}
        onSelectDate={setSelectedDate}
      />

      <div className={styles.full}>
        <PaymentAddForm
          asOf={forecast.as_of}
          date={addDate}
          onDateChange={setAddDate}
          onAdd={(event) => onChange({
            event,
            text: `добавлено: ${event.label} ${shortDate(event.date)}, ${shortMoney(event.amount, true)}`,
          })}
        />
      </div>
    </div>
  )
}

export default PaymentCalendar
