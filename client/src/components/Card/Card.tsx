import type { ReactNode } from 'react';
import styles from './Card.module.css';

interface CardProps {
  title?: string
  subtitle?: ReactNode
  aside?: ReactNode
  tour?: string
  className?: string
  children: ReactNode
}

const Card = ({ title, subtitle, aside, tour, className, children }: CardProps) => {
  return (
    <section className={className ? `${styles.card} ${className}` : styles.card} data-tour={tour}>
      {(title || aside) && (
        <div className={styles.head}>
          {title && <h3 className={styles.title}>{title}</h3>}
          {aside}
        </div>
      )}
      {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
      {children}
    </section>
  )
}

export default Card
