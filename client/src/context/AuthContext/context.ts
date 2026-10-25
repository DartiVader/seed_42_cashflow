import { createContext } from 'react';
import type { Credentials, User } from '@/api/types';

export interface AuthContextValue {
  user: User | null
  isLoading: boolean
  login: (credentials: Credentials) => Promise<void>
  register: (credentials: Credentials) => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
