import type { ImportReport } from '@/api/types';

const reportKey = (userId: number) => `importReport:${userId}`

export const reportStorage = {
  get: (userId: number): ImportReport | null => {
    try {
      const raw = sessionStorage.getItem(reportKey(userId))
      return raw ? JSON.parse(raw) as ImportReport : null
    } catch {
      return null
    }
  },

  set: (userId: number, report: ImportReport) => {
    try {
      sessionStorage.setItem(reportKey(userId), JSON.stringify(report))
    } catch {
      return
    }
  },
}
