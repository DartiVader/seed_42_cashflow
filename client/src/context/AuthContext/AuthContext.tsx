import { useEffect, useState, type ReactNode } from 'react';
import { authApi } from '@/api/auth';
import { setUnauthorizedHandler } from '@/api/api';
import type { Auth, Credentials, User } from '@/api/types';
import { AuthContext } from './context';

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const resetUser = () => {
    setUser(null)
  }

  const logout = async () => {
    try {
      await authApi.logout()
    } finally {
      resetUser()
    }
  }

  const applyAuth = (auth: Auth) => {
    setUser(auth.user)
  }

  const login = async (credentials: Credentials) => {
    applyAuth(await authApi.login(credentials))
  }

  const register = async (credentials: Credentials) => {
    applyAuth(await authApi.register(credentials))
  }

  useEffect(() => {
    setUnauthorizedHandler(resetUser)

    authApi.me()
      .then(setUser)
      .catch(resetUser)
      .finally(() => setIsLoading(false))
  }, [])

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
