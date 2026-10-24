import { $api } from "@/api/api";
import type { ApiResponse, Auth, Credentials, User } from "@/api/types";

export const authApi = {
  login: async (credentials: Credentials): Promise<Auth> => {
    const response = await $api.post<ApiResponse<Auth>>('/auth/login', credentials)
    return response.data.data
  },

  register: async (credentials: Credentials): Promise<Auth> => {
    const response = await $api.post<ApiResponse<Auth>>('/auth/register', credentials)
    return response.data.data
  },

  logout: async (): Promise<void> => {
    await $api.post<ApiResponse<null>>('/auth/logout')
  },

  me: async (): Promise<User> => {
    const response = await $api.get<ApiResponse<User>>('/me')
    return response.data.data
  },
}
