import { $api } from "@/api/api";
import type { ApiResponse, ListFilters, Operation, OperationPayload, Page } from "@/api/types";

export const operationsApi = {
  list: async (page: number, size: number, filters: ListFilters): Promise<Page<Operation>> => {
    const response = await $api.get<ApiResponse<Page<Operation>>>('/operations', { params: { ...filters, page, size } })
    return response.data.data
  },

  create: async (operation: OperationPayload): Promise<Operation> => {
    const response = await $api.post<ApiResponse<Operation>>('/operations', operation)
    return response.data.data
  },

  update: async (id: number, operation: OperationPayload): Promise<Operation> => {
    const response = await $api.put<ApiResponse<Operation>>(`/operations/${id}`, operation)
    return response.data.data
  },

  remove: async (id: number): Promise<void> => {
    await $api.delete<ApiResponse<null>>(`/operations/${id}`)
  },
}
