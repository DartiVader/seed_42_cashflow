import type { UploadSummary } from '@/pages/DashboardPage/useDatasetUpload';

const reportKey = (userId: number) => `importSummary:${userId}`

export const reportStorage = {
  get: (userId: number): UploadSummary | null => {
    try {
      const raw = sessionStorage.getItem(reportKey(userId))
      return raw ? JSON.parse(raw) as UploadSummary : null
    } catch {
      return null
    }
  },

  set: (userId: number, summary: UploadSummary) => {
    try {
      sessionStorage.setItem(reportKey(userId), JSON.stringify(summary))
    } catch {
      return
    }
  },
}
