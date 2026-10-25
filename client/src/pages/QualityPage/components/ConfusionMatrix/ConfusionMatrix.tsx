import Card from '@/components/Card';
import type { QualityMetrics } from '@/api/types';
import { formatShare } from '@/pages/QualityPage/qualityText';
import styles from './ConfusionMatrix.module.css';

interface ConfusionMatrixProps {
  title: string
  confusion: NonNullable<QualityMetrics['confusion']>
}

const ConfusionMatrix = ({ title, confusion }: ConfusionMatrixProps) => {
  const total = confusion.tp + confusion.fp + confusion.fn + confusion.tn || 1
  const cell = (label: string, value: number, tone: 'ok' | 'bad') => (
    <td className={styles.cell} data-tone={tone}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value.toLocaleString('ru-RU')}</span>
      <span className={styles.share}>{formatShare(value / total)}</span>
    </td>
  )

  return (
    <Card title={title} subtitle={`Всего проверок: ${total.toLocaleString('ru-RU')}`}>
      <table className={styles.matrix}>
        <thead>
          <tr>
            <th />
            <th>Нехватка была</th>
            <th>Нехватки не было</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Сервис предупредил</th>
            {cell('Предупредили и было', confusion.tp, 'ok')}
            {cell('Предупредили, а не было', confusion.fp, 'bad')}
          </tr>
          <tr>
            <th scope="row">Сервис промолчал</th>
            {cell('Пропустили', confusion.fn, 'bad')}
            {cell('Верно промолчали', confusion.tn, 'ok')}
          </tr>
        </tbody>
      </table>
    </Card>
  )
}

export default ConfusionMatrix
