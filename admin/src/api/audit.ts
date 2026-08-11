import type { components, paths } from './schema';
import { getApi } from './index';

export type AuditEntryDTO = components['schemas']['AuditEntryDTO'];
export type AuditPageDTO = components['schemas']['Page_AuditEntryDTO_'];
export type AuditQuery = NonNullable<paths['/api/v1/admin/audit/entries']['get']['parameters']['query']>;

export async function fetchAuditEntries(query: AuditQuery = {}, signal?: AbortSignal): Promise<AuditPageDTO> {
    return getApi().get('/api/v1/admin/audit/entries', query, signal);
}
