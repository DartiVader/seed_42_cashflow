import type { Forecast } from '@/api/types';
import styles from './DataQualityNotes.module.css';

interface DataQualityNotesProps {
  forecast: Forecast
  isDemo: boolean
}

const collectNotes = (forecast: Forecast) => {
  const quality = forecast.data_quality ?? {}
  const notes: string[] = []
  if (quality.short_history) {
    notes.push('История операций короче трёх месяцев — прогноз приблизительный, коридор шире.')
  }
  if ((quality.gaps_in_data ?? 0) > 0) {
    notes.push(`В выписке есть пропуски (${quality.gaps_in_data}) — эти дни не учитывались при обучении.`)
  }
  if ((quality.days_since_last_operation ?? 0) > 3) {
    notes.push(`Последняя операция в выписке — ${quality.days_since_last_operation} дн. назад. `
      + 'Загрузите свежую выписку для точного прогноза.')
  }
  if (quality.industry_known === false) {
    notes.push('Вид деятельности неизвестен — сезонность отрасли не учитывается.')
  }
  return notes
}

const DataQualityNotes = ({ forecast, isDemo }: DataQualityNotesProps) => {
  const notes = collectNotes(forecast)
  if (notes.length === 0 && !isDemo) {
    return null
  }

  return (
    <div className={styles.notes}>
      {isDemo && (
        <p className={styles.demo}>
          <b>Демо-режим.</b> Сервис прогноза сейчас недоступен или вы смотрите пример — расчёт упрощённый,
          все кнопки работают. Модель: {forecast.model_version}.
        </p>
      )}
      {notes.map((note) => <p key={note}>{note}</p>)}
    </div>
  )
}

export default DataQualityNotes
