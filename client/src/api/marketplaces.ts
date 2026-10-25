import { $api } from '@/api/api';
import type {
  ApiResponse, MarketplaceConnectRequest, MarketplaceConnection, MarketplaceSyncResult,
} from '@/api/types';

/** Отчёт маркетплейса за период может грузиться дольше обычного запроса (Яндекс формирует его на своей стороне) */
const SYNC_TIMEOUT_MS = 120_000

export const marketplacesApi = {
  list: async (): Promise<MarketplaceConnection[]> => {
    const response = await $api.get<ApiResponse<MarketplaceConnection[]>>('/marketplaces')
    return response.data.data
  },

  connect: async (request: MarketplaceConnectRequest): Promise<MarketplaceConnection> => {
    const response = await $api.post<ApiResponse<MarketplaceConnection>>('/marketplaces', request)
    return response.data.data
  },

  disconnect: async (id: number): Promise<void> => {
    await $api.delete<ApiResponse<null>>(`/marketplaces/${id}`)
  },

  sync: async (id: number, dateFrom: string, dateTo: string): Promise<MarketplaceSyncResult> => {
    const response = await $api.post<ApiResponse<MarketplaceSyncResult>>(
      `/marketplaces/${id}/sync`, { dateFrom, dateTo }, { timeout: SYNC_TIMEOUT_MS })
    return response.data.data
  },
}
