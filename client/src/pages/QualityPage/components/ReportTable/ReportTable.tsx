import { COLUMN_NAMES, MODEL_NAMES, formatScore } from '@/pages/QualityPage/qualityText';
import styles from './ReportTable.module.css';

interface ReportTableProps {
  columns: string[]
  rows: (string | number | null)[][]
}

const show = (column: string, value: string | number | null) => {
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  if (typeof value === 'number') {
    return Math.abs(value) >= 1000 ? Math.round(value).toLocaleString('ru-RU') : formatScore(value)
  }
  return column === 'model' ? MODEL_NAMES[value] ?? value : value
}

const ReportTable = ({ columns, rows }: ReportTableProps) => (
  <div className={styles.scroll}>
    <table className={styles.table}>
      <thead>
        <tr>{columns.map((column) => <th key={column}>{COLUMN_NAMES[column] ?? column}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {row.map((value, cellIndex) => (
              <td key={cellIndex} data-text={typeof value === 'string' || undefined}>
                {show(columns[cellIndex], value)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
)

export default ReportTable
