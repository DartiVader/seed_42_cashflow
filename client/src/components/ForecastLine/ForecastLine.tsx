import styles from './ForecastLine.module.css';

const HISTORY = [
  { x: 20, y: 120, r: 7 },
  { x: 80, y: 70, r: 11 },
  { x: 140, y: 110, r: 7 },
  { x: 200, y: 50, r: 11 },
  { x: 250, y: 92, r: 7 },
  { x: 290, y: 78, r: 12 },
]

const ForecastLine = () => {
  const historyPoints = HISTORY.map((point) => `${point.x},${point.y}`).join(' ')

  return (
    <svg className={styles.svg} viewBox="0 0 480 300" aria-hidden="true">
      <circle className={styles.ring} cx="300" cy="150" r="80" />
      <circle className={styles.ring} cx="300" cy="150" r="150" />
      <line className={styles.axis} x1="0" y1="210" x2="480" y2="210" />
      <polyline className={styles.history} points={historyPoints} />
      {HISTORY.map((point) => (
        <circle key={point.x} className={styles.point} cx={point.x} cy={point.y} r={point.r} />
      ))}
      <polyline className={styles.forecast} points="290,78 340,118 400,240 460,110" />
      <circle className={styles.hollow} cx="340" cy="118" r="7" />
      <circle className={styles.hollow} cx="460" cy="110" r="7" />
      <circle className={styles.gap} cx="400" cy="240" r="18" />
      <circle className={styles.gapCore} cx="400" cy="240" r="7" />
    </svg>
  )
}

export default ForecastLine
