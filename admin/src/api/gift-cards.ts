import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type GiftCardBatchDTO = components['schemas']['GiftCardBatchDTO'];
export type GiftCardBatchResultDTO = components['schemas']['GiftCardBatchResultDTO'];
export type GiftCardDTO = components['schemas']['GiftCardDTO'];
export type GiftCardVerifyDTO = components['schemas']['GiftCardVerifyDTO'];
export type RedemptionDTO = components['schemas']['RedemptionDTO'];
export type BatchPageDTO = components['schemas']['Page_GiftCardBatchDTO_'];
export type CardPageDTO = components['schemas']['Page_GiftCardDTO_'];
export type GenerateGiftCardBatchInput = components['schemas']['GenerateGiftCardBatchInput'];
export type VerifyGiftCardInput = components['schemas']['VerifyGiftCardInput'];
export type ReserveGiftCardRedemptionInput = components['schemas']['ReserveGiftCardRedemptionInput'];
export type CommitGiftCardRedemptionInput = components['schemas']['CommitGiftCardRedemptionInput'];
export type CancelGiftCardRedemptionInput = components['schemas']['CancelGiftCardRedemptionInput'];
export type ProviderPurchaseInput = components['schemas']['ProviderPurchaseInput'];
export type GiftCardBatchQuery = NonNullable<paths['/api/v1/admin/gift-cards/batches']['get']['parameters']['query']>;

export async function fetchGiftCardBatches(query?: GiftCardBatchQuery, signal?: AbortSignal): Promise<BatchPageDTO> {
    return getApi().get('/api/v1/admin/gift-cards/batches', query, signal);
}

export async function generateGiftCardBatch(body: GenerateGiftCardBatchInput, signal?: AbortSignal): Promise<GiftCardBatchResultDTO> {
    return getApi().post('/api/v1/admin/gift-cards/batches', body, { signal });
}

export async function closeGiftCardBatch(batchId: string, reason: string, signal?: AbortSignal): Promise<GiftCardBatchDTO> {
    return getApi().post(apiPath('/api/v1/admin/gift-cards/batches/{batch_id}/close', { batch_id: batchId }), { batch_id: batchId, reason }, { signal });
}

export async function fetchGiftCards(batchId: string, query?: { page?: number; size?: number }, signal?: AbortSignal): Promise<CardPageDTO> {
    return getApi().get(apiPath('/api/v1/admin/gift-cards/batches/{batch_id}/cards', { batch_id: batchId }), query, signal);
}

export async function revokeGiftCard(cardId: string, reason: string, expectedVersion: number, signal?: AbortSignal): Promise<GiftCardDTO> {
    return getApi().post(apiPath('/api/v1/admin/gift-cards/{card_id}/revoke', { card_id: cardId }), { card_id: cardId, reason, expected_version: expectedVersion }, { signal });
}

export async function verifyGiftCard(body: VerifyGiftCardInput, signal?: AbortSignal): Promise<GiftCardVerifyDTO> {
    return getApi().post('/api/v1/admin/gift-cards/verify', body, { signal });
}

export async function reserveGiftCardRedemption(body: ReserveGiftCardRedemptionInput, signal?: AbortSignal): Promise<RedemptionDTO> {
    return getApi().post('/api/v1/admin/gift-cards/redemptions/reserve', body, { signal });
}

export async function fetchGiftCardRedemption(redemptionId: string, signal?: AbortSignal): Promise<RedemptionDTO> {
    return getApi().get(apiPath('/api/v1/admin/gift-cards/redemptions/{redemption_id}', { redemption_id: redemptionId }), undefined, signal);
}

export async function commitGiftCardRedemption(redemptionId: string, body: CommitGiftCardRedemptionInput, signal?: AbortSignal): Promise<RedemptionDTO> {
    return getApi().post(apiPath('/api/v1/admin/gift-cards/redemptions/{redemption_id}/commit', { redemption_id: redemptionId }), body, { signal });
}

export async function cancelGiftCardRedemption(redemptionId: string, body: CancelGiftCardRedemptionInput, signal?: AbortSignal): Promise<RedemptionDTO> {
    return getApi().post(apiPath('/api/v1/admin/gift-cards/redemptions/{redemption_id}/cancel', { redemption_id: redemptionId }), body, { signal });
}

export async function recordGiftCardProviderFact(body: ProviderPurchaseInput, signal?: AbortSignal): Promise<Record<string, unknown>> {
    return getApi().post('/api/v1/admin/gift-cards/provider-facts', body, { signal });
}
