import type { ApiClient } from './client';

let api: ApiClient | null = null;

export function configureApi(client: ApiClient): void {
    api = client;
}

export function getApi(): ApiClient {
    if (api === null) {
        throw new Error('api client not configured; call configureApi from the composition root');
    }
    return api;
}

export { createApiClient } from './client';
export type { ApiClient, ApiClientOptions, PathKeys } from './client';
export { ApiError, errorMessage, requestIdOf } from './errors';
export { pageQuery, pageCount, isPageDTO } from './pagination';
export type { PageDTO } from './pagination';
export { fetchMe } from './auth';
export type { MeDTO } from './auth';
