import { useCallback, useEffect, useState, type FormEvent } from 'react';
import Button from '@/components/Button';
import Card from '@/components/Card';
import SegmentedControl from '@/components/SegmentedControl';
import { getErrorMessages } from '@/api/api';
import { companiesApi } from '@/api/companies';
import { marketplacesApi } from '@/api/marketplaces';
import type { Company, Marketplace, MarketplaceConnection, MarketplaceSyncResult } from '@/api/types';
import { addMonths, toIso } from '@/utils/format';
import styles from './Marketplaces.module.css';

const MARKETPLACES: { value: Marketplace, label: string }[] = [
  { value: 'ozon', label: 'OZON' },
  { value: 'wb', label: 'Wildberries' },
  { value: 'yandex', label: 'Яндекс Маркет' },
]

interface Field {
  key: 'clientId' | 'apiKey' | 'token' | 'businessId'
  label: string
  hint: string
  isSecret?: boolean
}

const FIELDS: Record<Marketplace, Field[]> = {
  ozon: [
    { key: 'clientId', label: 'Client-Id', hint: 'Seller API → Настройки → API-ключи' },
    { key: 'apiKey', label: 'Api-Key', hint: 'ключ с доступом к финансовым отчётам', isSecret: true },
  ],
  wb: [{ key: 'token', label: 'Токен', hint: 'Профиль → Настройки → Доступ к API, категория «Финансы»', isSecret: true }],
  yandex: [
    { key: 'token', label: 'Токен', hint: 'Настройки → API и модули, доступ к отчётам', isSecret: true },
    { key: 'businessId', label: 'Идентификатор кабинета', hint: 'businessId из ссылки на кабинет' },
  ],
}

type Credentials = Partial<Record<Field['key'], string>>

const today = toIso(new Date())
const formatDateTime = (iso: string) => new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })

const resultText = (result: MarketplaceSyncResult) =>
  `${result.dateFrom} — ${result.dateTo}: принято ${result.accepted.toLocaleString('ru-RU')}, `
  + `уже были ${result.skipped.toLocaleString('ru-RU')}, отклонено ${result.rejected.toLocaleString('ru-RU')}`

interface ConnectionCardProps {
  connection: MarketplaceConnection
  companyName?: string
  onSynced: () => void
  onRemoved: () => void
}

const ConnectionCard = ({ connection, companyName, onSynced, onRemoved }: ConnectionCardProps) => {
  const [dateFrom, setDateFrom] = useState(() => addMonths(today, -3))
  const [dateTo, setDateTo] = useState(today)
  const [isSyncing, setIsSyncing] = useState(false)
  const [result, setResult] = useState<MarketplaceSyncResult | null>(null)
  const [errors, setErrors] = useState<string[]>([])

  const sync = async () => {
    setIsSyncing(true)
    setErrors([])
    try {
      setResult(await marketplacesApi.sync(connection.id, dateFrom, dateTo))
      onSynced()
    } catch (error) {
      setErrors(getErrorMessages(error))
    } finally {
      setIsSyncing(false)
    }
  }

  const remove = async () => {
    try {
      await marketplacesApi.disconnect(connection.id)
      onRemoved()
    } catch (error) {
      setErrors(getErrorMessages(error))
    }
  }

  const last = result ?? connection.lastResult

  return (
    <section className={styles.connection} data-marketplace={connection.marketplace}>
      <div className={styles.connectionHead}>
        <div>
          <b className={styles.connectionTitle}>{connection.marketplaceName}</b>
          <p className={styles.muted}>{connection.companyId}{companyName ? ` · ${companyName}` : ''}</p>
        </div>
        <span className={styles.key}>{connection.clientId ? `${connection.clientId} · ` : ''}{connection.keyMasked}</span>
      </div>
      <div className={styles.period}>
        <label>
          С
          <input type="date" value={dateFrom} max={dateTo} onChange={(event) => setDateFrom(event.target.value)} />
        </label>
        <label>
          По
          <input type="date" value={dateTo} min={dateFrom} onChange={(event) => setDateTo(event.target.value)} />
        </label>
        <Button onClick={sync} disabled={isSyncing || !dateFrom || !dateTo}>
          {isSyncing ? 'Загружаем отчёт…' : 'Загрузить отчёт'}
        </Button>
      </div>
      {last && <p className={styles.result} data-fresh={result !== null || undefined}>{resultText(last)}</p>}
      {result?.classifying && <p className={styles.muted}>Категории операций считаются — это займёт до минуты</p>}
      {errors.map((error) => <p key={error} className={styles.error}>{error}</p>)}
      <div className={styles.connectionFoot}>
        <span className={styles.muted}>
          {connection.lastSyncAt ? `последняя загрузка ${formatDateTime(connection.lastSyncAt)}` : 'отчёты ещё не загружали'}
        </span>
        <Button variant="dangerGhost" size="sm" onClick={remove} disabled={isSyncing}>Отключить</Button>
      </div>
    </section>
  )
}

