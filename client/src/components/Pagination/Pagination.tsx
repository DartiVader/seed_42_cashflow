import { memo } from 'react';
import Button from '@/components/Button';
import styles from './Pagination.module.css';

type PageItem = number | 'gapStart' | 'gapEnd'

const MAX_VISIBLE_PAGES = 7

const getPageItems = (current: number, total: number): PageItem[] => {
  const items: PageItem[] = []
  if (total <= MAX_VISIBLE_PAGES) {
    for (let pageNumber = 1; pageNumber <= total; pageNumber++) {
      items.push(pageNumber)
    }
    return items
  }

  const windowStart = Math.max(Math.min(current - 1, total - 4), 3)
  const windowEnd = Math.min(Math.max(current + 1, 5), total - 2)

  items.push(1)
  items.push(windowStart > 3 ? 'gapStart' : 2)
  for (let pageNumber = windowStart; pageNumber <= windowEnd; pageNumber++) {
    items.push(pageNumber)
  }
  items.push(windowEnd < total - 2 ? 'gapEnd' : total - 1)
  items.push(total)
  return items
}

interface PaginationProps {
  page: number
  totalPages: number
  isDisabled: boolean
  onChange: (page: number) => void
}

const Pagination = ({ page, totalPages, isDisabled, onChange }: PaginationProps) => {
  if (totalPages <= 1) {
    return null
  }

  const items = getPageItems(page + 1, totalPages)

  return (
    <nav className={styles.pagination}>
      <Button variant="secondary" shape="square" onClick={() => onChange(page - 1)} disabled={isDisabled || page === 0}>
        ‹
      </Button>
      {items.map((item) => typeof item === 'number'
        ? (
          <Button
            key={item}
            variant={item === page + 1 ? 'primary' : 'secondary'}
            shape="square"
            onClick={() => onChange(item - 1)}
            disabled={isDisabled}
          >
            {item}
          </Button>
        )
        : <span key={item} className={styles.gap}>…</span>)}
      <Button
        variant="secondary"
        shape="square"
        onClick={() => onChange(page + 1)}
        disabled={isDisabled || page + 1 >= totalPages}
      >
        ›
      </Button>
    </nav>
  )
}

export default memo(Pagination)
