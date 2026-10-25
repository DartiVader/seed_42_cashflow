import Button from '@/components/Button';
import Card from '@/components/Card';
import type { Forecast } from '@/api/types';
import { buildTrace, formatDuration } from '@/utils/forecastTrace';
import { longDate } from '@/utils/format';
import styles from './Trace.module.css';

interface TraceProps {
  forecast: Forecast
  companyId: string | null
  elapsedMs: number | null
  isDemo: boolean
}

const download = (forecast: Forecast, companyId: string | null) => {
  const payload = { exported_at: new Date().toISOString(), company_id: companyId, forecast }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `raschet_${companyId ?? forecast.company_id}_${forecast.as_of}.json`
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

const Trace = ({ forecast, companyId, elapsedMs, isDemo }: TraceProps) => {
  const trace = buildTrace(forecast)
  const totalMs = trace.totalMs ?? elapsedMs

  return (
    <Card
      title="Как посчитан прогноз"
      tour="trace"
      aside={<Button variant="secondary" onClick={() => download(forecast, companyId)}>Скачать расчёт</Button>}
    >
      <p className={styles.meta}>
        Модель <b>{forecast.model_version}</b> · прогноз от {longDate(forecast.as_of)}
        {totalMs !== null && ` · посчитано за ${formatDuration(totalMs)}`}
        {isDemo && ' · демо-данные'}
      </p>
      {trace.isTemplate && (
        <p className={styles.note}>
          Упрощённое описание: шаги собраны по итогам прогноза, подробный журнал расчёта сервис пока не прислал.
        </p>
      )}
      <ol className={styles.steps}>
        {trace.steps.map((step) => (
          <li key={step.step} className={styles.step}>
            <span className={styles.number}>{step.step}</span>
            <div className={styles.body}>
              <div className={styles.head}>
                <span className={styles.title}>{step.title}</span>
                {step.durationMs !== undefined && <span className={styles.time}>{formatDuration(step.durationMs)}</span>}
              </div>
              {step.lines.length > 0 && (
                <ul className={styles.lines}>
                  {step.lines.map((line) => <li key={line}>{line}</li>)}
                </ul>
              )}
            </div>
          </li>
        ))}
      </ol>
    </Card>
  )
}

export default Trace
