import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import Button from '@/components/Button';
import { getErrorMessages } from '@/api/api';
import { useAuth } from '@/context/AuthContext';

type Mode = 'login' | 'register'

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
    <main>
      <h1>{isLogin ? 'Вход' : 'Регистрация'}</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Email
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
        {errors.map((error) => <p key={error}>{error}</p>)}
        <Button type="submit" disabled={isSubmitting}>
          {isLogin ? 'Войти' : 'Зарегистрироваться'}
        </Button>
      </form>
      <Button onClick={toggleMode}>
        {isLogin ? 'Нет аккаунта? Зарегистрироваться' : 'Уже есть аккаунт? Войти'}
      </Button>
    </main>
  )
}

export default AuthPage
