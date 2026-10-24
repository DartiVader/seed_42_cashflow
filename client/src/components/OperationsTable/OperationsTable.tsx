import { memo, useCallback } from 'react';
import { operationsApi } from '@/api/operations';
import type { Operation, OperationPayload, Page } from '@/api/types';
import OperationRow from '@/components/OperationRow';
import OperationEditRow from '@/components/OperationEditRow';
import Pagination from '@/components/Pagination';
import { getTableMinWidth, toRem, type TableColumn } from '@/utils/tableColumns';

const COLUMNS: TableColumn[] = [
  { title: 'Дата', widthRem: 8.5 },
  { title: 'Компания', widthRem: 6.75 },
  { title: 'Номер', widthRem: 8 },
  { title: 'Сумма', widthRem: 9 },
  { title: 'Контрагент', widthRem: null },
  { title: 'ИНН контрагента', widthRem: 8 },
  { title: 'Назначение платежа', widthRem: null },
]

const MIN_TEXT_COLUMN_REM = 5

const ACTIONS_REM = 7

interface OperationsTableProps {
  data: Page<Operation> | null
  page: number
  isLoading: boolean
  errors: string[]
  isEditing: boolean
  onPageChange: (page: number) => void
  onChanged: () => void
}

const OperationsTable = ({ data, page, isLoading, errors, isEditing, onPageChange, onChanged }: OperationsTableProps) => {
  const columnsCount = isEditing ? COLUMNS.length + 1 : COLUMNS.length

  const handleSave = useCallback(async (draft: OperationPayload, id?: number) => {
    if (id !== undefined) {
      await operationsApi.update(id, draft)
    } else {
      await operationsApi.create(draft)
    }
    onChanged()
  }, [onChanged])

  const handleDelete = useCallback(async (id: number) => {
    await operationsApi.remove(id)
    onChanged()
  }, [onChanged])

  if (errors.length > 0) {
    return <>{errors.map((error) => <p key={error}>{error}</p>)}</>
  }
  if (!data) {
    return <p>Загружаем операции…</p>
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
          {isEditing && <OperationEditRow columnsCount={columnsCount} onSave={handleSave} />}
          {data.items.map((operation) => isEditing
            ? <OperationEditRow key={operation.id} operation={operation} columnsCount={columnsCount}
                                onSave={handleSave} onDelete={handleDelete} />
            : <OperationRow key={operation.id} operation={operation} />)}
        </tbody>
      </table>
      {data.items.length === 0 && !isEditing && <p>Операций пока нет — загрузите выписку</p>}
      <p>Всего операций: {data.totalElements}</p>
      <Pagination page={page} totalPages={data.totalPages} isDisabled={isLoading} onChange={onPageChange} />
    </>
  )
}

export default memo(OperationsTable)
