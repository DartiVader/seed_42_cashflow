import { useEffect, useState } from 'react';
import axios from 'axios';
import { getErrorMessages } from '@/api/api';
import { forecastApi } from '@/api/forecast';
import { mockForecast } from '@/api/mocks/forecastMock';
import type { Company, Forecast, ForecastRequest } from '@/api/types';

const MOCK_DELAY_MS = 250
const UNAVAILABLE_STATUSES = [404, 502, 503, 504]

interface ForecastResult {
  requestKey: string | null
  forecast: Forecast | null
  error: string | null
  isDemo: boolean
}

export interface ForecastState {
  forecast: Forecast | null
  isLoading: boolean
  error: string | null
  isDemo: boolean
}

const isServiceUnavailable = (error: unknown) => {
  if (!axios.isAxiosError(error)) {
    return true
  }
  const status = error.response?.status
  return status === undefined || UNAVAILABLE_STATUSES.includes(status)
}

export const useForecast = (
  companyId: string | null,
  company: Company | undefined,
  request: ForecastRequest | null,
  demoOnly: boolean,
): ForecastState => {
  const [result, setResult] = useState<ForecastResult>({ requestKey: null, forecast: null, error: null, isDemo: demoOnly })
  const requestKey = companyId && request ? JSON.stringify([companyId, request, demoOnly]) : null

  useEffect(() => {
    if (!companyId || !request || !requestKey) {
      return
    }
    let isActual = true
    let timerId: number | undefined

    const showMock = () => {
      timerId = window.setTimeout(() => {
        if (isActual) {
          setResult({ requestKey, forecast: mockForecast(companyId, request, company), error: null, isDemo: true })
        }
      }, MOCK_DELAY_MS)
    }

    if (demoOnly) {
      showMock()
    } else {
      forecastApi.get(companyId, request)
        .then((forecast) => {
          if (isActual) {
            setResult({ requestKey, forecast, error: null, isDemo: false })
          }
        })
        .catch((error) => {
          if (!isActual) {
            return
          }
          if (isServiceUnavailable(error)) {
            showMock()
          } else {
            setResult({ requestKey, forecast: null, error: getErrorMessages(error).join(' '), isDemo: false })
          }
        })
    }
    return () => {
      isActual = false
      window.clearTimeout(timerId)
    }
  }, [companyId, company, request, demoOnly, requestKey])

  return {
    forecast: requestKey ? result.forecast : null,
    isLoading: requestKey !== null && result.requestKey !== requestKey,
    error: result.requestKey === requestKey ? result.error : null,
    isDemo: result.isDemo,
  }
}
