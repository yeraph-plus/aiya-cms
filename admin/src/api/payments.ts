import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type OrderDTO = components['schemas']['OrderDTO'];
export type OrderPageDTO = components['schemas']['OrderPageDTO'];
export type OrderDetailDTO = components['schemas']['OrderDetailDTO'];
export type RequestRefundInput = components['schemas']['RequestRefundInput'];
export type RefundDTO = components['schemas']['RefundDTO'];
export type PaymentOrderQuery = NonNullable<paths['/api/v1/admin/payments/orders']['get']['parameters']['query']>;

export async function fetchPaymentOrders(query?: PaymentOrderQuery, signal?: AbortSignal): Promise<OrderPageDTO> {
    return getApi().get('/api/v1/admin/payments/orders', query, signal);
}

export async function fetchPaymentOrder(orderId: string, signal?: AbortSignal): Promise<OrderDetailDTO> {
    return getApi().get(apiPath('/api/v1/admin/payments/orders/{order_id}', { order_id: orderId }), undefined, signal);
}

export async function cancelPaymentOrder(orderId: string, signal?: AbortSignal): Promise<OrderDTO> {
    return getApi().post(apiPath('/api/v1/admin/payments/orders/{order_id}/cancel', { order_id: orderId }), undefined, { signal });
}

export async function reconcilePaymentOrder(orderId: string, signal?: AbortSignal): Promise<OrderDTO> {
    return getApi().post(apiPath('/api/v1/admin/payments/orders/{order_id}/reconcile', { order_id: orderId }), undefined, { signal });
}

export async function refundPaymentOrder(orderId: string, body: RequestRefundInput, signal?: AbortSignal): Promise<RefundDTO> {
    return getApi().post(apiPath('/api/v1/admin/payments/orders/{order_id}/refund', { order_id: orderId }), body, { signal });
}
