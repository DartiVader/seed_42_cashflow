import type { Direction } from '@/api/types';

const moneyFormat = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', minimumFractionDigits: 2 })
const dateFormat = new Intl.DateTimeFormat('ru-RU')

export const formatMoney = (amount: number, direction: Direction) => {
  const sign = direction === 'Поступление' ? '+' : '−'
  return `${sign} ${moneyFormat.format(amount)}`
}

export const formatDate = (isoDate: string) => dateFormat.format(new Date(`${isoDate}T00:00:00`))
