import { memo, useState, type ChangeEvent } from 'react';
import Button from '@/components/Button';
import { getErrorMessages } from '@/api/api';
import type { Direction, Operation, OperationPayload } from '@/api/types';
import styles from './OperationEditRow.module.css';

const EMPTY_OPERATION: OperationPayload = {
  companyId: '',
  operationId: '',
  date: '',
  amount: '',
  direction: 'Поступление',
  counterpartyInn: '',
  counterpartyName: '',
  paymentPurpose: '',
}

const toPayload = (operation: Operation): OperationPayload => ({
  companyId: operation.companyId,
  operationId: operation.operationId,
  date: operation.date,
  amount: String(operation.amount),
  direction: operation.direction,
  counterpartyInn: operation.counterpartyInn ?? '',
  counterpartyName: operation.counterpartyName,
  paymentPurpose: operation.paymentPurpose ?? '',
})

interface OperationEditRowProps {
  operation?: Operation
  columnsCount: number
  onSave: (draft: OperationPayload, id?: number) => Promise<void>
  onDelete?: (id: number) => Promise<void>
}

const OperationEditRow = ({ operation, columnsCount, onSave, onDelete }: OperationEditRowProps) => {
  const [draft, setDraft] = useState<OperationPayload>(() => operation ? toPayload(operation) : EMPTY_OPERATION)
  const [errors, setErrors] = useState<string[]>([])
  const [isSaving, setIsSaving] = useState(false)

  const isNew = operation === undefined

  const handleChange = (field: keyof OperationPayload) =>
    (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      setDraft((current) => ({ ...current, [field]: event.target.value }))
    }

  const runAction = async (action: () => Promise<void>) => {
    setErrors([])
    setIsSaving(true)
    try {
      await action()
      if (isNew) {
        setDraft(EMPTY_OPERATION)
      }
    } catch (error) {
      setErrors(getErrorMessages(error))
    } finally {
      setIsSaving(false)
    }
  }

  const handleSave = () => runAction(() => onSave(draft, operation?.id))

  const handleDelete = () => {
    if (operation && onDelete && window.confirm(`Удалить операцию ${operation.operationId}?`)) {
      runAction(() => onDelete(operation.id))
    }
  }

  return (
    <>
      <tr>
        <td><input type="date" value={draft.date} onChange={handleChange('date')} /></td>
        <td><input value={draft.companyId} onChange={handleChange('companyId')} placeholder="C001" /></td>
        <td><input value={draft.operationId} onChange={handleChange('operationId')} placeholder="C001-000001" /></td>
        <td>
          <select value={draft.direction} onChange={handleChange('direction')}>
            {(['Поступление', 'Списание'] as Direction[]).map((direction) => (
              <option key={direction} value={direction}>{direction}</option>
            ))}
          </select>
          <input type="number" step="0.01" min="0.01" value={draft.amount} onChange={handleChange('amount')} />
        </td>
        <td><input value={draft.counterpartyName} onChange={handleChange('counterpartyName')} /></td>
        <td><input value={draft.counterpartyInn} onChange={handleChange('counterpartyInn')} inputMode="numeric" /></td>
        <td><input value={draft.paymentPurpose} onChange={handleChange('paymentPurpose')} /></td>
        <td>
          <div className={styles.actions}>
            <Button size="sm" onClick={handleSave} disabled={isSaving}>{isNew ? 'Добавить' : 'Сохранить'}</Button>
            {!isNew && <Button variant="danger" size="sm" onClick={handleDelete} disabled={isSaving}>Удалить</Button>}
          </div>
        </td>
      </tr>
      {errors.length > 0 && (
        <tr>
          <td colSpan={columnsCount} className={styles.errors}>{errors.map((error) => <p key={error}>{error}</p>)}</td>
        </tr>
      )}
    </>
  )
}

export default memo(OperationEditRow)
