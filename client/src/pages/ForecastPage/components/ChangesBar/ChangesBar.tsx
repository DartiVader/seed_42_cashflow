import Button from '@/components/Button';
import Icon from '@/components/Icon';
import styles from './ChangesBar.module.css';

interface ChangesBarProps {
  changes: { text: string }[]
  onUndo: (index: number) => void
  onReset: () => void
}

const ChangesBar = ({ changes, onUndo, onReset }: ChangesBarProps) => {
  if (changes.length === 0) {
    return null
  }

  return (
    <div className={styles.bar}>
      <span className={styles.title}>Учтены ваши изменения:</span>
      {changes.map((change, index) => (
        <span key={`${change.text}-${index}`} className={styles.chip}>
          {change.text}
          <button type="button" className={styles.undo} onClick={() => onUndo(index)} aria-label="Отменить изменение">
            <Icon name="close" />
          </button>
        </span>
      ))}
      <Button size="sm" variant="ghost" onClick={onReset}>Сбросить всё</Button>
    </div>
  )
}

export default ChangesBar
