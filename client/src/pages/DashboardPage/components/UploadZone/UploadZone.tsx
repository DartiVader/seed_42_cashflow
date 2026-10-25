import { useState, type ChangeEvent, type DragEvent } from 'react';
import CsvMascot from '@/components/CsvMascot';
import styles from './UploadZone.module.css';

interface UploadZoneProps {
  isCompact: boolean
  isUploading: boolean
  onFilesSelect: (files: File[]) => void
}

const UploadZone = ({ isCompact, isUploading, onFilesSelect }: UploadZoneProps) => {
  const [isDragging, setIsDragging] = useState(false)

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const files = [...(event.target.files ?? [])]
    event.target.value = ''
    if (files.length > 0) {
      onFilesSelect(files)
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
    const files = [...event.dataTransfer.files]
    if (files.length > 0 && !isUploading) {
      onFilesSelect(files)
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
          <input
            className={styles.fileInput}
            type="file"
            accept=".csv,.zip"
            multiple
            onChange={handleChange}
            disabled={isUploading}
          />
          {isUploading ? 'Загружаем файлы…' : 'Выберите файлы CSV или архив ZIP'}
        </label>
        <p className={styles.hint}>
          или перетащите сюда справочник компаний и выписки — можно сразу несколько файлов или один архив
        </p>
      </div>
    </section>
  )
}

export default UploadZone
