import { $api } from '@/api/api';
import type { ApiResponse, ExplainRequest, Explanation, Forecast, ForecastRequest, PlanFact } from '@/api/types';

const FORECAST_TIMEOUT_MS = 15000
const EXPLAIN_TIMEOUT_MS = 12000
const PLAN_FACT_TIMEOUT_MS = 15000
const DEFAULT_LOOKBACK_DAYS = 10

export const forecastApi = {
  get: async (companyId: string, request: ForecastRequest): Promise<Forecast> => {
    const response = await $api.post<ApiResponse<Forecast>>(
      `/companies/${encodeURIComponent(companyId)}/forecast`, request, { timeout: FORECAST_TIMEOUT_MS })
    return response.data.data
  },

  explain: async (companyId: string, request: ExplainRequest): Promise<Explanation> => {
    const response = await $api.post<ApiResponse<Explanation>>(
      `/companies/${encodeURIComponent(companyId)}/explain`, request, { timeout: EXPLAIN_TIMEOUT_MS })
    return response.data.data
  },
}

export const planFactApi = {
  get: async (companyId: string, asOf: string, lookbackDays = DEFAULT_LOOKBACK_DAYS): Promise<PlanFact> => {
    const response = await $api.get<ApiResponse<PlanFact>>(
      `/companies/${encodeURIComponent(companyId)}/plan-fact`,
      { params: { asOf, lookbackDays }, timeout: PLAN_FACT_TIMEOUT_MS },
    )
    return response.data.data
  },
}
