import type { components, paths } from './schema';
import { getApi } from './index';

export type PointsAdjustInput = components['schemas']['PointsAdjustInput'];
export type LedgerEntryDTO = components['schemas']['LedgerEntryDTO'];
export type PointsLedgerPageDTO = components['schemas']['Page_LedgerEntryDTO_'];
export type AdminPointsViewDTO = components['schemas']['AdminPointsViewDTO'];

export type AdminPointsLedgerQuery = NonNullable<paths['/api/v1/admin/points/ledger']['get']['parameters']['query']>;

export async function adjustPoints(body: PointsAdjustInput, signal?: AbortSignal): Promise<LedgerEntryDTO> {
    return getApi().post('/api/v1/admin/points/adjust', body, { signal });
}

export async function fetchAdminPointsLedger(query: AdminPointsLedgerQuery, signal?: AbortSignal): Promise<AdminPointsViewDTO> {
    return getApi().get('/api/v1/admin/points/ledger', query, signal);
}
