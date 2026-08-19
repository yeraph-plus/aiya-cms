import type { APIContext } from 'astro';

import { createGuardedServerFetch } from '@/lib/api/server/client';
import { verifySameOriginForm } from '@/lib/auth/server/csrf';
import type { CancelMembershipInput, GiftCardRedemptionInput, MembershipOrderInput, PointOrderInput } from '@/lib/user-center';

interface Target {
    method: 'GET' | 'POST';
    path: string;
    body?: CancelMembershipInput | GiftCardRedemptionInput | MembershipOrderInput | PointOrderInput;
}

function text(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

function targetFor(parts: string[], method: string, body: Record<string, unknown>, search: string): Target | null {
    if (method === 'POST' && parts.join('/') === 'check-ins') return { method: 'POST', path: '/api/v1/me/check-ins' };
    if (method === 'POST' && parts.join('/') === 'points/orders') return { method: 'POST', path: '/api/v1/me/points/orders', body: { product_key: text(body.product_key), provider_key: text(body.provider_key) } };
    if (method === 'POST' && parts.join('/') === 'membership/orders') return { method: 'POST', path: '/api/v1/me/membership/orders', body: { offer_key: text(body.offer_key), provider_key: text(body.provider_key), renewal: body.renewal === true || body.renewal === 'true' } };
    if (method === 'POST' && parts.join('/') === 'membership/cancel') return { method: 'POST', path: '/api/v1/me/membership/cancel', body: { reason: text(body.reason) } };
    if (method === 'POST' && parts.join('/') === 'gift-card') return { method: 'POST', path: '/api/v1/me/gift-cards/redemptions', body: { secret: text(body.secret), ...(text(body.platform_key) ? { platform_key: text(body.platform_key) } : {}) } };
    if (method === 'POST' && parts.length === 3 && parts[0] === 'downloads' && parts[2] === 'links') return { method: 'POST', path: `/api/v1/me/downloads/${encodeURIComponent(parts[1] ?? '')}/links` };
    if (method === 'GET' && parts.length === 2 && parts[0] === 'payment-orders') return { method: 'GET', path: `/api/v1/me/payment-orders/${encodeURIComponent(parts[1] ?? '')}${search}` };
    return null;
}

async function requestBody(request: Request): Promise<{ body: Record<string, unknown>; csrf: string | null }> {
    const contentType = request.headers.get('content-type') ?? '';
    if (contentType.includes('application/json')) {
        return { body: await request.json() as Record<string, unknown>, csrf: request.headers.get('X-CSRF-Token') };
    }
    const form = await request.formData();
    const body: Record<string, unknown> = {};
    for (const [key, value] of form.entries()) if (typeof value === 'string' && key !== 'csrf') body[key] = value;
    return { body, csrf: typeof form.get('csrf') === 'string' ? String(form.get('csrf')) : null };
}

export async function accountBff(context: APIContext): Promise<Response> {
    const headers = new Headers({ 'Cache-Control': 'private, no-store' });
    if (!context.session) return Response.json({ message: 'Authentication required' }, { status: 401, headers });
    const parts = context.params.path?.split('/').filter(Boolean) ?? [];
    const parsed = context.request.method === 'POST' ? await requestBody(context.request) : { body: {}, csrf: null };
    const target = targetFor(parts, context.request.method, parsed.body, context.url.search);
    if (!target) return Response.json({ message: 'Not found' }, { status: 404, headers });
    if (target.method === 'POST') {
        try {
            await verifySameOriginForm(context.request, context.session, parsed.csrf);
        } catch (error) {
            return Response.json({ message: error instanceof Error ? error.message : 'Invalid CSRF token' }, { status: 403, headers });
        }
    }
    const outgoingHeaders = new Headers({ Accept: 'application/json' });
    if (target.method === 'POST') {
        outgoingHeaders.set('Idempotency-Key', context.request.headers.get('Idempotency-Key') ?? crypto.randomUUID());
        if (target.body) outgoingHeaders.set('Content-Type', 'application/json');
    }
    const response = await createGuardedServerFetch(context.session, context.locals.requestId)(target.path, {
        method: target.method,
        cache: 'no-store',
        headers: outgoingHeaders,
        ...(target.body ? { body: JSON.stringify(target.body) } : {})
    });
    const contentType = response.headers.get('content-type') ?? 'application/json';
    headers.set('Content-Type', contentType);
    const requestId = response.headers.get('X-Request-ID') ?? response.headers.get('x-request-id');
    if (requestId) headers.set('X-Request-ID', requestId);
    return new Response(await response.arrayBuffer(), { status: response.status, headers });
}
