import type { APIContext } from 'astro';

import type { components, operations } from '@/lib/api/generated/schema';
import { createGuardedServerFetch } from '@/lib/api/server/client';
import { verifySameOriginForm } from '@/lib/auth/server/csrf';

export type PointOrderInput = operations['point_order_api_v1_me_points_orders_post']['requestBody']['content']['application/json'];
export type MembershipOrderInput = operations['membership_order_api_v1_me_membership_orders_post']['requestBody']['content']['application/json'];
export type CancelMembershipInput = operations['membership_cancel_api_v1_me_membership_cancel_post']['requestBody']['content']['application/json'];
export type GiftCardRedemptionInput = operations['gift_card_redemption_api_v1_me_gift_cards_redemptions_post']['requestBody']['content']['application/json'];
export type DownloadGrantPage = components['schemas']['DownloadGrantPageDTO'];
export type DownloadLinks = components['schemas']['ResolveDownloadLinksDTO'];

interface PointsSummary {
    balance: number;
    opened: boolean;
    program_key: string;
    buckets?: unknown[];
}

export interface CurrentUser {
    avatar_url?: string | null;
    capabilities?: string[];
    display_name?: string | null;
    points?: PointsSummary | null;
    status: string;
    subject_id: string;
    username?: string | null;
}

export type UserMeState =
    | { kind: 'ready'; data: CurrentUser }
    | { kind: 'unauthenticated' }
    | { kind: 'forbidden' }
    | { kind: 'unavailable' }
    | { kind: 'invalid' };

export interface AccountSectionData {
    downloads?: DownloadGrantPage;
    ledger?: Record<string, unknown>;
    membership?: unknown;
    membershipLevels?: Record<string, unknown>[];
    pointProducts?: Record<string, unknown>[];
    points?: Record<string, unknown>;
    purchases?: Record<string, unknown>;
}

export type AccountSectionState =
    | { kind: 'ready'; data: AccountSectionData }
    | { kind: 'unauthenticated' | 'forbidden' | 'unavailable' | 'invalid'; data: AccountSectionData };

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function asRecord(value: unknown): Record<string, unknown> | null {
    return isRecord(value) ? value : null;
}

export function asRecordArray(value: unknown): Record<string, unknown>[] {
    if (Array.isArray(value)) return value.filter(isRecord);
    const record = asRecord(value);
    return record && Array.isArray(record.items) ? record.items.filter(isRecord) : [];
}

function isCurrentUser(value: unknown): value is CurrentUser {
    return (
        isRecord(value) &&
        typeof value.subject_id === 'string' &&
        typeof value.status === 'string' &&
        (value.points === undefined ||
            value.points === null ||
            (isRecord(value.points) &&
                typeof value.points.balance === 'number' &&
                typeof value.points.opened === 'boolean' &&
                typeof value.points.program_key === 'string'))
    );
}


async function readJson(fetcher: typeof fetch, path: string): Promise<{ status: number; data?: unknown }> {
    const response = await fetcher(path, { method: 'GET', cache: 'no-store' });
    return { status: response.status, ...(response.ok ? { data: await response.json() } : {}) };
}

function failureKind(status: number): Exclude<AccountSectionState['kind'], 'ready'> {
    if (status === 401) return 'unauthenticated';
    if (status === 403) return 'forbidden';
    return status >= 500 ? 'unavailable' : 'invalid';
}

export async function fetchAccountSection(
    context: APIContext,
    section: 'points' | 'membership' | 'purchases' | 'gift-card' | 'downloads',
    fetcher: typeof fetch = createGuardedServerFetch(context.session, context.locals.requestId)
): Promise<AccountSectionState> {
    const paths = section === 'points'
        ? ['/api/v1/me/points', '/api/v1/me/points/ledger?page=1&size=20', '/api/v1/points/products']
        : section === 'membership'
          ? ['/api/v1/membership/levels', '/api/v1/me/membership']
          : section === 'purchases'
            ? ['/api/v1/me/purchases?page=1&size=20']
            : section === 'downloads'
              ? ['/api/v1/me/downloads?page=1&size=20']
              : [];
    try {
        const responses = await Promise.all(paths.map((path) => readJson(fetcher, path)));
        const failed = responses.find((response) => response.status < 200 || response.status >= 300);
        if (failed) return { kind: failureKind(failed.status), data: {} };
        if (section === 'points') {
            const points = asRecord(responses[0]?.data);
            const ledger = asRecord(responses[1]?.data);
            if (!points || !ledger) return { kind: 'invalid', data: {} };
            return { kind: 'ready', data: { points, ledger, pointProducts: asRecordArray(responses[2]?.data) } };
        }
        if (section === 'membership') {
            return { kind: 'ready', data: { membershipLevels: asRecordArray(responses[0]?.data), membership: responses[1]?.data ?? null } };
        }
        if (section === 'purchases') {
            const purchases = asRecord(responses[0]?.data);
            return purchases ? { kind: 'ready', data: { purchases } } : { kind: 'invalid', data: {} };
        }
        if (section === 'downloads') {
            const downloads = asRecord(responses[0]?.data);
            if (!downloads || !Array.isArray(downloads.items)) return { kind: 'invalid', data: {} };
            return { kind: 'ready', data: { downloads: downloads as unknown as DownloadGrantPage } };
        }
        return { kind: 'ready', data: {} };
    } catch {
        return { kind: 'unavailable', data: {} };
    }
}

export async function fetchCurrentUser(
    context: APIContext,
    fetcher: typeof fetch = createGuardedServerFetch(context.session, context.locals.requestId)
): Promise<UserMeState> {
    try {
        const response = await fetcher('/api/v1/me', { method: 'GET', cache: 'no-store' });
        if (response.status === 401) return { kind: 'unauthenticated' };
        if (response.status === 403) return { kind: 'forbidden' };
        if (response.status === 503 || response.status >= 500) return { kind: 'unavailable' };
        if (!response.ok) return { kind: 'invalid' };
        const data: unknown = await response.json();
        return isCurrentUser(data) ? { kind: 'ready', data } : { kind: 'invalid' };
    } catch {
        return { kind: 'unavailable' };
    }
}

export type IdentityActionState = 'success' | 'invalid' | 'unavailable';

export async function submitIdentityForm(
    context: APIContext,
    form: FormData,
    endpoint: '/api/v1/auth/register' | '/api/v1/auth/verify-email' | '/api/v1/auth/password-reset/request' | '/api/v1/auth/password-reset/confirm',
    body: Record<string, string>
): Promise<IdentityActionState> {
    if (!context.session) return 'unavailable';
    const token = form.get('csrf');
    await verifySameOriginForm(context.request, context.session, typeof token === 'string' ? token : null);

    try {
        const fetcher = createGuardedServerFetch(context.session, context.locals.requestId);
        const response = await fetcher(endpoint, {
            method: 'POST',
            cache: 'no-store',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (response.ok) return 'success';
        return response.status >= 500 ? 'unavailable' : 'invalid';
    } catch {
        return 'unavailable';
    }
}
