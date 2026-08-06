import { request } from './api-client'
import type { components } from './generated/api'

type Schemas = components['schemas']
export type QueryParams = Record<string, string | number | boolean | undefined>

export interface Page<T> {
  items: T[]
  total: number
  page: number
  size: number
}

export type UserAdmin = Omit<Schemas['UserAdminRead'], 'roles'> & {
  roles: string[]
}
export type Role = Omit<Schemas['RoleRead'], 'permissions'> & {
  permissions: string[]
}
export type ContentType = Schemas['ContentTypeRead']
export type ContentItem = Schemas['ContentRead']
export type Term = Schemas['TermRead']
export type Comment = Schemas['CommentRead']
export type AuditLog = Schemas['AuditLogRead']
export type TaskInstance = Schemas['TaskInstanceRead']

export type SettingGroup = Schemas['SettingGroupRead']
export type SettingPatch = Schemas['SettingPatch']

function query(path: string, params: QueryParams = {}) {
  const serialized = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    serialized.set(key, String(value))
  }
  const suffix = serialized.toString()
  return request(`${path}${suffix ? `?${suffix}` : ''}`)
}

export const adminApi = {
  dashboard: () =>
    request<{
      users_total: number | null
      contents_total: number | null
      comments_pending: number | null
      tasks_active: number | null
    }>('/api/v1/dashboard'),
  users: (params: QueryParams = {}) =>
    query('/api/v1/users', params) as Promise<Page<UserAdmin>>,
  user: (id: string) => request<UserAdmin>(`/api/v1/users/${id}`),
  updateUser: (
    id: string,
    payload: Partial<Pick<UserAdmin, 'display_name' | 'avatar_url'>>,
  ) =>
    request<UserAdmin>(`/api/v1/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  roles: () => request<Role[]>('/api/v1/roles'),
  replaceRoles: (id: string, roles: string[]) =>
    request<UserAdmin>(`/api/v1/users/${id}/roles`, {
      method: 'PUT',
      body: JSON.stringify({ roles }),
    }),
  ban: (id: string) =>
    request<UserAdmin>(`/api/v1/users/${id}/ban`, { method: 'POST' }),
  unban: (id: string) =>
    request<UserAdmin>(`/api/v1/users/${id}/unban`, { method: 'POST' }),
  contentTypes: () => request<ContentType[]>('/api/v1/content-types'),
  contents: (type: string, params: QueryParams = {}) =>
    query(`/api/v1/contents/${type}`, params) as Promise<Page<ContentItem>>,
  content: (type: string, slug: string) =>
    request<{
      content: ContentItem
      terms: Term[]
      comment_stats: { count: number }
    }>(`/api/v1/contents/${type}/${slug}`),
  createContent: (type: string, payload: Schemas['ContentCreate']) =>
    request<ContentItem>(`/api/v1/contents/${type}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateContent: (type: string, id: string, payload: Schemas['ContentUpdate']) =>
    request<ContentItem>(`/api/v1/contents/${type}/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  contentAction: (type: string, id: string, action: string) =>
    request<ContentItem>(`/api/v1/contents/${type}/${id}/${action}`, {
      method: 'POST',
    }),
  terms: (type: string, params: QueryParams = {}) =>
    query(`/api/v1/terms/${type}`, params) as Promise<Page<Term>>,
  term: (type: string, id: string) =>
    request<Term>(`/api/v1/terms/${type}/${id}`),
  createTerm: (type: string, payload: Schemas['TermCreate']) =>
    request<Term>(`/api/v1/terms/${type}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateTerm: (type: string, id: string, payload: Schemas['TermUpdate']) =>
    request<Term>(`/api/v1/terms/${type}/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteTerm: (type: string, id: string) =>
    request<void>(`/api/v1/terms/${type}/${id}`, { method: 'DELETE' }),
  assignTerms: (type: string, id: string, payload: Schemas['TermAssign']) =>
    request<Term[]>(`/api/v1/contents/${type}/${id}/terms`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  comments: (params: QueryParams = {}) =>
    query('/api/v1/comments/moderation', params) as Promise<Page<Comment>>,
  comment: (id: string) => request<Comment>(`/api/v1/comments/${id}`),
  moderateComment: (id: string, action: Schemas['ModerateRequest']['action']) =>
    request<Comment>(`/api/v1/comments/${id}/moderate`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    }),
  deleteComment: (id: string) =>
    request<void>(`/api/v1/comments/${id}`, { method: 'DELETE' }),
  audit: (params: QueryParams = {}) =>
    query('/api/v1/audit-logs', params) as Promise<Page<AuditLog>>,
  auditLog: (id: string) => request<AuditLog>(`/api/v1/audit-logs/${id}`),
  settings: () => request<SettingGroup[]>('/api/v1/settings'),
  updateSettingGroup: (groupSlug: string, payload: SettingPatch) =>
    request<SettingGroup>(`/api/v1/settings/${encodeURIComponent(groupSlug)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  tasks: (params: QueryParams = {}) =>
    query('/api/v1/tasks', params) as Promise<Page<TaskInstance>>,
  task: (id: string) => request<TaskInstance>(`/api/v1/tasks/${id}`),
}
