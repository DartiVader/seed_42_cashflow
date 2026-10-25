import { useState } from 'react';
import { useNavigate } from 'react-router';
import Button from '@/components/Button';
import type { UploadSummary } from '@/pages/DashboardPage/useDatasetUpload';
import styles from './ImportSummary.module.css';

const seconds = (ms: number) => {
  const value = ms / 1000
  return value < 10 ? `${value.toFixed(1).replace('.', ',')} с` : `${Math.round(value)} с`
}

const ImportSummary = ({ summary }: { summary: UploadSummary }) => {
  const navigate = useNavigate()
  const [companyId, setCompanyId] = useState(summary.companyIds[0] ?? '')

  const tiles = [
    { label: 'Компаний', value: summary.companies.toLocaleString('ru-RU') },
    { label: 'Операций', value: summary.operations.toLocaleString('ru-RU') },
    { label: 'Отклонено строк', value: summary.rejected.toLocaleString('ru-RU'), alert: summary.rejected > 0 },
    { label: 'Время', value: seconds(summary.tookMs) },
  ]

  return (
    <section className={styles.card}>
      <div className={styles.head}>
        <h2 className={styles.title}>Загрузка завершена</h2>
        {summary.skipped > 0 && (
          <span className={styles.note}>
            {summary.skipped.toLocaleString('ru-RU')} операций уже были загружены раньше — пропустили
          </span>
        )}
      </div>
      <div className={styles.tiles}>
        {tiles.map((tile) => (
          <div key={tile.label} className={styles.tile} data-alert={tile.alert || undefined}>
            <span className={styles.value}>{tile.value}</span>
            <span className={styles.label}>{tile.label}</span>
          </div>
        ))}
      </div>
      {summary.failedFiles > 0 && (
        <p className={styles.warning}>Не загружено файлов: {summary.failedFiles}. Причины — в списке файлов выше.</p>
      )}
      {summary.companyIds.length > 0 && (
        <div className={styles.actions}>
          <label className={styles.select}>
            Компания
            <select value={companyId} onChange={(event) => setCompanyId(event.target.value)}>
              {summary.companyIds.map((id) => <option key={id} value={id}>{id}</option>)}
            </select>
          </label>
          <Button onClick={() => navigate(`/forecast/${encodeURIComponent(companyId)}`)} disabled={!companyId}>
            Открыть прогноз
          </Button>
        </div>
      )}
    </section>
  )
}

export default ImportSummary
