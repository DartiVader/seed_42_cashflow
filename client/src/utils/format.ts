import type { Direction } from '@/api/types';

const moneyFormat = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', minimumFractionDigits: 2 })
const dateFormat = new Intl.DateTimeFormat('ru-RU')

export const formatMoney = (amount: number, direction: Direction) => {
  const sign = direction === 'Поступление' ? '+' : '−'
  return `${sign} ${moneyFormat.format(amount)}`
}

export const formatDate = (isoDate: string) => dateFormat.format(new Date(`${isoDate}T00:00:00`))

const MONTHS_GENITIVE = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
  'сентября', 'октября', 'ноября', 'декабря']
const WEEKDAYS_SHORT = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']

const oneDecimalFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const integerFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

export const shortMoney = (value: number, withSign = false) => {
  let sign = ''
  if (value < 0) {
    sign = '−'
  } else if (withSign && value > 0) {
    sign = '+'
  }
  const abs = Math.abs(value)
  if (abs >= 1_000_000) {
    return `${sign}${oneDecimalFormat.format(abs / 1_000_000)} млн ₽`
  }
  if (abs >= 10_000) {
    return `${sign}${integerFormat.format(abs / 1000)} тыс. ₽`
  }
  if (abs >= 1000) {
    return `${sign}${oneDecimalFormat.format(abs / 1000)} тыс. ₽`
  }
  return `${sign}${integerFormat.format(abs)} ₽`
}

export const approxMoney = (value: number) => `~${shortMoney(value)}`

export const parseIso = (isoDate: string) => new Date(`${isoDate}T00:00:00`)

export const toIso = (date: Date) => {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

export const addDays = (isoDate: string, days: number) => {
  const date = parseIso(isoDate)
  date.setDate(date.getDate() + days)
  return toIso(date)
}

export const addMonths = (isoDate: string, months: number) => {
  const date = parseIso(isoDate)
  const day = date.getDate()
  date.setDate(1)
  date.setMonth(date.getMonth() + months)
  const lastDay = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate()
  date.setDate(Math.min(day, lastDay))
  return toIso(date)
}

export const daysBetween = (fromIsoDate: string, toIsoDate: string) =>
  Math.round((parseIso(toIsoDate).getTime() - parseIso(fromIsoDate).getTime()) / 86_400_000)

export const shortDate = (isoDate: string) => {
  const date = parseIso(isoDate)
  return `${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}`
}

export const longDate = (isoDate: string) => {
  const date = parseIso(isoDate)
  return `${date.getDate()} ${MONTHS_GENITIVE[date.getMonth()]}`
}

export const weekdayDate = (isoDate: string) => {
  const date = parseIso(isoDate)
  return `${WEEKDAYS_SHORT[date.getDay()]}, ${date.getDate()} ${MONTHS_GENITIVE[date.getMonth()]}`
}

export const isWeekend = (isoDate: string) => {
  const day = parseIso(isoDate).getDay()
  return day === 0 || day === 6
}

export const pluralDays = (count: number) => {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) {
    return `${count} день`
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} дня`
  }
  return `${count} дней`
}

export interface ProbabilityLevel {
  word: string
  tone: 'ok' | 'low' | 'mid' | 'high' | 'max'
}

export const probabilityLevel = (probability: number): ProbabilityLevel => {
  if (probability < 0.15) {
    return { word: 'маловероятно', tone: 'ok' }
  }
  if (probability < 0.35) {
    return { word: 'возможно', tone: 'low' }
  }
  if (probability < 0.65) {
    return { word: 'вероятно', tone: 'mid' }
  }
  if (probability < 0.85) {
    return { word: 'очень вероятно', tone: 'high' }
  }
  return { word: 'почти наверняка', tone: 'max' }
}

export const naturalFrequency = (probability: number) => {
  const outOfTen = Math.round(probability * 10)
  if (outOfTen <= 0) {
    return 'меньше чем в 1 случае из 10'
  }
  if (outOfTen >= 10) {
    return 'почти во всех случаях'
  }
  return `примерно в ${outOfTen} ${outOfTen === 1 ? 'случае' : 'случаях'} из 10`
}

export const percent = (probability: number) => `${Math.round(probability * 100)}%`

const CATEGORY_NAMES: Record<string, string> = {
  salary: 'Зарплата',
  salary_advance: 'Зарплата (аванс)',
  salary_settlement: 'Зарплата (расчёт)',
  contractor_gph: 'Договоры ГПХ',
  tax_enp: 'Единый налоговый платёж',
  tax_other: 'Налоги и взносы',
  rent: 'Аренда',
  utilities: 'Коммунальные услуги',
  telecom: 'Связь и интернет',
  suppliers: 'Закупки у поставщиков',
  capex: 'Оборудование и ремонт',
  software: 'ПО и подписки',
  marketing: 'Реклама',
  transport: 'Транспорт и топливо',
  services_other: 'Услуги подрядчиков',
  loan_repayment: 'Погашение кредита',
  leasing: 'Лизинг',
  bank_fee: 'Комиссии банка',
  revenue_client: 'Оплата от клиента',
  revenue_acquiring: 'Эквайринг',
  revenue_marketplace: 'Выплата маркетплейса',
  income_subsidy: 'Субсидия',
  other: 'Прочее',
  manual: 'Вручную',
}

export const categoryName = (code: string | null | undefined) => (code && CATEGORY_NAMES[code]) || code || 'Платёж'

export const SOURCE_NAMES: Record<string, string> = {
  regular: 'по истории',
  manual: 'добавлено вами',
  invoice: 'счёт',
  contract: 'договор',
  tax: 'налоговый календарь',
  bank: 'банк',
  history: 'по истории',
}

export const PERIODICITY_NAMES: Record<string, string> = {
  once: 'Разово',
  monthly: 'Ежемесячно',
  monthly_irregular: 'Ежемесячно (с пропусками)',
  quarterly: 'Ежеквартально',
  bimonthly: 'Раз в 2 месяца',
  seasonal: 'Сезонно',
}
