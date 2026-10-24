import { useState, type FormEvent } from 'react';
import Button from '@/components/Button';
import Card from '@/components/Card';
import Chip from '@/components/Chip';
import type { Forecast } from '@/api/types';
import { approxMoney, categoryName, longDate, probabilityLevel, shortDate, shortMoney } from '@/utils/format';
import styles from './AskBox.module.css';

const SUGGESTIONS = ['Когда может не хватить денег?', 'Почему так?', 'Что лучше сделать?', 'Сколько нужно найти?']
const MAX_ANSWERS = 5

interface Answer {
  question: string
  answer: string
}

const templateAnswer = (question: string, forecast: Forecast) => {
  const text = question.toLowerCase()
  const gap = forecast.gaps[0]
  if (/когда|дат/.test(text)) {
    return gap
      ? `Первый риск нехватки — ${longDate(gap.date)} (${probabilityLevel(gap.probability).word}).`
      : 'В ближайшие 30 дней риска нехватки не видно.'
  }
  if (/сколько|сумм/.test(text)) {
    if (gap?.shortfall_at_gap === undefined) {
      return 'Нехватки не ожидается.'
    }
    return `К ${longDate(gap.date)} нужно найти ${approxMoney(gap.shortfall_at_gap)}, `
      + `с запасом — до ${shortMoney(gap.shortfall_at_gap_high ?? gap.shortfall_at_gap)}.`
  }
  if (/почему|причин/.test(text)) {
    return gap ? `${gap.reasons.slice(0, 3).join('. ')}.` : 'Поступления в ближайший месяц покрывают все известные платежи.'
  }
  if (/что делать|совет|как/.test(text)) {
    return gap?.actions[0]
      ?? 'Ничего срочного делать не нужно. Можно добавить в календарь ожидаемые крупные расходы, чтобы прогноз их учёл.'
  }
  const biggest = forecast.events.filter((item) => item.amount < 0).sort((a, b) => a.amount - b.amount)[0]
  if (!biggest) {
    return 'Спросите «когда может не хватить», «сколько нужно», «почему» или «что делать».'
  }
  return `Самый крупный ближайший платёж — ${categoryName(biggest.category)} ${shortDate(biggest.date)}, `
    + `${approxMoney(-biggest.amount)}. Спросите «когда», «сколько», «почему» или «что делать».`
}

interface AskBoxProps {
  forecast: Forecast
  isDemo: boolean
  onAsk: (question: string) => Promise<string | null>
}

const AskBox = ({ forecast, isDemo, onAsk }: AskBoxProps) => {
  const [question, setQuestion] = useState('')
  const [answers, setAnswers] = useState<Answer[]>([])
  const [isAsking, setIsAsking] = useState(false)

  const ask = async (text: string) => {
    if (!text.trim()) {
      return
    }
    setIsAsking(true)
    const serviceAnswer = isDemo ? null : await onAsk(text)
    const answer = serviceAnswer ?? templateAnswer(text, forecast)
    setAnswers((current) => [{ question: text, answer }, ...current].slice(0, MAX_ANSWERS))
    setQuestion('')
    setIsAsking(false)
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void ask(question)
  }

  return (
    <Card
      title="Спросите о своих деньгах"
      subtitle="Ответ строится только по вашему прогнозу — сервис не придумывает цифры."
      tour="ask"
    >
      <form className={styles.form} onSubmit={handleSubmit}>
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Например: хватит ли на зарплату 12-го?"
          maxLength={300}
        />
        <Button type="submit" disabled={isAsking || !question.trim()}>{isAsking ? 'Думаю…' : 'Спросить'}</Button>
      </form>
      <div className={styles.suggestions}>
        {SUGGESTIONS.map((suggestion) => (
          <Chip key={suggestion} onClick={() => void ask(suggestion)}>{suggestion}</Chip>
        ))}
      </div>
      {answers.map((item, index) => (
        <div key={`${item.question}-${index}`} className={styles.answer}>
          <div className={styles.question}>{item.question}</div>
          <div>{item.answer}</div>
        </div>
      ))}
    </Card>
  )
}

export default AskBox
