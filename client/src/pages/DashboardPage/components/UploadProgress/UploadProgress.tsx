import styles from './UploadProgress.module.css';

const UploadProgress = ({ progress }: { progress: number | null }) => {
  if (progress === null) {
    return <div className={styles.track} />
  }

  return (
    <div className={styles.track} role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
      <div
        className={progress < 100 ? styles.bar : `${styles.bar} ${styles.processing}`}
        style={{ width: `${progress}%` }}
      />
    </div>
  )
}

export default UploadProgress
