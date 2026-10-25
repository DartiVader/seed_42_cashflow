import { useCallback, useEffect, useState } from 'react';
import Button from '@/components/Button';
import Card from '@/components/Card';
import SegmentedControl from '@/components/SegmentedControl';
import { getErrorMessages } from '@/api/api';
import { qualityApi } from '@/api/quality';
import type { QualityJob, QualityReport, QualitySource, QualitySummary } from '@/api/types';
import ConfusionMatrix from '@/pages/QualityPage/components/ConfusionMatrix';
import HorizonErrors from '@/pages/QualityPage/components/HorizonErrors';
import ReportTable from '@/pages/QualityPage/components/ReportTable';
import {
  METRICS, SEGMENTS, TARGETS, formatScore, formatShare, imageCaption, type Segment, type Target,
} from '@/pages/QualityPage/qualityText';
import styles from './QualityPage.module.css';

const COVERAGE_TARGET = 0.8
const POLL_MS = 10000

const isActive = (job?: QualityJob | null) => job?.status === 'queued' || job?.status === 'running'

const coverageRows = (summary: QualitySummary) => {
  const byHorizon = (summary.regression ?? [])
    .filter((row) => row.coverage_p10_p90 !== undefined)
    .map((row) => ({ label: `${row.horizon} дн.`, value: row.coverage_p10_p90 as number }))
  if (byHorizon.length > 0) {
    return byHorizon
  }
  return summary.coverage?.p10_p90 !== undefined ? [{ label: 'Все горизонты', value: summary.coverage.p10_p90 }] : []
}

const baselineTable = (rows: Record<string, string | number | null>[]) => {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))]
  return { columns, rows: rows.map((row) => columns.map((column) => row[column] ?? null)) }
}

const DatasetStub = () => (
  <Card title="Отчёт по датасету не найден">
    <p className={styles.text}>
      Контрольный прогон по датасету участников считается в репозитории ML (ml.evaluation.control) и лежит
      в папке reports/control. Сейчас её нет.
    </p>
  </Card>
)

const Stub = () => (
  <Card title="Отчёт ещё не построен">
    <p className={styles.text}>
      Здесь появятся результаты проверки модели на истории: насколько часто сервис заранее замечает нехватку денег,
      как часто ошибается и насколько точно прогнозирует остаток.
    </p>
    <p className={styles.text}>
      Отчёт считается по компаниям, которые загрузил администратор: после его загрузки выписок отчёт
      пересчитывается сам, или администратор запускает пересчёт кнопкой.
    </p>
  </Card>
)

interface SourceLineProps {
  report: QualityReport
  isStarting: boolean
  onRun: () => void
}

const SourceLine = ({ report, isStarting, onRun }: SourceLineProps) => {
  const { source, job, canRun } = report
  const running = isActive(job)
  return (
    <div className={styles.source}>
      <span className={styles.muted}>
        {source?.companies
          ? `Посчитано по ${source.companies} компаниям, загруженным администратором`
          : 'Отчёт по компаниям администратора ещё не посчитан'}
        {source?.computedAt && ` · ${new Date(source.computedAt).toLocaleString('ru-RU')}`}
      </span>
      {running && (
        <span className={styles.running}>
          Пересчитываем{job?.progress ? ` · ${Math.round(job.progress * 100)}%` : ''} — обычно 10–15 минут
        </span>
      )}
      {job?.status === 'failed' && job.error && <span className={styles.error}>Пересчёт не удался: {job.error}</span>}
      {canRun && (
        <Button size="sm" variant="secondary" onClick={onRun} disabled={running || isStarting}>
          {running ? 'Считается…' : 'Пересчитать'}
        </Button>
      )}
    </div>
  )
}

