import { $api } from "@/api/api";
import type { ApiResponse, DatasetReport, ImportReport } from "@/api/types";

export const importsApi = {
  upload: async (file: File, onProgress: (percent: number) => void): Promise<ImportReport> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await $api.post<ApiResponse<ImportReport>>('/imports', formData, {
      onUploadProgress: (event) => onProgress(Math.round((event.loaded * 100) / (event.total ?? file.size))),
    })
    return response.data.data
  },

  /** Датасет одним запросом: несколько CSV и/или ZIP; сервер сам загружает справочник компаний первым. */
  uploadDataset: async (files: File[], onProgress: (percent: number) => void): Promise<DatasetReport> => {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    const total = files.reduce((sum, file) => sum + file.size, 0)
    const response = await $api.post<ApiResponse<DatasetReport>>('/imports/dataset', formData, {
      onUploadProgress: (event) => onProgress(Math.round((event.loaded * 100) / (event.total ?? total))),
    })
    return response.data.data
  },
}
