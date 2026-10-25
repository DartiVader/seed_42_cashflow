import styles from './CsvMascot.module.css';

const CsvMascot = ({ className }: { className?: string }) => {
  return (
    <svg className={className} viewBox="0 0 120 150" aria-hidden="true">
      <path className={styles.leafFilled} d="M60 40 C52 24 38 20 26 22 C28 36 42 44 60 40 Z" />
      <path className={styles.leafOutline} d="M60 36 C62 20 76 10 94 10 C92 26 80 34 60 36 Z" />
      <line className={styles.stem} x1="60" y1="52" x2="60" y2="30" />
      <path
        className={styles.file}
        d="M32 52 H78 L96 70 V136 Q96 144 88 144 H32 Q24 144 24 136 V60 Q24 52 32 52 Z"
      />
      <path className={styles.fold} d="M78 52 V64 Q78 70 84 70 H96 Z" />
      <circle className={styles.lens} cx="46" cy="86" r="10" />
      <circle className={styles.lens} cx="74" cy="86" r="10" />
      <line className={styles.frame} x1="56" y1="86" x2="64" y2="86" />
      <line className={styles.frame} x1="36" y1="84" x2="26" y2="80" />
      <line className={styles.frame} x1="84" y1="84" x2="94" y2="80" />
      <circle className={styles.eye} cx="47" cy="87" r="3" />
      <circle className={styles.eye} cx="75" cy="87" r="3" />
      <path className={styles.smile} d="M48 104 Q60 114 72 104" />
      <rect className={styles.badge} x="40" y="120" width="40" height="16" rx="4" />
      <text className={styles.badgeText} x="60" y="132" textAnchor="middle">CSV</text>
    </svg>
  )
}

export default CsvMascot
