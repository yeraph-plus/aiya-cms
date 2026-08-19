import type { APIContext } from 'astro';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const userCenterMocks = vi.hoisted(() => ({
    createGuardedServerFetch: vi.fn(),
    verifySameOriginForm: vi.fn()
}));

vi.mock('@/lib/api/server/client', () => ({ createGuardedServerFetch: userCenterMocks.createGuardedServerFetch }));
vi.mock('@/lib/auth/server/csrf', () => ({ verifySameOriginForm: userCenterMocks.verifySameOriginForm }));

import { localizedEquivalent, routePolicy } from '@/lib/routing/routes';
import { fetchCurrentUser, submitIdentityForm } from '@/lib/user-center';

const context = { locals: { requestId: 'request-1' } } as unknown as APIContext;

describe('user center', () => {
    beforeEach(() => vi.clearAllMocks());

    it.each([
        ['/account', 'authenticated'],
        ['/account/points', 'authenticated'],
        ['/account/membership', 'authenticated'],
        ['/account/purchases', 'authenticated'],
        ['/account/gift-card', 'authenticated'],
        ['/account/downloads', 'authenticated']
    ])('protects %s with routePolicy', (path, policy) => {
        expect(routePolicy(path)).toBe(policy);
    });

    it('preserves account sections while changing locale', () => {
        expect(localizedEquivalent('/account/downloads', 'en')).toBe('/en/account/downloads');
        expect(localizedEquivalent('/en/account/points', 'zh-CN')).toBe('/account/points');
    });

    it.each([
        [401, 'unauthenticated'],
        [403, 'forbidden'],
        [503, 'unavailable'],
        [500, 'unavailable'],
        [422, 'invalid']
    ])('maps /me status %i to %s', async (status, kind) => {
        const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status }));
        expect(await fetchCurrentUser(context, fetcher)).toEqual({ kind });
        expect(fetcher).toHaveBeenCalledWith('/api/v1/me', { method: 'GET', cache: 'no-store' });
    });

    it('accepts only a shaped /me response and keeps real points', async () => {
        const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
            subject_id: 'subject-1',
            status: 'active',
            username: 'aiya',
            points: { balance: 42, opened: true, program_key: 'credit' }
        }));
        const state = await fetchCurrentUser(context, fetcher);
        expect(state).toMatchObject({ kind: 'ready', data: { points: { balance: 42 } } });
    });

    it('fails closed when /me cannot be reached or parsed', async () => {
        const rejected = vi.fn<typeof fetch>().mockRejectedValue(new Error('offline'));
        const malformed = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ status: 'active' }));
        expect(await fetchCurrentUser(context, rejected)).toEqual({ kind: 'unavailable' });
        expect(await fetchCurrentUser(context, malformed)).toEqual({ kind: 'invalid' });
    });

    it('checks same-origin CSRF before forwarding an identity form', async () => {
        const backendFetch = vi.fn<typeof fetch>();
        userCenterMocks.createGuardedServerFetch.mockReturnValue(backendFetch);
        userCenterMocks.verifySameOriginForm.mockRejectedValue(new Error('invalid CSRF'));
        const form = new FormData();
        form.set('csrf', 'bad-token');
        const actionContext = {
            ...context,
            request: new Request('https://site.example/verify-email', { method: 'POST' }),
            session: {}
        } as unknown as APIContext;

        await expect(submitIdentityForm(actionContext, form, '/api/v1/auth/verify-email', { token: 'secret-token' })).rejects.toThrow('invalid CSRF');
        expect(backendFetch).not.toHaveBeenCalled();
    });

    it('sends identity secrets only in a no-store JSON request body', async () => {
        const backendFetch = vi.fn<typeof fetch>().mockResolvedValue(Response.json({}, { status: 200 }));
        userCenterMocks.createGuardedServerFetch.mockReturnValue(backendFetch);
        userCenterMocks.verifySameOriginForm.mockResolvedValue(undefined);
        const form = new FormData();
        form.set('csrf', 'csrf-token');
        const actionContext = {
            ...context,
            request: new Request('https://site.example/password-reset/confirm', { method: 'POST' }),
            session: {}
        } as unknown as APIContext;

        const state = await submitIdentityForm(actionContext, form, '/api/v1/auth/password-reset/confirm', {
            token: 'secret-token',
            new_password: 'secret-password'
        });

        expect(state).toBe('success');
        expect(backendFetch).toHaveBeenCalledWith('/api/v1/auth/password-reset/confirm', expect.objectContaining({
            method: 'POST',
            cache: 'no-store',
            body: JSON.stringify({ token: 'secret-token', new_password: 'secret-password' })
        }));
        expect(backendFetch.mock.calls[0]?.[0]).not.toContain('secret');
    });
});
