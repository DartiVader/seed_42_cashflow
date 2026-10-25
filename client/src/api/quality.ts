import { $api } from '@/api/api';
import type { ApiResponse, QualityReport, QualitySource } from '@/api/types';

export const qualityApi = {
  get: async (source: QualitySource = 'admin'): Promise<QualityReport> => {
    const response = await $api.get<ApiResponse<QualityReport>>('/quality', { params: { source } })
    return response.data.data
  },

  run: async (): Promise<string> => {
    const response = await $api.post<ApiResponse<{ jobId: string }>>('/quality/run')
    return response.data.data.jobId
  },

  fileUrl: (name: string, source: QualitySource = 'admin') =>
    `/api/quality/files/${encodeURIComponent(name)}?source=${source}`,
}
