import type { components } from './schema';
import { apiPath, getApi } from './index';

export type ClientDTO = components['schemas']['ClientDTO'];
export type ClientRegistrationResult = components['schemas']['ClientRegistrationResult'];
export type RegisterClientBody = components['schemas']['RegisterClientBody'];
export type UpdateClientBody = components['schemas']['UpdateClientBody'];

export async function fetchOidcClients(signal?: AbortSignal): Promise<ClientDTO[]> {
    return getApi().get('/api/v1/admin/oidc/clients', undefined, signal);
}

export async function fetchOidcClient(clientId: string, signal?: AbortSignal): Promise<ClientDTO> {
    return getApi().get(apiPath('/api/v1/admin/oidc/clients/{client_id}', { client_id: clientId }), undefined, signal);
}

export async function registerOidcClient(body: RegisterClientBody, signal?: AbortSignal): Promise<ClientRegistrationResult> {
    return getApi().post('/api/v1/admin/oidc/clients', body, { signal });
}

export async function updateOidcClient(clientId: string, body: UpdateClientBody, signal?: AbortSignal): Promise<ClientDTO> {
    return getApi().put(apiPath('/api/v1/admin/oidc/clients/{client_id}', { client_id: clientId }), body, { signal });
}

export async function disableOidcClient(clientId: string, signal?: AbortSignal): Promise<ClientDTO> {
    return getApi().post(apiPath('/api/v1/admin/oidc/clients/{client_id}/disable', { client_id: clientId }), undefined, { signal });
}

export async function enableOidcClient(clientId: string, signal?: AbortSignal): Promise<ClientDTO> {
    return getApi().post(apiPath('/api/v1/admin/oidc/clients/{client_id}/enable', { client_id: clientId }), undefined, { signal });
}

export async function rotateOidcClientSecret(clientId: string, signal?: AbortSignal): Promise<ClientRegistrationResult> {
    return getApi().post(apiPath('/api/v1/admin/oidc/clients/{client_id}/rotate-secret', { client_id: clientId }), undefined, { signal });
}