const Marketplaces = ({ onSynced }: { onSynced: () => void }) => {
  const [companies, setCompanies] = useState<Company[]>([])
  const [connections, setConnections] = useState<MarketplaceConnection[] | null>(null)
  const [marketplace, setMarketplace] = useState<Marketplace>('ozon')
  const [companyId, setCompanyId] = useState('')
  const [credentials, setCredentials] = useState<Credentials>({})
  const [isConnecting, setIsConnecting] = useState(false)
  const [errors, setErrors] = useState<string[]>([])

  const reload = useCallback(() => {
    marketplacesApi.list().then(setConnections).catch((error) => setErrors(getErrorMessages(error)))
  }, [])

  useEffect(() => {
    reload()
    companiesApi.listAll().then((list) => {
      setCompanies(list)
      setCompanyId((current) => current || list[0]?.companyId || '')
    }).catch(() => setCompanies([]))
  }, [reload])

  const changeMarketplace = (value: Marketplace) => {
    setMarketplace(value)
    setCredentials({})
    setErrors([])
  }

  const connect = async (event: FormEvent) => {
    event.preventDefault()
    setIsConnecting(true)
    setErrors([])
    try {
      await marketplacesApi.connect({ companyId, marketplace, ...credentials })
      setCredentials({})
      reload()
    } catch (error) {
      setErrors(getErrorMessages(error))
    } finally {
      setIsConnecting(false)
    }
  }

  const companyName = (id: string) => companies.find((item) => item.companyId === id)?.companyName

  return (
    <div className={styles.layout}>
      <Card
        title="Подключить маркетплейс"
        subtitle="Отчёты о продажах, комиссиях и доставке станут операциями компании и попадут в прогноз"
      >
        <form className={styles.form} onSubmit={connect}>
          <SegmentedControl options={MARKETPLACES} value={marketplace} onChange={changeMarketplace} />
          <label>
            Компания
            <select value={companyId} onChange={(event) => setCompanyId(event.target.value)} required>
              {companies.length === 0 && <option value="">Сначала загрузите справочник компаний</option>}
              {companies.map((item) => (
                <option key={item.companyId} value={item.companyId}>{item.companyId} · {item.companyName}</option>
              ))}
            </select>
          </label>
          {FIELDS[marketplace].map((field) => (
            <div key={field.key} className={styles.field}>
              <label>
                {field.label}
                <input
                  type={field.isSecret ? 'password' : 'text'}
                  autoComplete="off"
                  aria-describedby={`mp-hint-${field.key}`}
                  value={credentials[field.key] ?? ''}
                  onChange={(event) => setCredentials((current) => ({ ...current, [field.key]: event.target.value }))}
                  required
                />
              </label>
              <span id={`mp-hint-${field.key}`} className={styles.hint}>{field.hint}</span>
            </div>
          ))}
          {errors.map((error) => <p key={error} className={styles.error}>{error}</p>)}
          <Button type="submit" disabled={isConnecting || !companyId}>
            {isConnecting ? 'Проверяем ключ…' : 'Подключить'}
          </Button>
          <p className={styles.note}>
            Ключ проверяется пробным запросом и хранится только на сервере — здесь видны лишь последние 4 символа.
            Если выплаты маркетплейса уже есть в банковской выписке, загружайте отчёт за другой период — иначе суммы
            учтутся дважды.
          </p>
        </form>
      </Card>

      <div className={styles.connections}>
        {connections === null && <p className={styles.muted}>Загружаем подключения…</p>}
        {connections?.length === 0 && (
          <div className={styles.empty}>
            <b>Маркетплейсы ещё не подключены</b>
            <p className={styles.muted}>Подключите OZON, Wildberries или Яндекс Маркет — отчёты можно будет загружать за любой период.</p>
          </div>
        )}
        {connections?.map((connection) => (
          <ConnectionCard
            key={connection.id}
            connection={connection}
            companyName={companyName(connection.companyId)}
            onSynced={() => {
              reload()
              onSynced()
            }}
            onRemoved={reload}
          />
        ))}
      </div>
    </div>
  )
}

export default Marketplaces
