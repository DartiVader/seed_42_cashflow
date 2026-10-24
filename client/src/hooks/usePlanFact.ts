import { useEffect, useState } from 'react';
import axios from 'axios';
import { getErrorMessages } from '@/api/api';
import { planFactApi } from '@/api/forecast';
import { mockPlanFact } from '@/api/mocks/planFactMock';
import type { Company, PlanFact } from '@/api/types';

const UNAVAILABLE_STATUSES = [404, 502, 503, 504]

interface PlanFactResult {
  requestKey: string | null
  data: PlanFact | null
  error: string | null
  isDemo: boolean
}

export interface PlanFactState {
  data: PlanFact | null
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

export const usePlanFact = (
  companyId: string | null,
  company: Company | undefined,
  asOf: string,
  demoOnly: boolean,
  isEnabled: boolean,
): PlanFactState => {
  const [result, setResult] = useState<PlanFactResult>({ requestKey: null, data: null, error: null, isDemo: demoOnly })
  const requestKey = companyId && isEnabled ? JSON.stringify([companyId, asOf, demoOnly]) : null

  useEffect(() => {
    if (!companyId || !requestKey) {
      return
    }
    let isActual = true

    const showMock = () => {
      setResult({ requestKey, data: mockPlanFact(companyId, asOf, company), error: null, isDemo: true })
    }

    if (demoOnly) {
      showMock()
    } else {
      planFactApi.get(companyId, asOf)
        .then((data) => {
          if (isActual) {
            setResult({ requestKey, data, error: null, isDemo: false })
          }
        })
        .catch((error) => {
          if (!isActual) {
            return
          }
          if (isServiceUnavailable(error)) {
            showMock()
          } else {
            setResult({ requestKey, data: null, error: getErrorMessages(error).join(' '), isDemo: false })
          }
        })
    }
    return () => {
      isActual = false
    }
  }, [companyId, company, asOf, demoOnly, requestKey])

  const isCurrent = requestKey !== null && result.requestKey === requestKey
  return {
    data: isCurrent ? result.data : null,
    isLoading: requestKey !== null && !isCurrent,
    error: isCurrent ? result.error : null,
    isDemo: result.isDemo,
  }
}
