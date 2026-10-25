import { useCallback, useEffect, useLayoutEffect, useState } from 'react';
import Button from '@/components/Button';
import styles from './Tour.module.css';

export interface TourStep {
  target: string
  title: string
  text: string
  tab?: string
}

interface TourProps {
  steps: TourStep[]
  isOpen: boolean
  onClose: () => void
  onTab?: (tab: string) => void
}

interface Rect {
  top: number
  left: number
  width: number
  height: number
}

const PAD = 8
const TARGET_WAIT_STEP_MS = 60
const TARGET_WAIT_ATTEMPTS = 25

const Tour = ({ steps, isOpen, onClose, onTab }: TourProps) => {
  const [index, setIndex] = useState(0)
  const [rect, setRect] = useState<Rect | null>(null)
  const [wasOpen, setWasOpen] = useState(isOpen)
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen)
    if (isOpen) {
      setIndex(0)
    }
  }
  const step = steps[index]

  const measure = useCallback(() => {
    if (!step) return
    const el = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`)
    if (!el) {
      setRect(null)
      return
    }
    const r = el.getBoundingClientRect()
    setRect({ top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 })
  }, [step])

  useLayoutEffect(() => {
    if (!isOpen || !step) return
    if (step.tab && onTab) onTab(step.tab)
    // Вкладка меняется с анимацией: ждём, пока цель шага появится, и только потом прокручиваем к ней
    let attempts = 0
    let timer = 0
    const focusTarget = () => {
      const el = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`)
      if (!el && attempts < TARGET_WAIT_ATTEMPTS) {
        attempts += 1
        timer = window.setTimeout(focusTarget, TARGET_WAIT_STEP_MS)
        return
      }
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      timer = window.setTimeout(measure, 350)
    }
    timer = window.setTimeout(focusTarget, 80)
    return () => window.clearTimeout(timer)
  }, [isOpen, step, onTab, measure])

  useEffect(() => {
    if (!isOpen) return
    const update = () => measure()
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowRight') setIndex((i) => Math.min(i + 1, steps.length - 1))
      if (e.key === 'ArrowLeft') setIndex((i) => Math.max(i - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('keydown', onKey)
    }
  }, [isOpen, measure, onClose, steps.length])

  if (!isOpen || !step) return null

  const viewportH = window.innerHeight
  const viewportW = window.innerWidth
  const below = rect ? rect.top + rect.height + 220 < viewportH : true
  const cardTop = rect ? (below ? rect.top + rect.height + 12 : Math.max(12, rect.top - 12 - 200)) : viewportH / 2 - 100
  const cardLeft = rect ? Math.min(Math.max(12, rect.left), viewportW - 372) : viewportW / 2 - 180
  const isLast = index === steps.length - 1

  return (
    <div className={styles.root} role="dialog" aria-modal="true" aria-label="Обучение">
      {rect
        ? <div className={styles.spotlight} style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }} />
        : <div className={styles.backdrop} />}
      <div className={styles.card} style={{ top: cardTop, left: cardLeft }}>
        <div className={styles.progress}>Шаг {index + 1} из {steps.length}</div>
        <h3 className={styles.title}>{step.title}</h3>
        <p className={styles.text}>{step.text}</p>
        <div className={styles.dots}>
          {steps.map((s, i) => <i key={s.target + i} data-active={i === index} />)}
        </div>
        <div className={styles.actions}>
          <Button size="sm" variant="ghost" onClick={onClose}>Пропустить</Button>
          <div className={styles.nav}>
            {index > 0 && <Button size="sm" variant="secondary" onClick={() => setIndex(index - 1)}>Назад</Button>}
            <Button size="sm" onClick={() => (isLast ? onClose() : setIndex(index + 1))}>{isLast ? 'Понятно' : 'Дальше'}</Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Tour
