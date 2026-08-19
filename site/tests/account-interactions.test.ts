import type { APIContext } from 'astro';
import { readFile } from 'node:fs/promises';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    createGuardedServerFetch: vi.fn(),
    verifySameOriginForm: vi.fn()
}));

vi.mock('@/lib/api/server/client', () => ({ createGuardedServerFetch: mocks.createGuardedServerFetch }));
vi.mock('@/lib/auth/server/csrf', () => ({ verifySameOriginForm: mocks.verifySameOriginForm }));

import { accountBff } from '@/lib/user-center/bff';

function context(path: string, request: Request): APIContext {
    return {
        params: { path },
        request,
        url: new URL(request.url),
        session: {},
        locals: { requestId: 'site-request-1' }
    } as unknown as APIContext;
}

describe('account interactions', () => {
    beforeEach(() => vi.clearAllMocks());

    it('requires same-origin CSRF before forwarding mutations', async () => {
        mocks.verifySameOriginForm.mockRejectedValue(new Error('Invalid CSRF token'));
        const backend = vi.fn<typeof fetch>();
        mocks.createGuardedServerFetch.mockReturnValue(backend);
        const request = new Request('https://site.example/api/account/check-ins', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'bad' },
            body: '{}'
        });

        const response = await accountBff(context('check-ins', request));

        expect(response.status).toBe(403);
        expect(response.headers.get('Cache-Control')).toBe('private, no-store');
        expect(backend).not.toHaveBeenCalled();
    });

    it('forwards generated point-order fields without accepting a client amount', async () => {
        mocks.verifySameOriginForm.mockResolvedValue(undefined);
        const backend = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ id: 'order-1', state: 'pending' }, {
            headers: { 'X-Request-ID': 'backend-request-1' }
        }));
        mocks.createGuardedServerFetch.mockReturnValue(backend);
        const request = new Request('https://site.example/api/account/points/orders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf', 'Idempotency-Key': 'idem-1' },
            body: JSON.stringify({ product_key: 'bundle.basic', provider_key: 'mock', amount: 1 })
        });

        const response = await accountBff(context('points/orders', request));

        expect(response.status).toBe(200);
        expect(response.headers.get('X-Request-ID')).toBe('backend-request-1');
        expect(backend).toHaveBeenCalledWith('/api/v1/me/points/orders', expect.objectContaining({
            method: 'POST',
            cache: 'no-store',
            body: JSON.stringify({ product_key: 'bundle.basic', provider_key: 'mock' })
        }));
        const headers = new Headers(backend.mock.calls[0]?.[1]?.headers);
        expect(headers.get('Idempotency-Key')).toBe('idem-1');
    });

    it('preserves backend error status, body, request id, and no-store policy', async () => {
        mocks.verifySameOriginForm.mockResolvedValue(undefined);
        mocks.createGuardedServerFetch.mockReturnValue(vi.fn<typeof fetch>().mockResolvedValue(Response.json({
            code: 'user_center.product_unavailable',
            message: 'offer is unavailable'
        }, { status: 409, headers: { 'X-Request-ID': 'backend-request-2' } })));
        const request = new Request('https://site.example/api/account/membership/orders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf' },
            body: JSON.stringify({ offer_key: 'membership.monthly', provider_key: 'mock', renewal: false })
        });

        const response = await accountBff(context('membership/orders', request));

        expect(response.status).toBe(409);
        expect(response.headers.get('Cache-Control')).toBe('private, no-store');
        expect(response.headers.get('X-Request-ID')).toBe('backend-request-2');
        expect(await response.json()).toEqual({ code: 'user_center.product_unavailable', message: 'offer is unavailable' });
    });

    it('keeps gift-card secrets out of URLs and browser persistence and clears the input before awaiting', async () => {
        const source = await readFile(new URL('../src/components/vue/AccountInteractions.vue', import.meta.url), 'utf8');
        expect(source).toContain("const submittedSecret = secret.value;\n    secret.value = '';\n    await send('gift-card', { secret: submittedSecret });");
        expect(source).not.toMatch(/localStorage|sessionStorage|URLSearchParams/u);
        expect(source).not.toContain('gift-card?');
    });

    it('polls payment state through a same-origin GET instead of trusting browser return state', async () => {
        const backend = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ order: { id: 'order-1', state: 'captured' } }));
        mocks.createGuardedServerFetch.mockReturnValue(backend);
        const request = new Request('https://site.example/api/account/payment-orders/order-1');

        const response = await accountBff(context('payment-orders/order-1', request));

        expect(response.status).toBe(200);
        expect(backend).toHaveBeenCalledWith('/api/v1/me/payment-orders/order-1', expect.objectContaining({ method: 'GET', cache: 'no-store' }));
    });
});
