import { memo } from 'react';
import Button from '@/components/Button';

interface PaginationProps {
  page: number
  totalPages: number
  isDisabled: boolean
  onChange: (page: number) => void
}

const Pagination = ({ page, totalPages, isDisabled, onChange }: PaginationProps) => {
  return (
    <div>
      <Button onClick={() => onChange(page - 1)} disabled={isDisabled || page === 0}>Назад</Button>
      <span>Страница {page + 1} из {Math.max(totalPages, 1)}</span>
      <Button onClick={() => onChange(page + 1)} disabled={isDisabled || page + 1 >= totalPages}>Вперёд</Button>
    </div>
  )
}

export default memo(Pagination)
