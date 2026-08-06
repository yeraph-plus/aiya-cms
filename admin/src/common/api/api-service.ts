import type { ListResult } from '~/models/ListResult'
import {
  defaultOptions,
  type PagedAndSortedRequest,
} from '~/models/PagedAndSortedRequest'
import type { PaginatedList } from '~/models/PagedListResult'
import { request } from './api-client'

function withQuery(path: string, params?: Record<string, unknown>): string {
  if (!params) return path
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) query.append(key, String(item))
    } else {
      query.set(key, String(value))
    }
  }
  const serialized = query.toString()
  return serialized ? `${path}?${serialized}` : path
}

export class ApiService {
  private readonly apiBase: string

  constructor(apiBase: string) {
    const normalized = apiBase.replace(/^\/+|\/+$/g, '')
    this.apiBase = normalized.startsWith('api/')
      ? `/${normalized}`
      : `/api/${normalized}`
  }

  private path(url = ''): string {
    return `${this.apiBase}/${url}`.replace(/\/+/g, '/')
  }

  async get<T>(url = ''): Promise<T> {
    return request<T>(this.path(url))
  }

  async getList<T>(
    url: string,
    params: Record<string, unknown>,
  ): Promise<ListResult<T>> {
    return request<ListResult<T>>(withQuery(this.path(url), params))
  }

  async getPagedList<T>(
    url = '',
    options: PagedAndSortedRequest = defaultOptions,
  ): Promise<PaginatedList<T>> {
    return request<PaginatedList<T>>(
      withQuery(this.path(url), this.removeDefaultOptions(options)),
    )
  }

  async query<T>(url: string, params?: Record<string, unknown>): Promise<T> {
    return request<T>(withQuery(this.path(url), params))
  }

  async post<T>(url: string, data: unknown): Promise<T> {
    return request<T>(this.path(url), {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async put<T>(url: string, data: unknown): Promise<T> {
    return request<T>(this.path(url), {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  async delete<T>(url: string): Promise<T> {
    return request<T>(this.path(url), { method: 'DELETE' })
  }

  async getBlobFile(url: string, params: Record<string, unknown>) {
    return request<Blob>(withQuery(this.path(url), params), {
      headers: { Accept: '*/*' },
      responseType: 'blob',
    })
  }

  async postFile(url: string, params: { files: File[] }) {
    const formData = new FormData()
    params.files.forEach((file) => {
      formData.append('files', file)
    })
    return request(this.path(url), { method: 'POST', body: formData })
  }

  removeDefaultOptions(options: PagedAndSortedRequest): PagedAndSortedRequest {
    const result: PagedAndSortedRequest = {} as PagedAndSortedRequest
    for (const prop of Object.keys(options)) {
      const value = options[prop as keyof PagedAndSortedRequest]
      if (value === null || value === undefined || value === '') continue
      if (this.isDefaultProperty(prop)) continue
      result[prop] = value
    }
    return result
  }

  isDefaultProperty(prop: string): boolean {
    return [
      'pageCount',
      'onUpdatePageSize',
      'showSizePicker',
      'pageSizes',
    ].includes(prop)
  }
}
