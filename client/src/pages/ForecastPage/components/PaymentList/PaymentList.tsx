import { useState } from 'react';
import Button from '@/components/Button';
import Card from '@/components/Card';
import Icon from '@/components/Icon';
import type { ForecastEvent } from '@/api/types';
import {
  categoryName, PERIODICITY_NAMES, percent, shortDate, shortMoney, SOURCE_NAMES, weekdayDate,
} from '@/utils/format';
import PaymentEditForm from '@/pages/ForecastPage/components/PaymentEditForm';
import styles from './PaymentList.module.css';

export interface EventChange {
  event: ForecastEvent
  text: string
}

interface PaymentGroup {
  title: string
  hint: string
  items: ForecastEvent[]
}

const confidenceWord = (confidence: number) => {
  if (confidence >= 0.95) {
    return 'точно'
  }
  return confidence >= 0.6 ? 'скорее всего' : 'не уверен'
}

const eventTitle = (event: ForecastEvent) => event.label || categoryName(event.category)

const groupEvents = (events: ForecastEvent[]): PaymentGroup[] => [
  {
    title: 'Просрочено',
    hint: 'должны были пройти, но не прошли — сервис переносит их на ближайший рабочий день',
    items: events.filter((item) => item.overdue_from),
  },
  {
    title: 'Обязательные платежи',
    hint: 'налоги, зарплата, аренда, кредиты — найдены по вашей истории',
    items: events.filter((item) => !item.overdue_from && item.amount < 0 && item.mandatory),
  },
  {
    title: 'Ожидаемые поступления',
    hint: 'оплаты клиентов и другие поступления, о которых известно заранее',
    items: events.filter((item) => item.amount > 0),
  },
  {
    title: 'Прочие расходы',
    hint: 'необязательные — их можно перенести, если денег будет не хватать',
    items: events.filter((item) => !item.overdue_from && item.amount < 0 && !item.mandatory),
  },
]

interface PaymentListProps {
  events: ForecastEvent[]
  selectedDate: string | null
  onChange: (change: EventChange) => void
  onSelectDate: (date: string) => void
}

const PaymentList = ({ events, selectedDate, onChange, onSelectDate }: PaymentListProps) => {
  const [editingId, setEditingId] = useState<string | null>(null)
  const groups = groupEvents(events).filter((group) => group.items.length > 0)

  const handleRemove = (event: ForecastEvent) => {
    onChange({
      event: { ...event, amount: 0, source: 'manual' },
      text: `убрано: ${eventTitle(event)} ${shortDate(event.date)}`,
    })
  }

  const handleSave = (event: ForecastEvent, date: string, amount: number) => {
    setEditingId(null)
    onChange({
      event: { ...event, date, amount, source: 'manual', overdue_from: null },
      text: `${eventTitle(event)}: ${shortDate(date)}, ${shortMoney(amount, true)}`,
    })
  }

  return (
    <Card
      title="Календарь платежей"
      subtitle="Поправьте дату или сумму, если знаете точнее, — прогноз пересчитается за секунду."
      tour="events"
    >
      {groups.map((group) => (
        <div key={group.title} className={styles.group}>
          <h4 className={styles.groupTitle}>{group.title} <span className={styles.hint}>— {group.hint}</span></h4>
          <ul className={styles.list}>
            {group.items.map((item) => {
              const id = `${item.stream_id}-${item.date}`
              const canEdit = Boolean(item.stream_id) && !item.stream_id?.includes('#')
              return (
                <li key={id} className={styles.row} data-selected={item.date === selectedDate}>
                  <button type="button" className={styles.date} onClick={() => onSelectDate(item.date)}>
                    {weekdayDate(item.date)}
                  </button>
                  <div className={styles.name}>
                    <b>{eventTitle(item)}</b>
                    <span className={styles.meta}>
                      {item.counterparty_name ? `${item.counterparty_name} · ` : ''}{SOURCE_NAMES[item.source] ?? item.source}
                      {item.confidence < 0.99 ? ` · ${confidenceWord(item.confidence)} (${percent(item.confidence)})` : ''}
                      {item.overdue_from ? ` · должен был пройти ${shortDate(item.overdue_from)}` : ''}
                    </span>
                  </div>
                  <span>
                    {item.periodicity && item.periodicity !== 'once' && (
                      <span className={styles.periodicity}>
                        <Icon name="repeat" />
                        {PERIODICITY_NAMES[item.periodicity]}
                      </span>
                    )}
                  </span>
                  <div className={styles.amount} data-sign={item.amount < 0 ? 'out' : 'in'}>{shortMoney(item.amount, true)}</div>
                  <div className={styles.actions}>
                    {canEdit && (
                      <>
                        <Button
                          variant="ghost"
                          shape="square"
                          size="sm"
                          onClick={() => setEditingId(editingId === id ? null : id)}
                          aria-label={`Изменить: ${eventTitle(item)}`}
                          title="Изменить"
                        >
                          <Icon name="pencil" />
                        </Button>
                        <Button
                          variant="dangerGhost"
                          shape="square"
                          size="sm"
                          onClick={() => handleRemove(item)}
                          aria-label={`Убрать: ${eventTitle(item)}`}
                          title="Убрать из прогноза"
                        >
                          <Icon name="trash" />
                        </Button>
                      </>
                    )}
                  </div>
                  {editingId === id && (
                    <PaymentEditForm
                      event={item}
                      onCancel={() => setEditingId(null)}
                      onSave={(date, amount) => handleSave(item, date, amount)}
                    />
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </Card>
  )
}

export default PaymentList
