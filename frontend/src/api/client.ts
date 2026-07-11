import axios, { AxiosError, AxiosResponse } from 'axios'
import { ApiError } from '../types'

// Use window.location.hostname to dynamically determine API URL
const getApiUrl = () => {
  // @ts-ignore
  const envUrl = import.meta.env?.VITE_API_URL
  if (envUrl) return envUrl
  
  // If accessing from IP, use IP for API calls too
  const hostname = window.location.hostname
  if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
    return `http://${hostname}:8000`
  }
  
  return 'http://localhost:8000'
}

const API_URL = getApiUrl()

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
})

// Request interceptor - attach the real auth token (or none, letting the
// backend 401). The dev-token bypass is only ever present when devLogin stored
// it, which is gated to non-production builds.
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('accessToken') || localStorage.getItem('devToken')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor - handle errors and token refresh
api.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && originalRequest) {
      // Try to refresh token
      const refreshToken = localStorage.getItem('refreshToken')
      if (refreshToken) {
        try {
          const response = await axios.post(`${API_URL}/api/v1/auth/refresh`, {
            refreshToken,
          })
          const { accessToken } = response.data
          localStorage.setItem('accessToken', accessToken)
          originalRequest.headers.Authorization = `Bearer ${accessToken}`
          return api(originalRequest)
        } catch (refreshError) {
          // Refresh failed, logout user
          localStorage.removeItem('accessToken')
          localStorage.removeItem('refreshToken')
          localStorage.removeItem('devToken')
          localStorage.removeItem('user')
          window.location.href = '/login'
          return Promise.reject(refreshError)
        }
      } else {
        // No refresh token, logout user
        localStorage.removeItem('accessToken')
        localStorage.removeItem('refreshToken')
        localStorage.removeItem('devToken')
        localStorage.removeItem('user')
        window.location.href = '/login'
      }
    }

    return Promise.reject(error)
  }
)

export function handleApiError(error: unknown): ApiError {
  if (axios.isAxiosError(error)) {
    return {
      status: error.response?.status || 500,
      message: (error.response?.data as any)?.detail || error.message || 'An error occurred',
      details: (error.response?.data as any)?.details,
    }
  }
  return {
    status: 500,
    message: error instanceof Error ? error.message : 'An unknown error occurred',
  }
}
