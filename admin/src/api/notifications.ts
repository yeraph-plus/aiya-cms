import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type NotificationDeliveryDTO = components['schemas']['NotificationDeliveryDTO'];
export type NotificationDeliveryRecordDTO = components['schemas']['NotificationDeliveryRecordDTO'];
export type NotificationDeliveryPageDTO = components['schemas']['NotificationDeliveryPageDTO'];
export type NotificationDeliveryDetailDTO = components['schemas']['NotificationDeliveryDetailDTO'];
export type NotificationDeliveryQuery = NonNullable<paths['/api/v1/admin/notifications/deliveries']['get']['parameters']['query']>;

export async function fetchNotificationDeliveries(query?: NotificationDeliveryQuery, signal?: AbortSignal): Promise<NotificationDeliveryPageDTO> {
    return getApi().get('/api/v1/admin/notifications/deliveries', query, signal);
}

export async function fetchNotificationDelivery(deliveryId: string, signal?: AbortSignal): Promise<NotificationDeliveryDetailDTO> {
    return getApi().get(apiPath('/api/v1/admin/notifications/deliveries/{delivery_id}', { delivery_id: deliveryId }), undefined, signal);
}

export async function cancelNotificationDelivery(deliveryId: string, signal?: AbortSignal): Promise<NotificationDeliveryDTO> {
    return getApi().post(apiPath('/api/v1/admin/notifications/deliveries/{delivery_id}/cancel', { delivery_id: deliveryId }), undefined, { signal });
}

export async function retryNotificationDelivery(deliveryId: string, signal?: AbortSignal): Promise<NotificationDeliveryDTO> {
    return getApi().post(apiPath('/api/v1/admin/notifications/deliveries/{delivery_id}/retry', { delivery_id: deliveryId }), undefined, { signal });
}
