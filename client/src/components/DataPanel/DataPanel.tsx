import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import Button from '@/components/Button';
import SegmentedControl from '@/components/SegmentedControl';
import CompaniesTable from '@/components/CompaniesTable';
import OperationsTable from '@/components/OperationsTable';
import FilterPanel, { type FilterField, type FilterOption } from '@/components/FilterPanel';
import DateRangeCalendar from '@/components/DateRangeCalendar';
import { companiesApi } from '@/api/companies';
import { operationsApi } from '@/api/operations';
import type { Company, ListFilters } from '@/api/types';
import { useDebounce } from '@/hooks/useDebounce';
import { usePagedList } from '@/hooks/usePagedList';
import styles from './DataPanel.module.css';

export type DataTab = 'companies' | 'operations'

const TABS: { value: DataTab, label: string }[] = [
  { value: 'companies', label: 'Компании' },
  { value: 'operations', label: 'Операции' },
]

const FILTER_DELAY_MS = 300

const LEGAL_FORM_OPTIONS: FilterOption[] = [
  { value: 'ООО', label: 'ООО' },
  { value: 'ИП', label: 'ИП' },
]

const DIRECTION_OPTIONS: FilterOption[] = [
  { value: 'Поступление', label: 'Поступление' },
  { value: 'Списание', label: 'Списание' },
]

const COMPANY_SORT_OPTIONS: FilterOption[] = [
  { value: 'companyId', label: 'Код' },
  { value: 'companyName', label: 'Название' },
  { value: 'companyInn', label: 'ИНН' },
  { value: 'legalForm', label: 'Форма' },
  { value: 'industry', label: 'Вид деятельности' },
]

const OPERATION_SORT_OPTIONS: FilterOption[] = [
  { value: 'date', label: 'Дата' },
  { value: 'companyId', label: 'Компания' },
  { value: 'operationId', label: 'Номер' },
  { value: 'amount', label: 'Сумма' },
  { value: 'counterpartyName', label: 'Контрагент' },
  { value: 'counterpartyInn', label: 'ИНН контрагента' },
  { value: 'paymentPurpose', label: 'Назначение платежа' },
]

const getIndustryOptions = (companies: Company[]): FilterOption[] => {
  const industries = new Set<string>()
  for (const company of companies) {
    industries.add(company.industry)
  }
  const options: FilterOption[] = []
  for (const industry of [...industries].sort()) {
    options.push({ value: industry, label: industry })
  }
  return options
}

const getCompanyOptions = (companies: Company[]): FilterOption[] => {
  const options: FilterOption[] = []
  for (const company of companies) {
    options.push({ value: company.companyId, label: `${company.companyId} · ${company.companyName}` })
  }
  return options
}

interface DataPanelProps {
  refreshKey: number
  /** вкладка задаётся снаружи (боковое меню страницы) — тогда свой переключатель не показываем */
  tab?: DataTab
  /** фильтры над таблицей, а не в колонке справа — таблице достаётся вся ширина */
  isStacked?: boolean
}

