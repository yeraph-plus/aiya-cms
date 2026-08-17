import type { APIContext } from 'astro';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const oidcMocks = vi.hoisted(() => ({
    authorizationCodeGrant: vi.fn(),
    buildAuthorizationUrl: vi.fn(),
    calculatePKCECodeChallenge: vi.fn(),
    clientSecretBasic: vi.fn(),
    discovery: vi.fn(),
    randomNonce: vi.fn(),
    randomPkceCodeVerifier: vi.fn(),
    randomState: vi.fn()
}));

vi.mock('openid-client', () => ({
    ClientSecretBasic: oidcMocks.clientSecretBasic,
    allowInsecureRequests: vi.fn(),
    authorizationCodeGrant: oidcMocks.authorizationCodeGrant,
    buildAuthorizationUrl: oidcMocks.buildAuthorizationUrl,
    buildEndSessionUrl: vi.fn(),
    calculatePKCECodeChallenge: oidcMocks.calculatePKCECodeChallenge,
    discovery: oidcMocks.discovery,
    randomNonce: oidcMocks.randomNonce,
    randomPKCECodeVerifier: oidcMocks.randomPkceCodeVerifier,
    randomState: oidcMocks.randomState,
    refreshTokenGrant: vi.fn(),
    tokenRevocation: vi.fn()
}));

import { beginAuthorization, completeAuthorization } from '@/lib/auth/server/oidc';
import type { OidcTransaction } from '@/lib/auth/session';

type SiteSession = NonNullable<APIContext['session']>;

function fakeSession() {
    const values = new Map<string, unknown>();
    const session = {
        delete: vi.fn((key: string) => values.delete(key)),
        destroy: vi.fn(),
        get: vi.fn(async (key: string) => values.get(key)),
        regenerate: vi.fn(async () => undefined),
        set: vi.fn((key: string, value: unknown) => values.set(key, value))
    };
    return { session: session as unknown as SiteSession, values, spies: session };
}

const originalEnvironment = { ...process.env };

beforeEach(() => {
    process.env.SITE_ENVIRONMENT = 'test';
    process.env.SITE_ORIGIN = 'http://127.0.0.1:4321';
    process.env.SITE_API_ORIGIN = 'http://127.0.0.1:8000';
    process.env.SITE_OIDC_ISSUER = 'http://127.0.0.1:8000';
    process.env.SITE_OIDC_CLIENT_ID = 'aiya-site';
    process.env.SITE_OIDC_CLIENT_SECRET = 'test-secret-with-more-than-thirty-two-characters';
    oidcMocks.clientSecretBasic.mockReset();
    oidcMocks.discovery.mockReset();
    oidcMocks.randomPkceCodeVerifier.mockReset();
    oidcMocks.randomState.mockReset();
    oidcMocks.randomNonce.mockReset();
    oidcMocks.calculatePKCECodeChallenge.mockReset();
    oidcMocks.buildAuthorizationUrl.mockReset();
    oidcMocks.authorizationCodeGrant.mockReset();
    oidcMocks.clientSecretBasic.mockReturnValue(vi.fn());
    oidcMocks.discovery.mockResolvedValue({});
    oidcMocks.randomPkceCodeVerifier.mockReturnValue('pkce-verifier');
    oidcMocks.randomState.mockReturnValueOnce('state-value').mockReturnValueOnce('csrf-value');
    oidcMocks.randomNonce.mockReturnValue('nonce-value');
    oidcMocks.calculatePKCECodeChallenge.mockResolvedValue('pkce-challenge');
    oidcMocks.buildAuthorizationUrl.mockReturnValue(new URL('http://127.0.0.1:8000/oidc/authorize'));
});

afterEach(() => {
    process.env = { ...originalEnvironment };
    vi.clearAllMocks();
});

describe('OIDC BFF flow', () => {
    it('stores PKCE transaction state and uses confidential HTTP Basic auth', async () => {
        const { session, values, spies } = fakeSession();

        const redirect = await beginAuthorization(session, '/en/account', 'en');

        expect(redirect.pathname).toBe('/oidc/authorize');
        expect(spies.regenerate).toHaveBeenCalledOnce();
        expect(values.get('oidcTransaction')).toMatchObject({
            codeVerifier: 'pkce-verifier',
            state: 'state-value',
            nonce: 'nonce-value',
            returnTo: '/en/account',
            locale: 'en'
        });
        expect(oidcMocks.clientSecretBasic).toHaveBeenCalledWith('test-secret-with-more-than-thirty-two-characters');
        expect(oidcMocks.buildAuthorizationUrl).toHaveBeenCalledWith(
            expect.anything(),
            expect.objectContaining({
                code_challenge: 'pkce-challenge',
                code_challenge_method: 'S256',
                state: 'state-value',
                nonce: 'nonce-value',
                ui_locales: 'en'
            })
        );
    });

    it('validates the callback, rotates the session and retains tokens only server-side', async () => {
        const { session, values, spies } = fakeSession();
        values.set('oidcTransaction', {
            codeVerifier: 'pkce-verifier',
            state: 'state-value',
            nonce: 'nonce-value',
            returnTo: '/account',
            locale: 'zh-CN',
            createdAt: Date.now()
        } satisfies OidcTransaction);
        oidcMocks.authorizationCodeGrant.mockResolvedValue({
            access_token: 'server-access-token',
            refresh_token: 'server-refresh-token',
            id_token: 'server-id-token',
            expires_in: 300,
            claims: () => ({ sub: 'subject-1', name: 'Aiya' })
        });
        oidcMocks.randomState.mockReset().mockReturnValue('csrf-value');

        const returnTo = await completeAuthorization(
            session,
            new URL('http://127.0.0.1:4321/auth/callback?code=code&state=state-value')
        );

        expect(returnTo).toBe('/account');
        expect(spies.regenerate).toHaveBeenCalledOnce();
        expect(values.has('oidcTransaction')).toBe(false);
        expect(values.get('auth')).toMatchObject({
            subject: 'subject-1',
            accessToken: 'server-access-token',
            refreshToken: 'server-refresh-token'
        });
        expect(values.get('csrfToken')).toBe('csrf-value');
    });
});
