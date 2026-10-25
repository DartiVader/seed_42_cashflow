import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import DataPanel from '@/components/DataPanel';
import SideNav, { type SideNavGroup } from '@/components/SideNav';
import { companiesApi } from '@/api/companies';
import { operationsApi } from '@/api/operations';
import { useAuth } from '@/context/AuthContext';
import { reportStorage } from '@/utils/reportStorage';
import DataStats from '@/pages/DashboardPage/components/DataStats';
import FileFormats from '@/pages/DashboardPage/components/FileFormats';
import ImportSummary from '@/pages/DashboardPage/components/ImportSummary';
import Marketplaces from '@/pages/DashboardPage/components/Marketplaces';
import UploadFiles from '@/pages/DashboardPage/components/UploadFiles';
import UploadProgress from '@/pages/DashboardPage/components/UploadProgress';
import UploadZone from '@/pages/DashboardPage/components/UploadZone';
import { useDatasetUpload, type UploadSummary } from '@/pages/DashboardPage/useDatasetUpload';
import styles from './DashboardPage.module.css';

type View = 'upload' | 'marketplaces' | 'companies' | 'operations'

const isView = (value: string | null): value is View =>
  value === 'upload' || value === 'marketplaces' || value === 'companies' || value === 'operations'

const TITLES: Record<View, { title: string, subtitle: string }> = {
  upload: {
    title: 'Загрузка данных',
    subtitle: 'Справочник компаний и банковские выписки — из них строится прогноз денег на 30 дней',
  },
  marketplaces: {
    title: 'Маркетплейсы',
    subtitle: 'OZON, Wildberries и Яндекс Маркет по API-ключу: отчёты о продажах и удержаниях — в операции компании',
  },
  companies: { title: 'Компании', subtitle: 'Ваши компании: можно найти, поправить или добавить вручную' },
  operations: { title: 'Операции', subtitle: 'Все операции из выписок: фильтры по сумме, дате, контрагенту и назначению' },
}

const pluralFiles = (count: number) => {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) {
    return `${count} файл`
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} файла`
  }
  return `${count} файлов`
}

interface Totals {
  companies: number | null
  operations: number | null
}

const DashboardPage = () => {
  const { user } = useAuth()
  const userId = user?.id ?? 0
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const viewParam = searchParams.get('tab')
  const view: View = isView(viewParam) ? viewParam : 'upload'
  const [summary, setSummary] = useState<UploadSummary | null>(() => reportStorage.get(userId))
  const [refreshKey, setRefreshKey] = useState(0)
  const [totals, setTotals] = useState<Totals>({ companies: null, operations: null })

  const { items, progress, errors, upload, isUploading } = useDatasetUpload((done) => {
    setSummary(done)
    reportStorage.set(userId, done)
    setRefreshKey((current) => current + 1)
  })

  useEffect(() => {
    let isActual = true
    Promise.all([companiesApi.list(0, 1, {}), operationsApi.list(0, 1, {})])
      .then(([companies, operations]) => {
        if (isActual) {
          setTotals({ companies: companies.totalElements, operations: operations.totalElements })
        }
      })
      .catch(() => {
        if (isActual) {
          setTotals({ companies: 0, operations: 0 })
        }
      })
    return () => {
      isActual = false
    }
  }, [refreshKey])

  const uploadFiles = (files: File[]) => {
    setSummary(null)
    void upload(files)
  }

  const groups: SideNavGroup[] = [
    {
      caption: 'Данные',
      isTabs: true,
      items: [
        { value: 'upload', label: 'Загрузка', icon: 'upload' },
        { value: 'marketplaces', label: 'Маркетплейсы', icon: 'cart' },
        { value: 'companies', label: 'Компании', icon: 'building', badge: totals.companies ?? undefined },
        { value: 'operations', label: 'Операции', icon: 'list', badge: totals.operations ?? undefined },
      ],
    },
    {
      caption: 'Дальше',
      items: [
        { value: 'forecast', label: 'Открыть прогноз', icon: 'home', disabled: !totals.companies },
        { value: 'quality', label: 'Качество модели', icon: 'chart' },
      ],
    },
  ]

  const handleSelect = (value: string) => {
    if (value === 'forecast') {
      navigate(summary?.companyIds[0] ? `/forecast/${encodeURIComponent(summary.companyIds[0])}` : '/forecast')
    } else if (value === 'quality') {
      navigate('/quality')
    } else {
      setSearchParams(value === 'upload' ? {} : { tab: value })
    }
  }

  const fileItems = items.length > 0 ? items : summary?.items ?? []

  return (
    <>
      <UploadProgress progress={progress} />
      <main className={styles.page}>
        <SideNav
          groups={groups}
          activeValue={view}
          onSelect={handleSelect}
          card={{
            title: 'Как загрузить',
            text: 'Сначала справочник компаний, затем выписки. Или всё сразу одним архивом ZIP — порядок сервис наведёт сам.',
            meta: 'CSV · ZIP · до 300 МБ',
          }}
        />
        <div className={styles.main}>
          <div className={styles.heading}>
            <h1 className={styles.title}>{TITLES[view].title}</h1>
            <p className={styles.subtitle}>{TITLES[view].subtitle}</p>
          </div>

          <DataStats
            companies={totals.companies}
            operations={totals.operations}
            lastUpload={summary ? pluralFiles(summary.items.length) : null}
          />

          {view === 'upload' && (
            <div key="upload" className={styles.content}>
              <UploadZone
                isCompact={summary !== null || isUploading}
                isUploading={isUploading}
                onFilesSelect={uploadFiles}
              />
              {errors.map((error) => <p key={error} className={styles.error}>{error}</p>)}
              {summary && !isUploading && <ImportSummary summary={summary} />}
              <div className={styles.columns}>
                <UploadFiles items={fileItems} progress={progress} />
                <FileFormats />
              </div>
            </div>
          )}
          {view === 'marketplaces' && (
            <div key="marketplaces" className={styles.content}>
              <Marketplaces onSynced={() => setRefreshKey((current) => current + 1)} />
            </div>
          )}
          {(view === 'companies' || view === 'operations') && (
            <div key={view} className={styles.content}>
              <DataPanel refreshKey={refreshKey} tab={view} isStacked />
            </div>
          )}
        </div>
      </main>
    </>
  )
}

export default DashboardPage
