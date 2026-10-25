import { memo, type ChangeEvent } from 'react';
import Button from '@/components/Button';
import SegmentedControl from '@/components/SegmentedControl';
import type { ListFilters } from '@/api/types';
import styles from './FilterPanel.module.css';

export interface FilterOption {
  value: string
  label: string
}

export interface FilterField {
  key: string
  label: string
  type: 'text' | 'number' | 'select'
  options?: FilterOption[]
  allLabel?: string
}

type SortDirection = 'asc' | 'desc'

const SORT_DIRECTIONS: { value: SortDirection, label: string }[] = [
  { value: 'asc', label: 'По возрастанию' },
  { value: 'desc', label: 'По убыванию' },
]

interface FilterPanelProps {
  fields: FilterField[]
  sortOptions: FilterOption[]
  value: ListFilters
  onChange: (value: ListFilters) => void
  /** поля сеткой в несколько колонок — когда панель стоит над таблицей, а не сбоку */
  isWide?: boolean
}

const FilterPanel = ({ fields, sortOptions, value, onChange, isWide = false }: FilterPanelProps) => {
  const setValue = (key: string, fieldValue: string) => {
    const next = { ...value }
    if (fieldValue === '') {
      delete next[key]
    } else {
      next[key] = fieldValue
    }
    onChange(next)
  }

  const handleChange = (key: string) => (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setValue(key, event.target.value)
  }

  const handleSortFieldChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const next = { ...value }
    if (event.target.value === '') {
      delete next.sortField
      delete next.sortDirection
    } else {
      next.sortField = event.target.value
      next.sortDirection = value.sortDirection ?? 'asc'
    }
    onChange(next)
  }

  const hasFilters = Object.keys(value).length > 0

  return (
    <section className={isWide ? `${styles.card} ${styles.wide}` : styles.card}>
      <div className={styles.header}>
        <h2 className={styles.title}>Фильтры</h2>
        <Button variant="ghost" size="sm" onClick={() => onChange({})} disabled={!hasFilters}>Сбросить</Button>
      </div>
      <div className={styles.fields}>
        {fields.map((field) => (
          <label key={field.key}>
            {field.label}
            {field.type === 'select'
              ? (
                <select value={value[field.key] ?? ''} onChange={handleChange(field.key)}>
                  <option value="">{field.allLabel ?? 'Все'}</option>
                  {(field.options ?? []).map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              )
              : (
                <input
                  type={field.type}
                  min={field.type === 'number' ? 0 : undefined}
                  value={value[field.key] ?? ''}
                  onChange={handleChange(field.key)}
                />
              )}
          </label>
        ))}
      </div>
      <div className={styles.sort}>
        <label>
          Сортировать по
          <select value={value.sortField ?? ''} onChange={handleSortFieldChange}>
            <option value="">По умолчанию</option>
            {sortOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        {value.sortField && (
          <SegmentedControl
            options={SORT_DIRECTIONS}
            value={value.sortDirection === 'desc' ? 'desc' : 'asc'}
            onChange={(direction) => setValue('sortDirection', direction)}
          />
        )}
      </div>
    </section>
  )
}

export default memo(FilterPanel)
