import { useCallback, useEffect, useMemo, useState, type ChangeEvent } from 'react';
import { useNavigate, useParams } from 'react-router';
import Button from '@/components/Button';
import Card from '@/components/Card';
import Tour from '@/components/Tour';
import { companiesApi } from '@/api/companies';
import { forecastApi } from '@/api/forecast';
import { DEMO_AS_OF, DEMO_COMPANIES } from '@/api/mocks/forecastMock';
import type { Company, ForecastEvent, ForecastRequest, Scenario } from '@/api/types';
import { useExplanation } from '@/hooks/useExplanation';
import { useForecast } from '@/hooks/useForecast';
import { usePlanFact } from '@/hooks/usePlanFact';
import { scenarioTemplate, templateSummary } from '@/utils/forecastInsights';
import { longDate, shortMoney } from '@/utils/format';
import { isProblem } from '@/utils/planFactText';
import { preferenceStorage } from '@/utils/preferenceStorage';
import AdviceList from '@/pages/ForecastPage/components/AdviceList';
import AskBox from '@/pages/ForecastPage/components/AskBox';
import BalanceChart from '@/pages/ForecastPage/components/BalanceChart';
import ChangesBar from '@/pages/ForecastPage/components/ChangesBar';
import DataQualityNotes from '@/pages/ForecastPage/components/DataQualityNotes';
import GapCard from '@/pages/ForecastPage/components/GapCard';
import Help from '@/pages/ForecastPage/components/Help';
import MissedBanner from '@/pages/ForecastPage/components/MissedBanner';
import PaymentCalendar from '@/pages/ForecastPage/components/PaymentCalendar';
import type { EventChange } from '@/pages/ForecastPage/components/PaymentList';
import PlanFact from '@/pages/ForecastPage/components/PlanFact';
import StatusHero from '@/pages/ForecastPage/components/StatusHero';
import WeekStrip from '@/pages/ForecastPage/components/WeekStrip';
import WhatIf from '@/pages/ForecastPage/components/WhatIf';
import { TOUR_STEPS } from './tourSteps';
import styles from './ForecastPage.module.css';

type Tab = 'main' | 'calendar' | 'planfact' | 'whatif' | 'help'

const TABS: { value: Tab, label: string }[] = [
  { value: 'main', label: 'Главное' },
  { value: 'calendar', label: 'Календарь платежей' },
  { value: 'planfact', label: 'План-факт' },
  { value: 'whatif', label: 'Что если' },
  { value: 'help', label: 'Как читать прогноз' },
]

const HORIZON_DAYS = 30
const TOUR_DELAY_MS = 900
const NOTICE_DURATION_MS = 4000

interface ScenarioState {
  scenario: Scenario
  title: string
}

