import type { components } from './schema';
import { getApi } from './index';

export type AdminSessionDTO = components['schemas']['AdminSessionDTO'];

export async function fetchAdminSession(signal?: AbortSignal): Promise<AdminSessionDTO> {
    return getApi().get('/api/v1/admin/session', undefined, signal);
}

export async function logoutAdminSession(signal?: AbortSignal): Promise<void> {
    await getApi().post('/api/v1/admin/session/logout', undefined, { signal });
}
