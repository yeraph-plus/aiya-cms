import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type LevelDTO = components['schemas']['LevelDTO'];
export type SubscriptionDTO = components['schemas']['AdminSubscriptionDTO'];
export type SubscriptionPageDTO = components['schemas']['Page_AdminSubscriptionDTO_'];
export type MembershipCycleDTO = components['schemas']['MembershipCycleDTO'];
export type RenewalPageDTO = components['schemas']['Page_MembershipCycleDTO_'];
export type CancelInput = components['schemas']['CancelInput'];
export type TerminateInput = components['schemas']['TerminateInput'];
export type SubscriptionQuery = NonNullable<paths['/api/v1/admin/membership/subscriptions']['get']['parameters']['query']>;
export type RenewalQuery = NonNullable<paths['/api/v1/admin/membership/subscriptions/{subscription_id}/cycles']['get']['parameters']['query']>;
export type CreateLevelInput = components['schemas']['CreateLevelInput'];
export type UpdateLevelInput = components['schemas']['UpdateLevelInput'];

export interface MembershipSummaryDTO {
    level_count: number;
    active_level_count: number;
    subscription_count: number;
    active_subscription_count: number;
    cancelled_subscription_count: number;
    expired_subscription_count: number;
}

export async function fetchMembershipLevels(signal?: AbortSignal): Promise<LevelDTO[]> {
    return getApi().get('/api/v1/admin/membership/levels', undefined, signal);
}

export async function createMembershipLevel(body: CreateLevelInput, signal?: AbortSignal): Promise<LevelDTO> {
    return getApi().post('/api/v1/admin/membership/levels', body, { signal });
}

export async function updateMembershipLevel(levelKey: string, body: UpdateLevelInput, signal?: AbortSignal): Promise<LevelDTO> {
    return getApi().patch(
        apiPath('/api/v1/admin/membership/levels/{level_key}', {
            level_key: levelKey
        }),
        body,
        { signal }
    );
}

export async function setMembershipLevelStatus(levelKey: string, status: 'activate' | 'archive', signal?: AbortSignal, expectedVersion = 1): Promise<LevelDTO> {
    const body = { expected_version: expectedVersion, reason: `admin ${status}` };
    if (status === 'activate') {
        return getApi().post(
            apiPath('/api/v1/admin/membership/levels/{level_key}/activate', {
                level_key: levelKey
            }),
            body,
            { signal }
        );
    }
    return getApi().post(
        apiPath('/api/v1/admin/membership/levels/{level_key}/archive', {
            level_key: levelKey
        }),
        body,
        { signal }
    );
}

export async function fetchMembershipSummary(signal?: AbortSignal): Promise<MembershipSummaryDTO> {
    return getApi().get('/api/v1/admin/membership/summary', undefined, signal);
}

export async function fetchSubscriptions(query?: SubscriptionQuery, signal?: AbortSignal): Promise<SubscriptionPageDTO> {
    return getApi().get('/api/v1/admin/membership/subscriptions', query, signal);
}

export async function fetchSubscriptionRenewals(subscriptionId: string, query?: RenewalQuery, signal?: AbortSignal): Promise<RenewalPageDTO> {
    return getApi().get(apiPath('/api/v1/admin/membership/subscriptions/{subscription_id}/cycles', { subscription_id: subscriptionId }), query, signal);
}

export async function cancelSubscription(subscriptionId: string, body: CancelInput, signal?: AbortSignal): Promise<SubscriptionDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/membership/subscriptions/{subscription_id}/cancel', {
            subscription_id: subscriptionId
        }),
        body,
        { signal }
    );
}

export async function terminateSubscription(subscriptionId: string, body: TerminateInput, signal?: AbortSignal): Promise<SubscriptionDTO> {
    return getApi().post(apiPath('/api/v1/admin/membership/subscriptions/{subscription_id}/terminate', { subscription_id: subscriptionId }), body, { signal });
}