const ForecastPage = ({ demoOnly = false }: { demoOnly?: boolean }) => {
  const navigate = useNavigate()
  const { companyId: routeCompanyId } = useParams()
  const [companies, setCompanies] = useState<Company[]>(demoOnly ? DEMO_COMPANIES : [])
  const [tab, setTab] = useState<Tab>('main')
  const [asOf, setAsOf] = useState(DEMO_AS_OF)
  const [changes, setChanges] = useState<EventChange[]>([])
  const [scenario, setScenario] = useState<ScenarioState | null>(null)
  const [isTourOpen, setIsTourOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const basePath = demoOnly ? '/demo' : '/forecast'
  const companyId = routeCompanyId ?? companies[0]?.companyId ?? null
  const company = companies.find((item) => item.companyId === companyId)

  const [cushion, setCushion] = useState(() => (companyId ? preferenceStorage.getCushion(companyId) : 0))
  const [previousCompanyId, setPreviousCompanyId] = useState(companyId)
  if (companyId !== previousCompanyId) {
    setPreviousCompanyId(companyId)
    setChanges([])
    setScenario(null)
    setCushion(companyId ? preferenceStorage.getCushion(companyId) : 0)
  }

  useEffect(() => {
    if (demoOnly) {
      return
    }
    let isActual = true
    companiesApi.listAll()
      .then((list) => {
        if (isActual) {
          setCompanies(list.length > 0 ? list : DEMO_COMPANIES)
        }
      })
      .catch(() => {
        if (isActual) {
          setCompanies(DEMO_COMPANIES)
        }
      })
    return () => {
      isActual = false
    }
  }, [demoOnly])

  useEffect(() => {
    if (preferenceStorage.isTourDone(demoOnly)) {
      return
    }
    const timerId = window.setTimeout(() => setIsTourOpen(true), TOUR_DELAY_MS)
    return () => window.clearTimeout(timerId)
  }, [demoOnly])

  useEffect(() => {
    if (!notice) {
      return
    }
    const timerId = window.setTimeout(() => setNotice(null), NOTICE_DURATION_MS)
    return () => window.clearTimeout(timerId)
  }, [notice])

  const userEvents = useMemo(() => {
    const byStream = new Map<string, ForecastEvent>()
    for (const change of changes) {
      byStream.set(change.event.stream_id ?? `${change.event.date}-${change.event.amount}`, change.event)
    }
    return [...byStream.values()]
  }, [changes])

  const request = useMemo<ForecastRequest | null>(
    () => (companyId ? { asOf, horizonDays: HORIZON_DAYS, threshold: 0, events: userEvents } : null),
    [companyId, asOf, userEvents],
  )
  const scenarioRequest = useMemo<ForecastRequest | null>(
    () => (request && scenario ? { ...request, scenario: scenario.scenario } : null),
    [request, scenario],
  )

  const resolvedStreams = useMemo(() => {
    const streams = new Set<string>()
    for (const event of userEvents) {
      if (event.stream_id) {
        streams.add(event.stream_id)
      }
    }
    return streams
  }, [userEvents])

  const { forecast, isLoading, error, isDemo } = useForecast(companyId, company, request, demoOnly)
  const planFact = usePlanFact(companyId, company, asOf, demoOnly || isDemo, forecast !== null)
  const planFactProblems = planFact.data ? planFact.data.events.filter(isProblem).length : 0
  const scenarioState = useForecast(scenario ? companyId : null, company, scenarioRequest, demoOnly || isDemo)

  const summary = useExplanation({
    companyId,
    kind: 'summary',
    forecast,
    fallback: forecast ? templateSummary(forecast) : '',
    isEnabled: !isDemo && forecast !== null,
  })
  const scenarioExplanation = useExplanation({
    companyId,
    kind: 'scenario',
    forecast: scenarioState.forecast,
    fallback: forecast && scenarioState.forecast && scenario
      ? scenarioTemplate(forecast, scenarioState.forecast, scenario.title)
      : '',
    isEnabled: !isDemo && scenarioState.forecast !== null,
    base: forecast,
  })

  const applyChange = useCallback((change: EventChange) => {
    setChanges((current) => [...current.filter((item) => item.event.stream_id !== change.event.stream_id), change])
    setNotice(`Прогноз пересчитан: ${change.text}`)
  }, [])

  const closeTour = useCallback(() => {
    setIsTourOpen(false)
    preferenceStorage.markTourDone(demoOnly)
  }, [demoOnly])

  const changeTab = useCallback((value: string) => setTab(value as Tab), [])

  const handleAsk = async (question: string) => {
    if (!companyId || !forecast) {
      return null
    }
    try {
      const answer = await forecastApi.explain(companyId, { kind: 'answer', forecast, question })
      return answer.text
    } catch {
      return null
    }
  }

  const handleCushionChange = (event: ChangeEvent<HTMLInputElement>) => {
    const value = Math.max(0, Number(event.target.value) || 0)
    setCushion(value)
    if (companyId) {
      preferenceStorage.setCushion(companyId, value)
    }
  }

  const handleAdviceApply = (event: ForecastEvent, text: string) => {
    applyChange({ event, text: `совет: ${text.split(' — ')[0]}` })
  }

  const openTourFromHelp = () => {
    setTab('main')
    setIsTourOpen(true)
  }

  const gap = forecast?.gaps[0]
  const tourSteps = gap ? TOUR_STEPS : TOUR_STEPS.filter((step) => step.target !== 'advice')
  const lastDay = forecast?.daily[forecast.daily.length - 1]

  return (
    <main className={styles.page}>
      <div className={styles.toolbar}>
        <div>
          <h1 className={styles.title}>Деньги на 30 дней</h1>
          <p className={styles.muted}>
            {company ? `${company.companyName} · ${company.industry}` : 'Выберите компанию'}
            {forecast && ` · прогноз от ${longDate(forecast.as_of)}`}
          </p>
        </div>
        <div className={styles.controls}>
          <label>
            Компания
            <select
              value={companyId ?? ''}
              onChange={(event) => navigate(`${basePath}/${encodeURIComponent(event.target.value)}`)}
            >
              {companies.map((item) => (
                <option key={item.companyId} value={item.companyId}>{item.companyId} · {item.companyName}</option>
              ))}
            </select>
          </label>
          <label>
            Дата прогноза
            <input type="date" value={asOf} onChange={(event) => event.target.value && setAsOf(event.target.value)} />
          </label>
          <label data-tour="cushion">
            Подушка, ₽
            <input type="number" min={0} step={50000} value={cushion || ''} placeholder="0" onChange={handleCushionChange} />
          </label>
          <div className={styles.buttons}>
            <Button variant="secondary" onClick={() => setIsTourOpen(true)}>Как пользоваться</Button>
            <Button variant="ghost" onClick={() => window.print()} disabled={!forecast}>Печать отчёта</Button>
          </div>
        </div>
      </div>

      <nav className={styles.tabs} role="tablist">
        {TABS.map((item) => (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={tab === item.value}
            className={styles.tab}
            data-tour={item.value === 'help' ? 'help-tab' : undefined}
            onClick={() => setTab(item.value)}
          >
            {item.label}
            {item.value === 'calendar' && forecast && <span className={styles.tabCount}>{forecast.events.length}</span>}
            {item.value === 'planfact' && planFactProblems > 0 && (
              <span className={styles.tabCount} data-alert="true">{planFactProblems}</span>
            )}
          </button>
        ))}
      </nav>

      <ChangesBar
        changes={changes}
        onUndo={(index) => setChanges((current) => current.filter((_, itemIndex) => itemIndex !== index))}
        onReset={() => setChanges([])}
      />
      {notice && <div className={styles.toast} role="status">{notice}</div>}
      {error && <p className={styles.error}>{error}</p>}
      {isLoading && !forecast && <div className={styles.skeleton}>Считаем тысячу вариантов будущего…</div>}

      {forecast && lastDay && (
        <div className={styles.content} data-loading={isLoading}>
          {tab === 'main' && (
            <>
              <MissedBanner data={planFact.data} resolvedStreams={resolvedStreams} onOpen={() => setTab('planfact')} />
              <StatusHero
                forecast={forecast}
                cushion={cushion}
                explanation={summary.explanation}
                isExplaining={summary.isLoading}
              />
              <WeekStrip forecast={forecast} />
              <Card
                title="Остаток на счёте по дням"
                tour="chart"
                aside={<span className={styles.muted}>через 30 дней скорее всего {shortMoney(lastDay.p50)}</span>}
              >
                <BalanceChart forecast={forecast} cushion={cushion} />
              </Card>
              <div className={styles.twoColumns}>
                <GapCard gap={gap} forecast={forecast} />
                {gap
                  ? <AdviceList gap={gap} forecast={forecast} onApply={handleAdviceApply} />
                  : <AskBox forecast={forecast} isDemo={isDemo} onAsk={handleAsk} />}
              </div>
              {gap && <AskBox forecast={forecast} isDemo={isDemo} onAsk={handleAsk} />}
              <DataQualityNotes forecast={forecast} isDemo={isDemo} />
            </>
          )}
          {tab === 'calendar' && <PaymentCalendar forecast={forecast} onChange={applyChange} />}
          {tab === 'planfact' && (
            <PlanFact
              data={planFact.data}
              isLoading={planFact.isLoading}
              isDemo={planFact.isDemo}
              error={planFact.error}
              resolvedStreams={resolvedStreams}
              onChange={applyChange}
            />
          )}
          {tab === 'whatif' && (
            <WhatIf
              base={forecast}
              scenarioForecast={scenario ? scenarioState.forecast : null}
              isLoading={scenarioState.isLoading}
              cushion={cushion}
              explanation={scenarioExplanation.explanation}
              title={scenario?.title ?? null}
              onRun={(nextScenario, title) => setScenario({ scenario: nextScenario, title })}
              onClear={() => setScenario(null)}
            />
          )}
          {tab === 'help' && <Help onTour={openTourFromHelp} />}
        </div>
      )}

      <Tour steps={tourSteps} isOpen={isTourOpen && forecast !== null} onClose={closeTour} onTab={changeTab} />
    </main>
  )
}

export default ForecastPage
