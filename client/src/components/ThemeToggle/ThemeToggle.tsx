import { useCallback, useEffect, useRef, useState } from 'react';
import Icon from '@/components/Icon';
import { preferenceStorage, type Theme } from '@/utils/preferenceStorage';
import styles from './ThemeToggle.module.css';

const HIDE_DELAY_MS = 2500
const TRANSITION_MS = 450
const DARK_QUERY = '(prefers-color-scheme: dark)'

const readTheme = (): Theme => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')

const applyTheme = (theme: Theme) => {
  const root = document.documentElement
  root.classList.add('theme-transition')
  root.dataset.theme = theme
  window.setTimeout(() => root.classList.remove('theme-transition'), TRANSITION_MS)
}

const ThemeToggle = () => {
  const [theme, setTheme] = useState<Theme>(readTheme)
  const [isVisible, setIsVisible] = useState(true)
  const hideTimerRef = useRef<number | undefined>(undefined)

  const scheduleHide = useCallback(() => {
    window.clearTimeout(hideTimerRef.current)
    hideTimerRef.current = window.setTimeout(() => setIsVisible(false), HIDE_DELAY_MS)
  }, [])

  const show = () => {
    window.clearTimeout(hideTimerRef.current)
    setIsVisible(true)
  }

  useEffect(() => {
    scheduleHide()
    return () => window.clearTimeout(hideTimerRef.current)
  }, [scheduleHide])

  useEffect(() => {
    const media = window.matchMedia(DARK_QUERY)
    const handleSystemChange = (event: MediaQueryListEvent) => {
      if (preferenceStorage.getTheme() !== null) {
        return
      }
      const systemTheme: Theme = event.matches ? 'dark' : 'light'
      applyTheme(systemTheme)
      setTheme(systemTheme)
    }
    media.addEventListener('change', handleSystemChange)
    return () => media.removeEventListener('change', handleSystemChange)
  }, [])

  const handleToggle = () => {
    const nextTheme: Theme = theme === 'dark' ? 'light' : 'dark'
    applyTheme(nextTheme)
    preferenceStorage.setTheme(nextTheme)
    setTheme(nextTheme)
  }

  const label = theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'

  return (
    <div className={styles.hotspot} onPointerEnter={show} onPointerLeave={scheduleHide}>
      <button
        type="button"
        className={styles.toggle}
        data-visible={isVisible}
        onClick={handleToggle}
        onFocus={show}
        onBlur={scheduleHide}
        aria-label={label}
        title={label}
      >
        <span className={styles.icon} key={theme}>
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
        </span>
      </button>
    </div>
  )
}

export default ThemeToggle
