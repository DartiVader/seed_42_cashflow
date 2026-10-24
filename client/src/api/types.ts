export interface ApiError {
  field: string | null
  message: string
}

export interface ApiResponse<T> {
  localDateTime: string
  methodName: string
  success: boolean
  data: T
  listErrors: ApiError[]
}

export interface User {
  id: number
  email: string
  isAdmin: boolean
}

export interface Auth {
  expiresAt: string
  user: User
}

export interface Credentials {
  email: string
  password: string
}
