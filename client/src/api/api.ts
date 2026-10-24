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

$api.interceptors.request.use(
  (request) => {
    request.headers['X-Request-ID'] = crypto.randomUUID()
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
