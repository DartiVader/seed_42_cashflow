import Icon, { type IconName } from '@/components/Icon';
import styles from './DataStats.module.css';

interface DataStatsProps {
  companies: number | null
  operations: number | null
  lastUpload: string | null
}

const count = (value: number | null) => (value === null ? '…' : value.toLocaleString('ru-RU'))

const DataStats = ({ companies, operations, lastUpload }: DataStatsProps) => {
  const tiles: { icon: IconName, label: string, value: string, hint: string }[] = [
    { icon: 'building', label: 'Компаний', value: count(companies), hint: 'из справочника' },
    { icon: 'list', label: 'Операций', value: count(operations), hint: 'по всем выпискам' },
    { icon: 'upload', label: 'Последняя загрузка', value: lastUpload ?? 'ещё не было', hint: 'в этом сеансе' },
  ]

  return (
    <div className={styles.stats}>
      {tiles.map((tile) => (
        <div key={tile.label} className={styles.tile}>
          <span className={styles.icon}><Icon name={tile.icon} /></span>
          <div className={styles.body}>
            <span className={styles.label}>{tile.label}</span>
            <span className={styles.value}>{tile.value}</span>
            <span className={styles.hint}>{tile.hint}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

export default DataStats
