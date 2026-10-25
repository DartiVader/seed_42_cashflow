import axios from "axios";
import type { ApiResponse } from "@/api/types";

export const $api = axios.create({
  baseURL: '/api',
})

let onUnauthorized: () => void = () => {}

export const setUnauthorizedHandler = (handler: () => void) => {
  onUnauthorized = handler
}

export const getErrorMessages = (error: unknown): string[] => {
  if (axios.isAxiosError<ApiResponse<unknown>>(error) && error.response?.data?.listErrors?.length) {
    return error.response.data.listErrors.map((apiError) => apiError.message)
  }
  return ['Не удалось связаться с сервером, попробуйте ещё раз']
}

// crypto.randomUUID есть только в защищённом контексте (HTTPS, localhost); по http://IP — UUID v4 из getRandomValues
const requestId = (): string => {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

$api.interceptors.request.use(
  (request) => {
    request.headers['X-Request-ID'] = requestId()
    console.log(`Запрос: ${request.method?.toUpperCase()} ${request.url} trace_id=${request.headers['X-Request-ID']}`);
    return request
  }, (error) => {
    console.error('Ошибка при подготовке запроса:', error)
    return Promise.reject(error)
  }
)

$api.interceptors.response.use(
  (response) => {
    console.log(`Ответ: ${response.status} ${response.config.url}`)
    return response
  },
  (error) => {
    console.error(`Ошибка ответа trace_id=${error.config?.headers?.['X-Request-ID']}:`, error.response?.data ?? error.message)
    if (error.response?.status === 401 && !error.config?.url?.startsWith('/auth/')) {
      onUnauthorized()
    }
    return Promise.reject(error)
  }
)