const DataPanel = ({ refreshKey, tab: controlledTab, isStacked = false }: DataPanelProps) => {
  const [ownTab, setOwnTab] = useState<DataTab>('companies')
  const tab = controlledTab ?? ownTab
  const [isEditing, setIsEditing] = useState(false)
  const [companyFilters, setCompanyFilters] = useState<ListFilters>({})
  const [operationFilters, setOperationFilters] = useState<ListFilters>({})
  const [allCompanies, setAllCompanies] = useState<Company[]>([])

  const debouncedCompanyFilters = useDebounce(companyFilters, FILTER_DELAY_MS)
  const debouncedOperationFilters = useDebounce(operationFilters, FILTER_DELAY_MS)

  const loadCompanies = useCallback(
    (page: number, size: number) => companiesApi.list(page, size, debouncedCompanyFilters),
    [debouncedCompanyFilters],
  )
  const loadOperations = useCallback(
    (page: number, size: number) => operationsApi.list(page, size, debouncedOperationFilters),
    [debouncedOperationFilters],
  )

  const companies = usePagedList(loadCompanies, true, refreshKey)
  const operations = usePagedList(loadOperations, companies.isLoaded, refreshKey)

  const reloadCompanies = companies.reload
  const reloadOperations = operations.reload

  useEffect(() => {
    let isActual = true
    companiesApi.listAll()
      .then((result) => {
        if (isActual) {
          setAllCompanies(result)
        }
      })
      .catch(() => {
        if (isActual) {
          setAllCompanies([])
        }
      })
    return () => {
      isActual = false
    }
  }, [companies.data])

  const handleCompaniesChanged = useCallback(() => {
    reloadCompanies()
    reloadOperations()
  }, [reloadCompanies, reloadOperations])

  const handleDateRangeChange = useCallback((from: string | null, to: string | null) => {
    setOperationFilters((current) => {
      const next = { ...current }
      delete next.dateFrom
      delete next.dateTo
      if (from && to) {
        next.dateFrom = from
        next.dateTo = to
      }
      return next
    })
  }, [])

  const companyFields = useMemo<FilterField[]>(() => [
    { key: 'companyId', label: 'Код', type: 'text' },
    { key: 'companyName', label: 'Название', type: 'text' },
    { key: 'companyInn', label: 'ИНН', type: 'text' },
    { key: 'legalForm', label: 'Форма', type: 'select', options: LEGAL_FORM_OPTIONS },
    { key: 'industry', label: 'Вид деятельности', type: 'select', options: getIndustryOptions(allCompanies) },
  ], [allCompanies])

  const operationFields = useMemo<FilterField[]>(() => [
    {
      key: 'companyId',
      label: 'Компания',
      type: 'select',
      options: getCompanyOptions(allCompanies),
      allLabel: 'Все компании',
    },
    { key: 'operationId', label: 'Номер', type: 'text' },
    { key: 'direction', label: 'Направление', type: 'select', options: DIRECTION_OPTIONS },
    { key: 'amountFrom', label: 'Сумма от, ₽', type: 'number' },
    { key: 'amountTo', label: 'Сумма до, ₽', type: 'number' },
    { key: 'counterpartyName', label: 'Контрагент', type: 'text' },
    { key: 'counterpartyInn', label: 'ИНН контрагента', type: 'text' },
    { key: 'paymentPurpose', label: 'Назначение платежа', type: 'text' },
  ], [allCompanies])

  const isCompaniesTab = tab === 'companies'

  return (
    <div className={isStacked ? `${styles.layout} ${styles.stacked}` : styles.layout}>
      <section className={styles.panel}>
        <div className={styles.toolbar}>
          {controlledTab
            ? <h2 className={styles.title}>{TABS.find((item) => item.value === tab)?.label}</h2>
            : <SegmentedControl options={TABS} value={tab} onChange={setOwnTab} />}
          <Button
            variant={isEditing ? 'primary' : 'secondary'}
            className={styles.editButton}
            onClick={() => setIsEditing((current) => !current)}
          >
            {isEditing ? 'Готово' : 'Редактировать'}
          </Button>
        </div>
        <div className={styles.window}>
          {isCompaniesTab
            ? (
              <CompaniesTable
                data={companies.data}
                page={companies.page}
                isLoading={companies.isLoading}
                errors={companies.errors}
                isEditing={isEditing}
                onPageChange={companies.setPage}
                onChanged={handleCompaniesChanged}
              />
            )
            : (
              <OperationsTable
                data={operations.data}
                page={operations.page}
                isLoading={operations.isLoading}
                errors={operations.errors}
                isEditing={isEditing}
                onPageChange={operations.setPage}
                onChanged={reloadOperations}
              />
            )}
        </div>
      </section>
      <aside className={styles.aside}>
        {isCompaniesTab
          ? (
            <FilterPanel
              key="companies"
              fields={companyFields}
              sortOptions={COMPANY_SORT_OPTIONS}
              value={companyFilters}
              onChange={setCompanyFilters}
              isWide={isStacked}
            />
          )
          : (
            <>
              <FilterPanel
                key="operations"
                fields={operationFields}
                sortOptions={OPERATION_SORT_OPTIONS}
                value={operationFilters}
                onChange={setOperationFilters}
                isWide={isStacked}
              />
              <DateRangeCalendar
                from={operationFilters.dateFrom ?? null}
                to={operationFilters.dateTo ?? null}
                onChange={handleDateRangeChange}
              />
            </>
          )}
      </aside>
    </div>
  )
}

export default memo(DataPanel)
