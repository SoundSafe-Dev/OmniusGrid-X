import axios, { AxiosError, AxiosResponse } from 'axios'
import { ApiError, AuthResponse } from '../types'

// Use window.location.hostname to dynamically determine API URL
const getApiUrl = () => {
  // @ts-ignore
  const envUrl = import.meta.env?.VITE_API_URL
  if (envUrl) return envUrl
  
  // If accessing from IP, use IP for API calls too
  const hostname = window.location.hostname
  if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
    return `http://${hostname}:8002`
  }
  
  return 'http://localhost:8002'
}

const API_URL = getApiUrl()

type RotatedTokens = {
  accessToken: string
  refreshToken: string
}

type RetriableRequest = NonNullable<AxiosError['config']> & {
  _retry?: boolean
}

let refreshPromise: Promise<RotatedTokens> | null = null

const clearStoredAuth = () => {
  localStorage.removeItem('accessToken')
  localStorage.removeItem('refreshToken')
  localStorage.removeItem('devToken')
  localStorage.removeItem('user')
  localStorage.removeItem('auth-storage')
}

const redirectToLogin = () => {
  if (window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

const rotateTokens = (): Promise<RotatedTokens> => {
  if (refreshPromise) return refreshPromise

  const refreshToken = localStorage.getItem('refreshToken')
  if (!refreshToken) {
    return Promise.reject(new Error('No refresh token available'))
  }

  refreshPromise = axios
    .post<AuthResponse>(`${API_URL}/api/v1/auth/refresh`, { refreshToken })
    .then(({ data }) => {
      const tokens = {
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
      }
      localStorage.setItem('accessToken', tokens.accessToken)
      localStorage.setItem('refreshToken', tokens.refreshToken)
      return tokens
    })
    .finally(() => {
      refreshPromise = null
    })

  return refreshPromise
}

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
})

// Request interceptor - add auth token
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
    const originalRequest = error.config as RetriableRequest | undefined
    const requestPath = originalRequest?.url || ''
    const isSessionExchange =
      requestPath.includes('/api/v1/auth/login') ||
      requestPath.includes('/api/v1/auth/refresh') ||
      requestPath.includes('/api/v1/auth/logout')

    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest._retry &&
      !isSessionExchange
    ) {
      originalRequest._retry = true
      try {
        const { accessToken } = await rotateTokens()
        originalRequest.headers.Authorization = `Bearer ${accessToken}`
        return api(originalRequest)
      } catch (refreshError) {
        clearStoredAuth()
        redirectToLogin()
        return Promise.reject(refreshError)
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
