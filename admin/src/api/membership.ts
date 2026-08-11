import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type LevelDTO = components['schemas']['LevelDTO'];
export type SubscriptionDTO = components['schemas']['SubscriptionDTO'];
export type SubscriptionPageDTO = components['schemas']['Page_SubscriptionDTO_'];
export type RenewalRecordDTO = components['schemas']['RenewalRecordDTO'];
export type RenewalPageDTO = components['schemas']['Page_RenewalRecordDTO_'];
export type CancelInput = components['schemas']['CancelInput'];
export type TerminateInput = components['schemas']['TerminateInput'];
export type SubscriptionQuery = NonNullable<paths['/api/v1/admin/membership/subscriptions']['get']['parameters']['query']>;
export type RenewalQuery = NonNullable<paths['/api/v1/admin/membership/subscriptions/{subscription_id}/renewals']['get']['parameters']['query']>;

export async function fetchMembershipLevels(signal?: AbortSignal): Promise<LevelDTO[]> {
    return getApi().get('/api/v1/admin/membership/levels', undefined, signal);
}

export async function fetchSubscriptions(query?: SubscriptionQuery, signal?: AbortSignal): Promise<SubscriptionPageDTO> {
    return getApi().get('/api/v1/admin/membership/subscriptions', query, signal);
}

export async function fetchSubscriptionRenewals(subscriptionId: string, query?: RenewalQuery, signal?: AbortSignal): Promise<RenewalPageDTO> {
    return getApi().get(apiPath('/api/v1/admin/membership/subscriptions/{subscription_id}/renewals', { subscription_id: subscriptionId }), query, signal);
}

export async function cancelSubscription(subscriptionId: string, body: CancelInput, signal?: AbortSignal): Promise<SubscriptionDTO> {
    return getApi().post(apiPath('/api/v1/admin/membership/subscriptions/{subscription_id}/cancel', { subscription_id: subscriptionId }), body, { signal });
}

export async function terminateSubscription(subscriptionId: string, body: TerminateInput, signal?: AbortSignal): Promise<SubscriptionDTO> {
    return getApi().post(apiPath('/api/v1/admin/membership/subscriptions/{subscription_id}/terminate', { subscription_id: subscriptionId }), body, { signal });
}
