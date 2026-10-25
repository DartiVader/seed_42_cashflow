import type { ReactNode } from 'react';
import styles from './Chip.module.css';

interface ChipProps {
  onClick: () => void
  children: ReactNode
}

const Chip = ({ onClick, children }: ChipProps) => {
  return (
    <button type="button" className={styles.chip} onClick={onClick}>
      {children}
    </button>
  )
}

export default Chip
