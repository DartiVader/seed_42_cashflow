import { memo, useState, type ChangeEvent } from 'react';
import Button from '@/components/Button';
import Icon from '@/components/Icon';
import { getErrorMessages } from '@/api/api';
import type { Company, LegalForm } from '@/api/types';
import styles from './CompanyEditRow.module.css';

const EMPTY_COMPANY: Company = {
  companyId: '',
  companyName: '',
  companyInn: '',
  legalForm: 'ООО',
  industry: '',
}

interface CompanyEditRowProps {
  company?: Company
  columnsCount: number
  onSave: (draft: Company, companyId?: string) => Promise<void>
  onDelete?: (companyId: string) => Promise<void>
}

const CompanyEditRow = ({ company, columnsCount, onSave, onDelete }: CompanyEditRowProps) => {
  const [draft, setDraft] = useState<Company>(company ?? EMPTY_COMPANY)
  const [errors, setErrors] = useState<string[]>([])
  const [isSaving, setIsSaving] = useState(false)

  const isNew = company === undefined

  const handleChange = (field: keyof Company) => (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setDraft((current) => ({ ...current, [field]: event.target.value }))
  }

  const runAction = async (action: () => Promise<void>) => {
    setErrors([])
    setIsSaving(true)
    try {
      await action()
      if (isNew) {
        setDraft(EMPTY_COMPANY)
      }
    } catch (error) {
      setErrors(getErrorMessages(error))
    } finally {
      setIsSaving(false)
    }
  }

  const handleSave = () => runAction(() => onSave(draft, company?.companyId))

  const handleDelete = () => {
    if (company && onDelete && window.confirm(`Удалить компанию ${company.companyId} и все её операции?`)) {
      runAction(() => onDelete(company.companyId))
    }
  }

  return (
    <>
      <tr>
        <td>
          {isNew
            ? <input value={draft.companyId} onChange={handleChange('companyId')} placeholder="C151" />
            : draft.companyId}
        </td>
        <td><input value={draft.companyName} onChange={handleChange('companyName')} /></td>
        <td><input value={draft.companyInn} onChange={handleChange('companyInn')} inputMode="numeric" /></td>
        <td>
          <select value={draft.legalForm} onChange={handleChange('legalForm')}>
            {(['ООО', 'ИП'] as LegalForm[]).map((form) => <option key={form} value={form}>{form}</option>)}
          </select>
        </td>
        <td><input value={draft.industry} onChange={handleChange('industry')} /></td>
        <td>
          <div className={styles.actions}>
            <Button
              shape="square"
              size="sm"
              onClick={handleSave}
              disabled={isSaving}
              aria-label={isNew ? 'Добавить' : 'Сохранить'}
              title={isNew ? 'Добавить' : 'Сохранить'}
            >
              <Icon name={isNew ? 'plus' : 'check'} />
            </Button>
            {!isNew && (
              <Button
                variant="dangerGhost"
                shape="square"
                size="sm"
                onClick={handleDelete}
                disabled={isSaving}
                aria-label="Удалить"
                title="Удалить"
              >
                <Icon name="trash" />
              </Button>
            )}
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

export default memo(CompanyEditRow)
