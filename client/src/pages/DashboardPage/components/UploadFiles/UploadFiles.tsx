import type { FileStatus, UploadItem } from '@/pages/DashboardPage/useDatasetUpload';
import styles from './UploadFiles.module.css';

interface UploadFilesProps {
  items: UploadItem[]
  progress: number | null
}

const STATUS_TEXT: Record<FileStatus, string> = {
  waiting: 'ждёт',
  uploading: 'загружается',
  processing: 'обрабатывается',
  done: 'готово',
  failed: 'не загружен',
}

const TYPE_TEXT = { COMPANIES: 'справочник компаний', OPERATIONS: 'выписка' }

const statusOf = (item: UploadItem) => {
  if (item.status === 'done' && (item.rejected ?? 0) > 0) {
    return { text: `ошибки: ${item.rejected}`, tone: 'warning' }
  }
  return { text: STATUS_TEXT[item.status], tone: item.status }
}

const UploadFiles = ({ items, progress }: UploadFilesProps) => {
  if (items.length === 0) {
    return null
  }
  const finished = items.filter((item) => item.status === 'done' || item.status === 'failed').length

  return (
    <section className={styles.panel} aria-live="polite">
      <div className={styles.head}>
        <span className={styles.title}>Файлы</span>
        <span className={styles.muted}>
          {progress !== null ? `отправлено ${progress}%` : `обработано ${finished} из ${items.length}`}
        </span>
      </div>
      {progress !== null && (
        <div className={styles.track} role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
          <div className={styles.bar} style={{ width: `${progress}%` }} />
        </div>
      )}
      <ul className={styles.list}>
        {items.map((item, index) => {
          const status = statusOf(item)
          return (
            <li key={`${item.name}-${index}`} className={styles.item}>
              <span className={styles.name} title={item.name}>{item.name}</span>
              <span className={styles.muted}>
                {item.fileType ? TYPE_TEXT[item.fileType] : ''}
                {item.status === 'done' && item.accepted !== undefined && ` · принято ${item.accepted.toLocaleString('ru-RU')}`}
              </span>
              <span className={styles.status} data-tone={status.tone}>{status.text}</span>
              {item.message && <span className={styles.message}>{item.message}</span>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export default UploadFiles
