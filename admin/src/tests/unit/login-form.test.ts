import { describe, expect, it, vi } from 'vitest';

const createSigninRequestMock = vi.fn();

vi.mock('oidc-client-ts', () => ({
    OidcClient: class {
        settings: unknown;
        constructor(settings: unknown) {
            this.settings = settings;
        }
        async createSigninRequest() {
            return createSigninRequestMock();
        }
    },
    UserManager: class {
        settings: unknown;
        constructor(settings: unknown) {
            this.settings = settings;
        }
        async signoutRedirect() {
            return undefined;
        }
    },
    InMemoryWebStorage: class {
        private data = new Map<string, string>();
        get(key: string) {
            return this.data.get(key);
        }
        set(key: string, value: string) {
            this.data.set(key, value);
        }
        remove(key: string) {
            this.data.delete(key);
        }
        get length() {
            return this.data.size;
        }
        key(index: number) {
            return [...this.data.keys()][index] ?? null;
        }
        clear() {
            this.data.clear();
        }
    },
    WebStorageStateStore: class {
        constructor() {}
    }
}));

describe('createLoginFormArgs', () => {
    it('returns the OP login endpoint and authorize parameters as hidden fields', async () => {
        const { env } = await import('@/env');
        createSigninRequestMock.mockResolvedValue({
            url: `${env.oidcIssuer}/oidc/authorize?client_id=admin&redirect_uri=${encodeURIComponent(env.oidcRedirectUri)}&response_type=code&scope=openid%20profile%20email&state=state-1&nonce=nonce-1&code_challenge=challenge-1&code_challenge_method=S256`
        });

        const { createLoginFormArgs } = await import('@/auth/oidc');
        const args = await createLoginFormArgs();

        expect(args.action).toBe(`${env.oidcIssuer}/oidc/login`);
        expect(args.fields).toEqual({
            client_id: 'admin',
            redirect_uri: env.oidcRedirectUri,
            response_type: 'code',
            scope: 'openid profile email',
            state: 'state-1',
            nonce: 'nonce-1',
            code_challenge: 'challenge-1',
            code_challenge_method: 'S256'
        });
    });

    it('posts credentials without navigating and returns the frontend callback URL', async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ redirect_uri: 'http://127.0.0.1:5173/callback?code=code-1' })
        });
        vi.stubGlobal('fetch', fetchMock);

        const { submitLogin } = await import('@/auth/oidc');
        const redirectUri = await submitLogin(
            {
                action: 'http://127.0.0.1:8000/oidc/login',
                fields: { client_id: 'admin', state: 'state-1' }
            },
            'alice',
            'password'
        );

        expect(redirectUri).toBe('http://127.0.0.1:5173/callback?code=code-1');
        expect(fetchMock).toHaveBeenCalledWith(
            'http://127.0.0.1:8000/oidc/login',
            expect.objectContaining({
                method: 'POST',
                credentials: 'include',
                redirect: 'manual',
                headers: {
                    Accept: 'application/json',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            })
        );
        vi.unstubAllGlobals();
    });

    it('turns an OIDC JSON error into a frontend error', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue({
                ok: false,
                json: async () => ({ error: 'invalid_request', error_description: 'redirect uri is not registered' })
            })
        );

        const { submitLogin } = await import('@/auth/oidc');
        await expect(submitLogin({ action: 'http://127.0.0.1:8000/oidc/login', fields: {} }, 'alice', 'password')).rejects.toThrow('redirect uri is not registered');
        vi.unstubAllGlobals();
    });
});
