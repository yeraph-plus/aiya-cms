import { HttpResponse, http } from 'msw'
import type { components } from '~/common/api/generated/api'

type AuthMe = components['schemas']['AuthMe']
type LoginRequest = components['schemas']['LoginRequest']
type RegisterRequest = components['schemas']['RegisterRequest']
type TokenPair = components['schemas']['TokenPair']

const mockUser: AuthMe = {
  id: '00000000-0000-7000-8000-000000000001',
  username: 'admin',
  email: 'admin@example.local',
  display_name: 'Aiya Administrator',
  avatar_url: null,
  status: 'active',
  roles: ['admin'],
  capabilities: [
    'user:read_any',
    'user:update_any',
    'user:ban',
    'role:manage',
    'role:assign',
    'audit:read',
    'setting:read',
    'setting:update',
    'task:manage',
    'content:create',
    'content:update_any',
    'content:delete_any',
    'content:publish',
    'term:manage',
    'term:assign',
    'comment:moderate',
    'comment:delete_any',
  ],
}

let accessToken = 'mock-access-initial'
let refreshToken = 'mock-refresh-initial'
let authenticated = false

function pair(): TokenPair {
  accessToken = `mock-access-${Date.now()}`
  refreshToken = `mock-refresh-${Date.now()}`
  return {
    access_token: accessToken,
    refresh_token: refreshToken,
    token_type: 'bearer',
    expires_in: 900,
  }
}

function error(status: number, code: string, message: string) {
  const requestId = `mock-${Date.now().toString(36)}`
  return HttpResponse.json(
    { code, message, detail: null, request_id: requestId },
    { status, headers: { 'X-Request-ID': requestId } },
  )
}

function hasAuth(request: Request): boolean {
  return (
    authenticated &&
    request.headers.get('Authorization') === `Bearer ${accessToken}`
  )
}

const handlers = [
  http.post('*/api/v1/auth/login', async ({ request }) => {
    const payload = (await request.json()) as LoginRequest
    if (payload.identifier !== 'admin' || payload.password !== 'admin1234')
      return error(401, 'AUTH_002', 'Invalid credentials')

    authenticated = true
    const tokens = pair()
    return HttpResponse.json(tokens, {
      headers: {
        'Set-Cookie': `aiya_refresh=${tokens.refresh_token}; HttpOnly; Path=/api/v1/auth; SameSite=Strict`,
      },
    })
  }),

  http.post('*/api/v1/auth/register', async ({ request }) => {
    const payload = (await request.json()) as RegisterRequest
    if (payload.username === 'admin')
      return error(409, 'USER_002', 'Username already exists')
    mockUser.username = payload.username
    mockUser.email = payload.email
    mockUser.display_name = payload.display_name ?? payload.username
    return HttpResponse.json(
      { ...mockUser, roles: [], status: 'active' },
      { status: 201 },
    )
  }),

  http.post('*/api/v1/auth/refresh', ({ request }) => {
    const cookie = request.headers.get('cookie') ?? ''
    if (!cookie.includes(`aiya_refresh=${refreshToken}`))
      return error(401, 'AUTH_003', 'Refresh token is invalid')
    authenticated = true
    const tokens = pair()
    return HttpResponse.json(tokens, {
      headers: {
        'Set-Cookie': `aiya_refresh=${tokens.refresh_token}; HttpOnly; Path=/api/v1/auth; SameSite=Strict`,
      },
    })
  }),

  http.post('*/api/v1/auth/logout', ({ request }) => {
    if (hasAuth(request)) authenticated = false
    return new HttpResponse(null, {
      status: 204,
      headers: { 'Set-Cookie': 'aiya_refresh=; Max-Age=0; Path=/api/v1/auth' },
    })
  }),

  http.get('*/api/v1/auth/me', ({ request }) => {
    if (!hasAuth(request))
      return error(401, 'AUTH_001', 'Authentication required')
    return HttpResponse.json(mockUser)
  }),
]

export default handlers
