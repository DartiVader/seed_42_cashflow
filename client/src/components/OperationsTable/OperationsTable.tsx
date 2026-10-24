import { memo, useCallback } from 'react';
import { operationsApi } from '@/api/operations';
import type { Operation, OperationPayload, Page } from '@/api/types';
import OperationRow from '@/components/OperationRow';
import OperationEditRow from '@/components/OperationEditRow';
import Pagination from '@/components/Pagination';

const COLUMNS = ['Дата', 'Компания', 'Номер', 'Сумма', 'Контрагент', 'ИНН контрагента', 'Назначение платежа']

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
      <table>
        <thead>
          <tr>
            {COLUMNS.map((column) => <th key={column}>{column}</th>)}
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
