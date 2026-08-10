import type { paths } from './schema';
import { ApiError } from './errors';

export type PathKeys = keyof paths;

export interface ApiClientOptions {
    baseUrl: string;
    getAccessToken: () => string | null;
    onUnauthorized: () => void;
}

interface RequestOptions {
    method: string;
    path: string;
    query?: Record<string, string | number | boolean | undefined | null>;
    body?: unknown;
    idempotencyKey?: string;
    signal?: AbortSignal;
}

function newRequestId(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    return `req-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createApiClient(options: ApiClientOptions) {
    const buildUrl = (path: string, query?: RequestOptions['query']) => {
        const url = new URL(options.baseUrl + path);
        if (query) {
            for (const [key, value] of Object.entries(query)) {
                if (value !== undefined && value !== null) {
                    url.searchParams.set(key, String(value));
                }
            }
        }
        return url;
    };

    const request = async <T>(req: RequestOptions): Promise<T> => {
        const headers: Record<string, string> = {
            'X-Request-ID': newRequestId()
        };
        const token = options.getAccessToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;
        if (req.idempotencyKey) headers['Idempotency-Key'] = req.idempotencyKey;

        let body: BodyInit | undefined;
        if (req.body !== undefined) {
            headers['Content-Type'] = 'application/json';
            body = JSON.stringify(req.body);
        }

        const response = await fetch(buildUrl(req.path, req.query), {
            method: req.method,
            headers,
            body,
            signal: req.signal
        });

        if (response.status === 401) {
            options.onUnauthorized();
        }

        if (!response.ok) {
            const requestId = response.headers.get('x-request-id') ?? undefined;
            let detail: unknown;
            try {
                detail = await response.json();
            } catch {
                detail = null;
            }
            throw new ApiError(response.status, detail, requestId);
        }

        if (response.status === 204) {
            return undefined as T;
        }
        return (await response.json()) as T;
    };

    return {
        get: <T>(path: string, query?: RequestOptions['query'], signal?: AbortSignal) => request<T>({ method: 'GET', path, query, signal }),
        post: <T>(path: string, body?: unknown, options_?: { idempotencyKey?: string; signal?: AbortSignal }) => request<T>({ method: 'POST', path, body, idempotencyKey: options_?.idempotencyKey, signal: options_?.signal }),
        put: <T>(path: string, body?: unknown, options_?: { idempotencyKey?: string; signal?: AbortSignal }) => request<T>({ method: 'PUT', path, body, idempotencyKey: options_?.idempotencyKey, signal: options_?.signal }),
        patch: <T>(path: string, body?: unknown, options_?: { idempotencyKey?: string; signal?: AbortSignal }) => request<T>({ method: 'PATCH', path, body, idempotencyKey: options_?.idempotencyKey, signal: options_?.signal }),
        delete: <T>(path: string, query?: RequestOptions['query'], signal?: AbortSignal) => request<T>({ method: 'DELETE', path, query, signal })
    };
}

export type ApiClient = ReturnType<typeof createApiClient>;
