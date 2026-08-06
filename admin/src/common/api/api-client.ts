import type { components, operations, paths } from './generated/api'

export type AuthMe = components['schemas']['AuthMe']
export type ErrorResponse = components['schemas']['ErrorResponse']
export type TokenPair = components['schemas']['TokenPair']
export type UserRead = components['schemas']['UserRead']
export type HealthResponse =
  operations['health_api_v1_health_get']['responses'][200]['content']['application/json']

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly http_status: number
  readonly requestId: string
  readonly detail: unknown

  constructor(
    status: number,
    body: Partial<ErrorResponse> | Record<string, unknown> = {},
    requestId = '',
  ) {
    super(
      typeof body.message === 'string'
        ? body.message
        : typeof body.detail === 'string'
          ? body.detail
          : Array.isArray(body.detail)
            ? body.detail
                .map((item) =>
                  typeof item === 'string' ? item : JSON.stringify(item),
                )
                .join('; ')
            : `HTTP ${status} request failed`,
    )
    this.name = 'ApiError'
    this.status = status
    this.http_status = status
    this.code = typeof body.code === 'string' ? body.code : 'COMMON_500'
    this.requestId = requestId
    this.detail = body.detail
  }

  static network(cause: unknown, requestId: string): ApiError {
    const error = new ApiError(
      0,
      {
        code: 'COMMON_NETWORK',
        message: 'The service is unavailable',
        detail: cause,
      },
      requestId,
    )
    error.cause = cause
    return error
  }

  static timeout(requestId: string): ApiError {
    return new ApiError(
      0,
      {
        code: 'COMMON_TIMEOUT',
        message: 'The request timed out',
      },
      requestId,
    )
  }

  static canceled(requestId: string): ApiError {
    return new ApiError(
      0,
      {
        code: 'COMMON_CANCELED',
        message: 'The request was canceled',
      },
      requestId,
    )
  }
}

const configuredOrigin = String(import.meta.env.VITE_API_URL ?? '').replace(
  /\/$/,
  '',
)
const apiOrigin = configuredOrigin === '/api' ? '' : configuredOrigin
let accessToken: string | null = null
let refreshing: Promise<TokenPair> | null = null

export type RequestOptions = RequestInit & {
  responseType?: 'json' | 'blob'
  timeoutMs?: number
}

function requestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

function urlFor(path: string): string {
  return `${apiOrigin}${path.startsWith('/') ? path : `/${path}`}`
}

function asErrorBody(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : {}
}

export async function request<T>(
  path: string,
  init: RequestOptions = {},
  retry = true,
  replayId?: string,
): Promise<T> {
  const id = replayId ?? requestId()
  const {
    responseType = 'json',
    timeoutMs = 15_000,
    signal,
    ...fetchInit
  } = init
  const headers = new Headers(fetchInit.headers)
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  if (!(fetchInit.body instanceof FormData))
    headers.set('Content-Type', 'application/json')
  headers.set('X-Request-ID', id)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)

  const controller = new AbortController()
  let timedOut = false
  const abortFromCaller = () => controller.abort()
  if (signal) {
    if (signal.aborted) throw ApiError.canceled(id)
    signal.addEventListener('abort', abortFromCaller, { once: true })
  }
  const timeout =
    timeoutMs > 0
      ? setTimeout(() => {
          timedOut = true
          controller.abort()
        }, timeoutMs)
      : undefined

  let response: Response
  try {
    response = await fetch(urlFor(path), {
      ...fetchInit,
      headers,
      credentials: 'include',
      signal: controller.signal,
    })
  } catch (error) {
    if (timedOut) throw ApiError.timeout(id)
    if (signal?.aborted) throw ApiError.canceled(id)
    throw ApiError.network(error, id)
  } finally {
    if (timeout) clearTimeout(timeout)
    signal?.removeEventListener('abort', abortFromCaller)
  }

  if (response.status === 401 && retry && !path.endsWith('/auth/refresh')) {
    try {
      const pair = await refresh()
      accessToken = pair.access_token
      return request<T>(path, init, false, id)
    } catch {
      accessToken = null
    }
  }

  if (!response.ok) {
    let body: Record<string, unknown> = {}
    try {
      body = asErrorBody(await response.json())
    } catch {
      // Non-JSON failures still become a stable ApiError.
    }
    throw new ApiError(
      response.status,
      body,
      response.headers.get('X-Request-ID') ?? id,
    )
  }
  if (response.status === 204) return undefined as T
  if (responseType === 'blob') return (await response.blob()) as T
  return (await response.json()) as T
}

export async function login(
  identifier: string,
  password: string,
): Promise<TokenPair> {
  const pair = await request<TokenPair>(
    '/api/v1/auth/login',
    {
      method: 'POST',
      body: JSON.stringify({ identifier, password }),
    },
    false,
  )
  accessToken = pair.access_token
  return pair
}

export async function register(
  username: string,
  email: string,
  password: string,
  displayName?: string,
): Promise<UserRead> {
  return request<UserRead>(
    '/api/v1/auth/register',
    {
      method: 'POST',
      body: JSON.stringify({
        username,
        email,
        password,
        display_name: displayName ?? username,
      }),
    },
    false,
  )
}

export async function me(): Promise<AuthMe> {
  return request<AuthMe>('/api/v1/auth/me')
}

export async function health(): Promise<HealthResponse> {
  return request<HealthResponse>('/api/v1/health', {}, false)
}

export async function refresh(): Promise<TokenPair> {
  if (!refreshing) {
    refreshing = request<TokenPair>(
      '/api/v1/auth/refresh',
      { method: 'POST' },
      false,
    )
      .then((pair) => {
        accessToken = pair.access_token
        return pair
      })
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

export async function logout(): Promise<void> {
  try {
    await request<void>('/api/v1/auth/logout', { method: 'POST' }, false)
  } finally {
    accessToken = null
  }
}

export function getAccessToken(): string | null {
  return accessToken
}

export function clearAccessToken(): void {
  accessToken = null
}

export type ApiPaths = paths
