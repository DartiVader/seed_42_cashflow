import { $api } from "@/api/api";
import type { ApiResponse, ImportReport } from "@/api/types";

export const importsApi = {
  upload: async (file: File, onProgress: (percent: number) => void): Promise<ImportReport> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await $api.post<ApiResponse<ImportReport>>('/imports', formData, {
      onUploadProgress: (event) => onProgress(Math.round((event.loaded * 100) / (event.total ?? file.size))),
    })
    return response.data.data
  },
}
