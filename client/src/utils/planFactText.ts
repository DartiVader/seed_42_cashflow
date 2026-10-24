import type { PlanFactEvent, PlanFactStatus } from '@/api/types';
import { categoryName, shortMoney } from '@/utils/format';

export const PLAN_FACT_STATUS_NAMES: Record<PlanFactStatus, string> = {
  paid: 'Прошёл',
  partial: 'Частично',
  missed: 'Не прошёл',
}

export const planFactEventName = (event: PlanFactEvent) => (
  event.counterparty_name ? `${categoryName(event.category)} · ${event.counterparty_name}` : categoryName(event.category)
)

export const planFactRemainder = (event: PlanFactEvent) => event.amount_plan - (event.amount_fact ?? 0)

export const missedText = (event: PlanFactEvent) => {
  const rest = shortMoney(Math.abs(planFactRemainder(event)))
  if (event.amount_plan < 0) {
    return `не оплачено ${rest} — платёж остался в прогнозе`
  }
  return event.status === 'partial' ? `не доплатили ${rest}` : `ждали ${rest}, денег нет`
}

export const isProblem = (event: PlanFactEvent) => event.status !== 'paid'
