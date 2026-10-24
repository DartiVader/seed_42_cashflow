import { useState, type ChangeEvent, type FormEvent } from 'react';
import Button from '@/components/Button';
import DataPanel from '@/components/DataPanel';
import { getErrorMessages } from '@/api/api';
import { importsApi } from '@/api/imports';
import type { ImportFileType, ImportReport } from '@/api/types';
import { useAuth } from '@/context/AuthContext';
import { reportStorage } from '@/utils/reportStorage';

const FILE_TITLES: Record<ImportFileType, string> = {
  COMPANIES: 'Справочник компаний',
  OPERATIONS: 'Выписка операций',
}

const DashboardPage = () => {
  const { user } = useAuth()
  const userId = user?.id ?? 0
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [report, setReport] = useState<ImportReport | null>(() => reportStorage.get(userId))
  const [errors, setErrors] = useState<string[]>([])
  const [refreshKey, setRefreshKey] = useState(0)

  const isUploading = progress !== null

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null)
    setErrors([])
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!file) {
      return
    }
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
    <main>
      <h1>Дашборд</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Файл CSV: выписка или справочник компаний
          <input type="file" accept=".csv" onChange={handleFileChange} disabled={isUploading} />
        </label>
        <Button type="submit" disabled={!file || isUploading}>Загрузить</Button>
      </form>
      {progress !== null && (
        <p>{progress < 100 ? `Отправляем файл: ${progress}%` : 'Файл отправлен, проверяем и сохраняем строки…'}</p>
      )}
      {errors.map((error) => <p key={error}>{error}</p>)}
      {report && (
        <section>
          <h2>{FILE_TITLES[report.fileType]}: последняя загрузка</h2>
          <p>Строк в файле: {report.total}</p>
          <p>Сохранено: {report.accepted}</p>
          <p>Уже были загружены раньше: {report.skipped}</p>
          <p>Не приняты: {report.rejected}</p>
          {report.errors.length > 0 && (
            <ul>
              {report.errors.map((error) => (
                <li key={error.lineNumber}>Строка {error.lineNumber}: {error.message}</li>
              ))}
            </ul>
          )}
          {report.rejected > report.errors.length && (
            <p>Показаны первые {report.errors.length} ошибок из {report.rejected}</p>
          )}
        </section>
      )}
      <DataPanel refreshKey={refreshKey} />
    </main>
  )
}

export default DashboardPage
