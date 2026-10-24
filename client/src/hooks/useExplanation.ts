import { useEffect, useState } from 'react';
import { forecastApi } from '@/api/forecast';
import type { ExplainKind, Explanation, Forecast } from '@/api/types';

interface ExplanationOptions {
  companyId: string | null
  kind: ExplainKind
  forecast: Forecast | null
  fallback: string
  isEnabled: boolean
  base?: Forecast | null
}

interface ExplanationResult {
  requestKey: string | null
  explanation: Explanation | null
}

export const useExplanation = ({ companyId, kind, forecast, fallback, isEnabled, base = null }: ExplanationOptions) => {
  const [result, setResult] = useState<ExplanationResult>({ requestKey: null, explanation: null })
  const requestKey = isEnabled && companyId && forecast ? JSON.stringify([companyId, kind, forecast, base]) : null

  useEffect(() => {
    if (!companyId || !forecast || !requestKey) {
      return
    }
    let isActual = true
    forecastApi.explain(companyId, { kind, forecast, base, question: null })
      .then((explanation) => {
        if (isActual) {
          setResult({ requestKey, explanation: explanation?.text ? explanation : null })
        }
      })
      .catch(() => {
        if (isActual) {
          setResult({ requestKey, explanation: null })
        }
      })
    return () => {
      isActual = false
    }
  }, [companyId, kind, forecast, base, requestKey])

  const isCurrent = requestKey !== null && result.requestKey === requestKey
  const fallbackExplanation: Explanation = { text: fallback, source: 'template', verified: false }

  return {
    explanation: isCurrent && result.explanation ? result.explanation : fallbackExplanation,
    isLoading: requestKey !== null && !isCurrent,
  }
}
