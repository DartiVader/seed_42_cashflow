import { memo, useCallback } from 'react';
import { companiesApi } from '@/api/companies';
import type { Company, Page } from '@/api/types';
import CompanyRow from '@/components/CompanyRow';
import CompanyEditRow from '@/components/CompanyEditRow';
import Pagination from '@/components/Pagination';
import { getTableMinWidth, toRem, type TableColumn } from '@/utils/tableColumns';

const COLUMNS: TableColumn[] = [
  { title: 'Код', widthRem: 5 },
  { title: 'Название', widthRem: null },
  { title: 'ИНН', widthRem: 9.5 },
  { title: 'Форма', widthRem: 5.5 },
  { title: 'Вид деятельности', widthRem: null },
]

const MIN_TEXT_COLUMN_REM = 9

const ACTIONS_REM = 5

interface CompaniesTableProps {
  data: Page<Company> | null
  page: number
  isLoading: boolean
  errors: string[]
  isEditing: boolean
  onPageChange: (page: number) => void
  onChanged: () => void
}

const CompaniesTable = ({ data, page, isLoading, errors, isEditing, onPageChange, onChanged }: CompaniesTableProps) => {
  const columnsCount = isEditing ? COLUMNS.length + 1 : COLUMNS.length

  const handleSave = useCallback(async (draft: Company, companyId?: string) => {
    if (companyId) {
      await companiesApi.update(companyId, draft)
    } else {
      await companiesApi.create(draft)
    }
    onChanged()
  }, [onChanged])

  const handleDelete = useCallback(async (companyId: string) => {
    await companiesApi.remove(companyId)
    onChanged()
  }, [onChanged])

  if (errors.length > 0) {
    return <>{errors.map((error) => <p key={error}>{error}</p>)}</>
  }
  if (!data) {
    return <p>Загружаем компании…</p>
  }

  return (
    <>
      <table style={{ minWidth: getTableMinWidth(COLUMNS, MIN_TEXT_COLUMN_REM, isEditing ? ACTIONS_REM : 0) }}>
        <colgroup>
          {COLUMNS.map((column) => (
            <col key={column.title} style={{ width: column.widthRem === null ? undefined : toRem(column.widthRem) }} />
          ))}
          {isEditing && <col style={{ width: toRem(ACTIONS_REM) }} />}
        </colgroup>
        <thead>
          <tr>
            {COLUMNS.map((column) => <th key={column.title}>{column.title}</th>)}
            {isEditing && <th />}
          </tr>
        </thead>
        <tbody>
          {isEditing && <CompanyEditRow columnsCount={columnsCount} onSave={handleSave} />}
          {data.items.map((company) => isEditing
            ? <CompanyEditRow key={company.companyId} company={company} columnsCount={columnsCount}
                              onSave={handleSave} onDelete={handleDelete} />
            : <CompanyRow key={company.companyId} company={company} />)}
        </tbody>
      </table>
      {data.items.length === 0 && !isEditing && (
        <p>Компаний пока нет — загрузите справочник компаний или добавьте компанию в режиме редактирования</p>
      )}
      <Pagination page={page} totalPages={data.totalPages} isDisabled={isLoading} onChange={onPageChange} />
    </>
  )
}

export default memo(CompaniesTable)
