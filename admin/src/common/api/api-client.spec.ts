import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, clearAccessToken, login, me, request } from './api-client'

describe('api client authentication replay', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    clearAccessToken()
  })

  it('reuses the original request id after refreshing a 401', async () => {
    const calls: Array<{ url: string; requestId: string | null }> = []
    let call = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const headers = new Headers(init?.headers)
        calls.push({
          url: String(input),
          requestId: headers.get('X-Request-ID'),
        })
        call += 1
        if (call === 1) {
          return new Response(
            JSON.stringify({
              access_token: 'access-1',
              refresh_token: 'refresh-1',
              expires_in: 900,
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }
        if (call === 2) {
          return new Response(
            JSON.stringify({ code: 'AUTH_002', message: 'expired' }),
            {
              status: 401,
              headers: { 'Content-Type': 'application/json' },
            },
          )
        }
        if (call === 3) {
          return new Response(
            JSON.stringify({
              access_token: 'access-2',
              refresh_token: 'refresh-2',
              expires_in: 900,
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }
        return new Response(
          JSON.stringify({
            id: '00000000-0000-7000-8000-000000000001',
            username: 'alice',
            email: 'alice@example.com',
            display_name: 'Alice',
            avatar_url: null,
            status: 'active',
            roles: [],
            capabilities: [],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }),
    )

    await login('alice', 'password')
    await me()

    expect(calls[1]?.requestId).toBeTruthy()
    expect(calls[1]?.requestId).toBe(calls[3]?.requestId)
  })

  it('maps network and timeout failures to stable ApiError codes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    await expect(request('/api/v1/health', {}, false)).rejects.toMatchObject({
      code: 'COMMON_NETWORK',
      status: 0,
    })

    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            )
          }),
      ),
    )
    const timeout = request('/api/v1/health', { timeoutMs: 1 }, false)
    await expect(timeout).rejects.toBeInstanceOf(ApiError)
    await expect(timeout).rejects.toMatchObject({ code: 'COMMON_TIMEOUT' })
  })

  it('returns undefined for an explicit 204 response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 204 })),
    )
    await expect(
      request<void>('/api/v1/auth/logout', { method: 'POST' }, false),
    ).resolves.toBeUndefined()
  })

  it('preserves FastAPI detail messages for HTTP errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: 'Not Found' }), {
            status: 404,
            headers: {
              'Content-Type': 'application/json',
              'X-Request-ID': 'req-404',
            },
          }),
      ),
    )

    await expect(request('/api/v1/missing', {}, false)).rejects.toMatchObject({
      message: 'Not Found',
      status: 404,
      requestId: 'req-404',
    })
  })
})