const QualityPage = () => {
  const [report, setReport] = useState<QualityReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [target, setTarget] = useState<Target>('shortfall')
  const [segment, setSegment] = useState<Segment>('all')
  const [isStarting, setIsStarting] = useState(false)
  const [source, setSource] = useState<QualitySource>('admin')

  const load = useCallback(() => qualityApi.get(source)
    .then((data) => {
      setReport(data)
      setError(null)
    })
    .catch((reason) => setError(getErrorMessages(reason).join(' '))), [source])

  const switchSource = () => {
    setReport(null)
    setSegment('all')
    setSource((current) => (current === 'admin' ? 'dataset' : 'admin'))
  }

  useEffect(() => {
    load()
  }, [load])

  // Пока идёт пересчёт — опрашиваем статус; когда задача закончится, придёт новый отчёт
  const running = source === 'admin' && isActive(report?.job)
  useEffect(() => {
    if (!running) {
      return
    }
    const timer = window.setInterval(load, POLL_MS)
    return () => window.clearInterval(timer)
  }, [running, load])

  const handleRun = async () => {
    setIsStarting(true)
    try {
      await qualityApi.run()
      await load()
    } catch (reason) {
      setError(getErrorMessages(reason).join(' '))
    } finally {
      setIsStarting(false)
    }
  }

  const summary = report?.summary ?? null
  const classification = segment === 'holdout' && summary?.classification_holdout
    ? summary.classification_holdout
    : summary?.classification
  const metrics = classification?.[target]
  const coverage = summary ? coverageRows(summary) : []
  const tables = Object.entries(report?.tables ?? {})

  return (
    <main className={styles.page}>
      <div>
        <h1 className={styles.title}>Качество модели</h1>
        <p className={styles.muted}>
          Как сервис справлялся на истории, которую не видел при обучении
          {summary?.model_version && ` · модель ${summary.model_version}`}
          {report?.generatedAt && ` · отчёт от ${new Date(report.generatedAt).toLocaleString('ru-RU')}`}
        </p>
      </div>

      <div className={styles.source}>
        <Button size="sm" variant="ghost" onClick={switchSource}>
          {source === 'admin' ? 'Отчёт по датасету участников' : '← Отчёт по компаниям администратора'}
        </Button>
        {source === 'dataset' && (
          <span className={styles.muted}>Контрольный прогон по датасету участников, посчитан заранее в ML</span>
        )}
      </div>
      {report && source === 'admin' && <SourceLine report={report} isStarting={isStarting} onRun={handleRun} />}
      {error && <p className={styles.error}>{error}</p>}
      {!report && !error && <div className={styles.skeleton}>Загружаем отчёт…</div>}
      {report && !report.available && (source === 'admin' ? <Stub /> : <DatasetStub />)}

      {report?.available && (
        <>
          {summary?.classification && (
            <Card title="Предупреждения о нехватке денег за 30 дней" aside={
              <div className={styles.switches}>
                {summary.classification_holdout && (
                  <SegmentedControl options={SEGMENTS} value={segment} onChange={setSegment} />
                )}
                <SegmentedControl options={TARGETS} value={target} onChange={setTarget} />
              </div>
            }>
              {metrics ? (
                <div className={styles.tiles}>
                  {METRICS.filter((metric) => metrics[metric.key] !== undefined).map((metric) => {
                    const value = metrics[metric.key] as number
                    return (
                      <div key={metric.key} className={styles.tile} title={metric.hint}>
                        <span className={styles.tileValue}>
                          {metric.kind === 'share' ? formatShare(value) : formatScore(value)}
                        </span>
                        <span className={styles.tileLabel}>{metric.label}</span>
                        <span className={styles.tileHint}>{metric.hint}</span>
                      </div>
                    )
                  })}
                </div>
              ) : <p className={styles.muted}>Для этой цели в отчёте нет метрик.</p>}
            </Card>
          )}

          {(classification?.shortfall?.confusion || classification?.negative?.confusion) && (
            <div className={styles.twoColumns}>
              {TARGETS.map(({ value, label }) => {
                const confusion = classification?.[value]?.confusion
                return confusion ? <ConfusionMatrix key={value} title={label} confusion={confusion} /> : null
              })}
            </div>
          )}

          {summary?.regression && summary.regression.length > 0 && <HorizonErrors rows={summary.regression} />}

          <div className={styles.twoColumns}>
            {coverage.length > 0 && (
              <Card
                title="Честность коридора P10–P90"
                subtitle="Цель — 80%: в 8 случаях из 10 фактический остаток должен попадать в коридор прогноза"
              >
                <div className={styles.coverage}>
                  {coverage.map((row) => (
                    <div key={row.label} className={styles.coverageRow}>
                      <span className={styles.coverageLabel}>{row.label}</span>
                      <div className={styles.coverageTrack}>
                        <div className={styles.coverageBar} style={{ width: `${Math.min(row.value, 1) * 100}%` }}
                          data-ok={Math.abs(row.value - COVERAGE_TARGET) <= 0.05 || undefined} />
                        <div className={styles.coverageTarget} style={{ left: `${COVERAGE_TARGET * 100}%` }} />
                      </div>
                      <span className={styles.coverageValue}>{formatShare(row.value)}</span>
                    </div>
                  ))}
                </div>
              </Card>
            )}
            {summary?.baselines && summary.baselines.length > 0 && (
              <Card title="Сравнение с простыми правилами"
                subtitle="naive_s5 — «как неделю назад», dow_mean — «среднее по дню недели». Модель должна их обгонять">
                <ReportTable {...baselineTable(summary.baselines)} />
              </Card>
            )}
          </div>

          {report.images && report.images.length > 0 && (
            <Card title="Графики из отчёта">
              <div className={styles.images}>
                {report.images.map((name) => (
                  <figure key={name} className={styles.figure}>
                    <img src={qualityApi.fileUrl(name, source)} alt={imageCaption(name)} loading="lazy" />
                    <figcaption>{imageCaption(name)}</figcaption>
                  </figure>
                ))}
              </div>
            </Card>
          )}

          {summary?.method && (
            <Card title="Как мы проверяли">
              <ul className={styles.method}>
                <li>
                  <b>Схема:</b> {summary.method.scheme === 'rolling-origin' || !summary.method.scheme
                    ? 'rolling-origin — прогноз строится на дату в прошлом только по данным до неё и сверяется с тем, что было потом; дата сдвигается шаг за шагом'
                    : summary.method.scheme}
                </li>
                {summary.method.companies != null && <li><b>Компаний:</b> {summary.method.companies}</li>}
                {summary.method.origins != null && (
                  <li><b>Точек прогноза (origins):</b> {summary.method.origins.toLocaleString('ru-RU')}</li>
                )}
                {summary.method.holdout && <li><b>Холдаут:</b> {summary.method.holdout}</li>}
                {summary.method.notes && <li>{summary.method.notes}</li>}
              </ul>
            </Card>
          )}

          {tables.length > 0 && (
            <details className={styles.details}>
              <summary>Все таблицы отчёта ({tables.length})</summary>
              {tables.map(([name, table]) => (
                <Card key={name} title={name}>
                  <ReportTable columns={table.columns} rows={table.rows} />
                </Card>
              ))}
            </details>
          )}
        </>
      )}
    </main>
  )
}

export default QualityPage
