import CsvMascot from '@/components/CsvMascot';
import styles from './MascotLoader.module.css';

const MascotLoader = ({ text }: { text: string }) => {
  return (
    <div className={styles.loader} role="status">
      <CsvMascot className={styles.mascot} />
      <p className={styles.text}>{text}</p>
      <span className={styles.dots} aria-hidden="true"><i /><i /><i /></span>
    </div>
  )
}

export default MascotLoader
