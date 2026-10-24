import { useState } from 'react';
import DataPanel from '@/components/DataPanel';
import { getErrorMessages } from '@/api/api';
import { importsApi } from '@/api/imports';
import type { ImportReport } from '@/api/types';
import { useAuth } from '@/context/AuthContext';
import { reportStorage } from '@/utils/reportStorage';
import UploadZone from '@/pages/DashboardPage/components/UploadZone';
import UploadProgress from '@/pages/DashboardPage/components/UploadProgress';
import styles from './DashboardPage.module.css';

const DashboardPage = () => {
  const { user } = useAuth()
  const userId = user?.id ?? 0
  const [progress, setProgress] = useState<number | null>(null)
  const [report, setReport] = useState<ImportReport | null>(() => reportStorage.get(userId))
  const [errors, setErrors] = useState<string[]>([])
  const [refreshKey, setRefreshKey] = useState(0)

  const isUploading = progress !== null

  const uploadFile = async (file: File) => {
    setErrors([])
    setProgress(0)
    // TODO: временный замер времени загрузки файла — убрать после проверки производительности (начало)
    const startedAt = performance.now()
    let uploadedAt = startedAt
    const handleProgress = (percent: number) => {
      setProgress(percent)
      if (percent === 100) {
        uploadedAt = performance.now()
      }
    }
    // TODO: временный замер времени загрузки файла — убрать после проверки производительности (конец)
    try {
      const uploadedReport = await importsApi.upload(file, handleProgress)
      // TODO: временный замер времени загрузки файла — убрать после проверки производительности (начало)
      const finishedAt = performance.now()
      console.log(`Замер загрузки «${file.name}»: отправка ${((uploadedAt - startedAt) / 1000).toFixed(1)} с, `
        + `обработка на сервере ${((finishedAt - uploadedAt) / 1000).toFixed(1)} с, `
        + `всего ${((finishedAt - startedAt) / 1000).toFixed(1)} с`)
      // TODO: временный замер времени загрузки файла — убрать после проверки производительности (конец)
      setReport(uploadedReport)
      reportStorage.set(userId, uploadedReport)
      setRefreshKey((current) => current + 1)
    } catch (error) {
      setErrors(getErrorMessages(error))
    } finally {
      setProgress(null)
    }
  }

  return (
    <>
      <UploadProgress progress={progress} />
      <main className={styles.page}>
        <div className={styles.heading}>
          <h1>Анализ денежных потоков</h1>
          <p className={styles.subtitle}>
            Загрузите банковскую выписку или справочник компаний — операции и компании появятся в таблице ниже
          </p>
        </div>
        <UploadZone isCompact={report !== null} isUploading={isUploading} onFileSelect={uploadFile} />
        {errors.map((error) => <p key={error} className={styles.error}>{error}</p>)}
        <DataPanel refreshKey={refreshKey} />
      </main>
    </>
  )
}

export default DashboardPage
