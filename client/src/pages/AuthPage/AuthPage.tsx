import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import Button from '@/components/Button';
import ForecastLine from '@/components/ForecastLine';
import { getErrorMessages } from '@/api/api';
import { useAuth } from '@/context/AuthContext';
import styles from './AuthPage.module.css';

type Mode = 'login' | 'register'

const FACTS = [
  { value: '30 дней', label: 'прогноз остатка на каждый день' },
  { value: '1000', label: 'сценариев для оценки риска' },
  { value: 'P10–P90', label: 'коридор возможного остатка' },
  { value: '1 файл', label: 'банковская выписка в CSV' },
]

const AuthPage = () => {
  const { login, register } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)

  const isLogin = mode === 'login'

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErrors([])
    setIsSubmitting(true)
    try {
      if (isLogin) {
        await login({ email, password })
      } else {
        await register({ email, password })
      }
      navigate('/dashboard', { replace: true })
    } catch (error) {
      setErrors(getErrorMessages(error))
    } finally {
      setIsSubmitting(false)
    }
  }

  const toggleMode = () => {
    setErrors([])
    setMode(isLogin ? 'register' : 'login')
  }

  return (
    <main className={styles.page}>
      <div className={styles.inner}>
        <section className={styles.hero}>
          <h1 className={styles.title}>Узнайте заранее, хватит ли денег</h1>
          <p className={styles.subtitle}>
            Прогноз остатка по выписке, известным платежам и налогам — понятным языком
          </p>
          <ForecastLine />
          <div className={styles.facts}>
            {FACTS.map((fact) => (
              <div key={fact.value} className={styles.fact}>
                <span className={styles.factValue}>{fact.value}</span>
                <span className={styles.factLabel}>{fact.label}</span>
              </div>
            ))}
          </div>
        </section>
        <section className={styles.card}>
          <h2 className={styles.cardTitle}>{isLogin ? 'Добро пожаловать' : 'Создать аккаунт'}</h2>
          <p className={styles.cardSubtitle}>{isLogin ? 'Войдите в Seed 42' : 'Регистрация в Seed 42'}</p>
          <form className={styles.form} onSubmit={handleSubmit}>
            <label>
              Почта
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
            </label>
            <label>
              Пароль
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete={isLogin ? 'current-password' : 'new-password'}
                required
              />
            </label>
            {errors.map((error) => <p key={error} className={styles.error}>{error}</p>)}
            <Button type="submit" className={styles.submit} disabled={isSubmitting}>
              {isLogin ? 'Войти' : 'Зарегистрироваться'}
            </Button>
          </form>
          <Button variant="ghost" className={styles.toggle} onClick={toggleMode}>
            {isLogin ? 'Нет аккаунта? Зарегистрироваться' : 'Уже есть аккаунт? Войти'}
          </Button>
        </section>
      </div>
    </main>
  )
}

export default AuthPage
