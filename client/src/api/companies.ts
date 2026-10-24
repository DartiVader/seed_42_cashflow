import { $api } from "@/api/api";
import type { ApiResponse, Company, Page } from "@/api/types";

export const companiesApi = {
  list: async (page: number, size: number): Promise<Page<Company>> => {
    const response = await $api.get<ApiResponse<Page<Company>>>('/companies', { params: { page, size } })
    return response.data.data
  },

  create: async (company: Company): Promise<Company> => {
    const response = await $api.post<ApiResponse<Company>>('/companies', company)
    return response.data.data
  },

  update: async (companyId: string, company: Company): Promise<Company> => {
    const response = await $api.put<ApiResponse<Company>>(`/companies/${encodeURIComponent(companyId)}`, company)
    return response.data.data
  },

  remove: async (companyId: string): Promise<void> => {
    await $api.delete<ApiResponse<null>>(`/companies/${encodeURIComponent(companyId)}`)
  },
}
