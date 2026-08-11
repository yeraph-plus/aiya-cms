import type { components } from './schema';
import { apiPath, getApi } from './index';

export type MeDTO = components['schemas']['MeDTO'];
export type GrantConsentDTO = components['schemas']['GrantConsentDTO'];

export async function fetchMe(signal?: AbortSignal): Promise<MeDTO> {
    return getApi().get('/api/v1/me', undefined, signal);
}

export async function fetchGrants(signal?: AbortSignal): Promise<GrantConsentDTO[]> {
    return getApi().get('/api/v1/auth/grants', undefined, signal);
}

export async function revokeGrant(clientId: string, signal?: AbortSignal): Promise<void> {
    return getApi().delete(apiPath('/api/v1/auth/grants/{client_id}', { client_id: clientId }), undefined, signal);
}
