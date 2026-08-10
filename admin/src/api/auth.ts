import type { components } from './schema';
import { getApi } from './index';

export type MeDTO = components['schemas']['MeDTO'];

export async function fetchMe(signal?: AbortSignal): Promise<MeDTO> {
    return getApi().get<MeDTO>('/api/v1/auth/me', undefined, signal);
}
