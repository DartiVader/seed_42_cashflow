import { useState, type ChangeEvent, type DragEvent } from 'react';
import CsvMascot from '@/pages/DashboardPage/components/CsvMascot';
import styles from './UploadZone.module.css';

interface UploadZoneProps {
  isCompact: boolean
  isUploading: boolean
  onFileSelect: (file: File) => void
}

const UploadZone = ({ isCompact, isUploading, onFileSelect }: UploadZoneProps) => {
  const [isDragging, setIsDragging] = useState(false)

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) {
      onFileSelect(file)
    }
  }

  const handleDragOver = (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    if (!isUploading) {
      setIsDragging(true)
    }
  }

  const handleDragLeave = () => setIsDragging(false)

  const handleDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    setIsDragging(false)
    const file = event.dataTransfer.files[0]
    if (file && !isUploading) {
      onFileSelect(file)
    }
  }

  const zoneClasses = [styles.zone, isCompact && styles.compact, isDragging && styles.dragging]
    .filter(Boolean)
    .join(' ')

  return (
    <section className={zoneClasses} onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
      <div className={styles.inner}>
        <CsvMascot className={styles.mascot} />
        <label className={isUploading ? `${styles.pick} ${styles.pickDisabled}` : styles.pick}>
          <input className={styles.fileInput} type="file" accept=".csv" onChange={handleChange} disabled={isUploading} />
          {isUploading ? 'Загружаем файл…' : 'Выберите файл CSV'}
        </label>
        <p className={styles.hint}>или перетащите выписку или справочник компаний сюда</p>
      </div>
    </section>
  )
}

export default UploadZone
