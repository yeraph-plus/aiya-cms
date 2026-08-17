import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type PointsAdjustInput = components['schemas']['PointsAdjustInput'];
export type LedgerEntryDTO = components['schemas']['LedgerEntryDTO'];
export type PointsLedgerPageDTO = components['schemas']['Page_LedgerEntryDTO_'];
export type AdminPointsViewDTO = components['schemas']['AdminPointsViewDTO'];
export type PointsProgramDTO = components['schemas']['PointsProgramDTO'];
export type PointsProgramInput = components['schemas']['PointsProgramInput'];
export type PointsProgramPatch = components['schemas']['PointsProgramPatch'];

export interface PointsSummaryDTO {
    program_count: number;
    account_count: number;
    active_account_count: number;
    frozen_account_count: number;
    debt_account_count: number;
    total_balance: number;
}

export interface PointsAccountAdminDTO {
    account_id: string;
    program_key: string;
    subject_type: string;
    subject_id: string;
    state: string;
    balance: number;
    version: number;
    subject?: components['schemas']['AdminSubjectRefDTO'] | null;
}

export interface PointsAccountPageDTO {
    items: PointsAccountAdminDTO[];
    total: number;
    page: number;
    size: number;
}

export type AdminPointsLedgerQuery = NonNullable<paths['/api/v1/admin/points/ledger']['get']['parameters']['query']>;

export async function adjustPoints(body: PointsAdjustInput, signal?: AbortSignal): Promise<LedgerEntryDTO> {
    return getApi().post('/api/v1/admin/points/adjust', body, { signal });
}

export async function fetchAdminPointsLedger(query: AdminPointsLedgerQuery, signal?: AbortSignal): Promise<AdminPointsViewDTO> {
    return getApi().get('/api/v1/admin/points/ledger', query, signal);
}

export async function fetchPointsPrograms(signal?: AbortSignal): Promise<PointsProgramDTO[]> {
    return getApi().get('/api/v1/admin/points/programs', undefined, signal);
}

export async function createPointsProgram(body: PointsProgramInput, signal?: AbortSignal): Promise<PointsProgramDTO> {
    return getApi().post('/api/v1/admin/points/programs', body, { signal });
}

export async function updatePointsProgram(programKey: string, body: PointsProgramPatch, signal?: AbortSignal): Promise<PointsProgramDTO> {
    return getApi().patch(
        apiPath('/api/v1/admin/points/programs/{program_key}', {
            program_key: programKey
        }),
        body,
        { signal }
    );
}

export async function setPointsProgramStatus(programKey: string, status: 'activate' | 'deactivate', signal?: AbortSignal, expectedVersion = 1): Promise<PointsProgramDTO> {
    const body = { expected_version: expectedVersion, reason: `admin ${status}` };
    if (status === 'activate') {
        return getApi().post(
            apiPath('/api/v1/admin/points/programs/{program_key}/activate', {
                program_key: programKey
            }),
            body,
            { signal }
        );
    }
    return getApi().post(
        apiPath('/api/v1/admin/points/programs/{program_key}/deactivate', {
            program_key: programKey
        }),
        body,
        { signal }
    );
}

export async function fetchPointsSummary(signal?: AbortSignal): Promise<PointsSummaryDTO> {
    return getApi().get('/api/v1/admin/points/summary', undefined, signal);
}

export type PointsAccountQuery = NonNullable<paths['/api/v1/admin/points/accounts']['get']['parameters']['query']>;

export async function fetchPointsAccounts(query?: PointsAccountQuery, signal?: AbortSignal): Promise<PointsAccountPageDTO> {
    return getApi().get('/api/v1/admin/points/accounts', query, signal);
}
