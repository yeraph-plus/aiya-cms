import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getApiMock, getMock, putMock, postMock, deleteMock } = vi.hoisted(() => ({
    getApiMock: vi.fn(),
    getMock: vi.fn(),
    putMock: vi.fn(),
    postMock: vi.fn(),
    deleteMock: vi.fn()
}));

vi.mock('@/api/index', () => ({
    getApi: getApiMock,
    apiPath: (template: string, params: Record<string, string | number>) => Object.entries(params).reduce((path, [key, value]) => path.replace(`{${key}}`, encodeURIComponent(String(value))), template)
}));

import { fetchAuditEntries } from '@/api/audit';
import { fetchSettingGroup, fetchSettingGroups, resetSettingGroup, updateSettingGroup } from '@/api/settings';
import { banUser, deleteUser, fetchUser, fetchUsers, unbanUser } from '@/api/identity';
import { adjustPoints, fetchAdminPointsLedger } from '@/api/points';
import { isProtectedOidcClient } from '@/api/oidc-admin';

describe('admin domain adapters', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        getApiMock.mockReturnValue({
            get: getMock,
            put: putMock,
            post: postMock,
            delete: deleteMock
        });
    });

    it('binds all settings operations to the generated endpoint group', async () => {
        await fetchSettingGroups();
        await fetchSettingGroup('object storage');
        await updateSettingGroup('general', {
            expected_version: 3,
            values: { maintenance_mode: true }
        });
        await resetSettingGroup('general');

        expect(getMock).toHaveBeenNthCalledWith(1, '/api/v1/admin/settings/groups', undefined, undefined);
        expect(getMock).toHaveBeenNthCalledWith(2, '/api/v1/admin/settings/groups/object%20storage', undefined, undefined);
        expect(putMock).toHaveBeenCalledWith('/api/v1/admin/settings/groups/general', { expected_version: 3, values: { maintenance_mode: true } }, { signal: undefined });
        expect(postMock).toHaveBeenCalledWith('/api/v1/admin/settings/groups/general/reset', undefined, { signal: undefined });
    });

    it('passes audit filters to the server-side page query', async () => {
        const query = {
            page: 2,
            size: 25,
            action: 'settings.update',
            actor_type: 'user',
            actor_id: 'admin-1',
            outcome: 'success',
            occurred_after: '2026-08-01T00:00:00.000Z',
            occurred_before: '2026-08-11T00:00:00.000Z'
        } as const;

        await fetchAuditEntries(query);

        expect(getMock).toHaveBeenCalledWith('/api/v1/admin/audit/entries', query, undefined);
    });

    it('binds user list and management operations to generated paths', async () => {
        await fetchUsers({ page: 2, size: 25, status: 'banned' });
        await fetchUser('user/1');
        await banUser('user/1', { reason: 'policy violation' });
        await unbanUser('user/1');
        await deleteUser('user/1');

        expect(getMock).toHaveBeenCalledWith('/api/v1/admin/users', { page: 2, size: 25, status: 'banned' }, undefined);
        expect(getMock).toHaveBeenCalledWith('/api/v1/admin/users/user%2F1', undefined, undefined);
        expect(postMock).toHaveBeenCalledWith('/api/v1/admin/users/user%2F1/ban', { reason: 'policy violation' }, { signal: undefined });
        expect(postMock).toHaveBeenCalledWith('/api/v1/admin/users/user%2F1/unban', undefined, { signal: undefined });
        expect(deleteMock).toHaveBeenCalledWith('/api/v1/admin/users/user%2F1', undefined, undefined);
    });

    it('binds points adjustment without inventing bucket fields', async () => {
        const body = {
            subject_type: 'identity',
            subject_id: 'user-1',
            amount: -20,
            reason: 'manual correction',
            idempotency_key: 'adjust-1'
        } as const;

        await adjustPoints(body);

        expect(postMock).toHaveBeenCalledWith('/api/v1/admin/points/adjust', body, {
            signal: undefined
        });
        expect(body).not.toHaveProperty('program_key');
        expect(body).not.toHaveProperty('bucket_id');
    });

    it('binds points ledger reads only to the admin endpoint group', async () => {
        await fetchAdminPointsLedger({ subject_id: 'user-1', page: 1, size: 20 });
        await fetchAdminPointsLedger({
            subject_id: 'user-1',
            program_key: 'credit',
            page: 1,
            size: 20
        });

        expect(getMock).toHaveBeenNthCalledWith(1, '/api/v1/admin/points/ledger', { subject_id: 'user-1', page: 1, size: 20 }, undefined);
        expect(getMock).toHaveBeenNthCalledWith(2, '/api/v1/admin/points/ledger', { subject_id: 'user-1', program_key: 'credit', page: 1, size: 20 }, undefined);
    });
});

describe('OIDC client safety', () => {
    it('protects the administrator client from the disable action', () => {
        expect(isProtectedOidcClient({ client_id: 'admin' })).toBe(true);
        expect(isProtectedOidcClient({ client_id: 'client-public' })).toBe(false);
    });
});
