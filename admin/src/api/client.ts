import type { paths } from './schema';
import { ApiError } from './errors';
import { assertAdminSpaApiPath } from './scope';

export type PathKeys = keyof paths;
type HttpMethod = 'get' | 'post' | 'put' | 'patch' | 'delete';
type Operation<P extends PathKeys, M extends HttpMethod> = M extends keyof paths[P] ? paths[P][M] : never;
type QueryFor<P extends PathKeys, M extends HttpMethod> = Operation<P, M> extends { parameters: infer Parameters } ? (Parameters extends { query?: infer Query } ? Query : undefined) : undefined;
type BodyFor<P extends PathKeys, M extends HttpMethod> = Operation<P, M> extends { requestBody: { content: infer Content } } ? (Content extends { 'application/json': infer Body } ? Body : undefined) : undefined;
type ResponseFor<P extends PathKeys, M extends HttpMethod> =
    Operation<P, M> extends { responses: infer Responses }
        ? 200 extends keyof Responses
            ? Responses[200] extends { content: infer Content }
                ? Content extends { 'application/json': infer Body }
                    ? Body
                    : undefined
                : undefined
            : undefined
        : never;

export interface ApiPath<P extends PathKeys> {
    readonly template: P;
    readonly value: string;
}

export function apiPath<P extends PathKeys>(template: P, params: Record<string, string | number>): ApiPath<P> {
    let value = template as string;
    for (const [key, parameter] of Object.entries(params)) {
        value = value.replace(`{${key}}`, encodeURIComponent(String(parameter)));
    }
    if (/\{[^}]+\}/u.test(value)) throw new Error(`Missing path parameter in ${template}`);
    return { template, value };
}

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

type Query = RequestOptions['query'];

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
        assertAdminSpaApiPath(req.path);
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
        get: <P extends PathKeys>(path: P | ApiPath<P>, query?: QueryFor<P, 'get'>, signal?: AbortSignal) => request<ResponseFor<P, 'get'>>({ method: 'GET', path: typeof path === 'string' ? path : path.value, query: query as Query, signal }),
        post: <P extends PathKeys>(
            path: P | ApiPath<P>,
            ...args: BodyFor<P, 'post'> extends undefined
                ? [body?: undefined, options_?: { idempotencyKey?: string; query?: QueryFor<P, 'post'>; signal?: AbortSignal }]
                : [body: BodyFor<P, 'post'>, options_?: { idempotencyKey?: string; query?: QueryFor<P, 'post'>; signal?: AbortSignal }]
        ) => {
            const [body, options_] = args;
            return request<ResponseFor<P, 'post'>>({ method: 'POST', path: typeof path === 'string' ? path : path.value, body, query: options_?.query as Query, idempotencyKey: options_?.idempotencyKey, signal: options_?.signal });
        },
        put: <P extends PathKeys>(
            path: P | ApiPath<P>,
            ...args: BodyFor<P, 'put'> extends undefined
                ? [body?: undefined, options_?: { idempotencyKey?: string; query?: QueryFor<P, 'put'>; signal?: AbortSignal }]
                : [body: BodyFor<P, 'put'>, options_?: { idempotencyKey?: string; query?: QueryFor<P, 'put'>; signal?: AbortSignal }]
        ) => {
            const [body, options_] = args;
            return request<ResponseFor<P, 'put'>>({ method: 'PUT', path: typeof path === 'string' ? path : path.value, body, query: options_?.query as Query, idempotencyKey: options_?.idempotencyKey, signal: options_?.signal });
        },
        patch: <P extends PathKeys>(
            path: P | ApiPath<P>,
            ...args: BodyFor<P, 'patch'> extends undefined
                ? [body?: undefined, options_?: { idempotencyKey?: string; query?: QueryFor<P, 'patch'>; signal?: AbortSignal }]
                : [body: BodyFor<P, 'patch'>, options_?: { idempotencyKey?: string; query?: QueryFor<P, 'patch'>; signal?: AbortSignal }]
        ) => {
            const [body, options_] = args;
            return request<ResponseFor<P, 'patch'>>({ method: 'PATCH', path: typeof path === 'string' ? path : path.value, body, query: options_?.query as Query, idempotencyKey: options_?.idempotencyKey, signal: options_?.signal });
        },
        delete: <P extends PathKeys>(path: P | ApiPath<P>, query?: QueryFor<P, 'delete'>, signal?: AbortSignal) =>
            request<ResponseFor<P, 'delete'>>({ method: 'DELETE', path: typeof path === 'string' ? path : path.value, query: query as Query, signal })
    };
}

export type ApiClient = ReturnType<typeof createApiClient>;
