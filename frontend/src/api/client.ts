import axios, { AxiosError, AxiosResponse } from 'axios'
import { requestTransform, responseTransform } from './transformRegistry'
import { ApiError } from '../types'

// API base resolution:
//  - VITE_API_URL wins when set
//  - dev builds (vite dev server) talk to the backend on :8000 directly
//  - production builds use SAME-ORIGIN ('' base): nginx serves the SPA and
//    proxies /api and /ws to the backend (frontend/nginx.conf) — the old
//    http://<hostname>:8000 guess pointed at an unpublished port in prod.
const getApiUrl = () => {
  const envUrl = import.meta.env?.VITE_API_URL
  if (envUrl) return envUrl

  if (import.meta.env.DEV) {
    return `http://${window.location.hostname || 'localhost'}:8000`
  }
  return ''
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
api.interceptors.request.use(requestTransform)

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
api.interceptors.response.use(responseTransform)

api.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && originalRequest) {
      // Try to refresh token
      const refreshToken = localStorage.getItem('refreshToken')
      if (refreshToken) {
        try {
          // Raw axios on purpose: must not recurse through this interceptor.
          // Request body is camelCase (matches backend RefreshRequest);
          // the RESPONSE is the snake_case Token schema — reading
          // `accessToken` here stored undefined and broke every refresh.
          const response = await axios.post(`${API_URL}/api/v1/auth/refresh`, {
            refreshToken,
          })
          const { access_token: accessToken, refresh_token: newRefreshToken } = response.data
          localStorage.setItem('accessToken', accessToken)
          if (newRefreshToken) {
            localStorage.setItem('refreshToken', newRefreshToken)
          }
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
