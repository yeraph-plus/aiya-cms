import { afterEach, describe, expect, it } from 'vitest';

import { loadServerConfig } from '@/lib/config/server';

const originalEnvironment = { ...process.env };

afterEach(() => {
    process.env = { ...originalEnvironment };
});

describe('server configuration', () => {
    it('derives exact OIDC callbacks from the site origin', () => {
        process.env.SITE_ENVIRONMENT = 'test';
        process.env.SITE_ORIGIN = 'http://127.0.0.1:4321';
        process.env.SITE_OIDC_CLIENT_SECRET = 'test-secret-with-more-than-thirty-two-characters';

        const config = loadServerConfig();

        expect(config.oidcRedirectUri).toBe('http://127.0.0.1:4321/auth/callback');
        expect(config.oidcPostLogoutRedirectUri).toBe('http://127.0.0.1:4321/auth/logged-out');
    });

    it('rejects HTTP origins in production', () => {
        process.env.SITE_ENVIRONMENT = 'production';
        process.env.SITE_ORIGIN = 'http://site.example.test';
        process.env.SITE_API_ORIGIN = 'https://api.example.test';
        process.env.SITE_OIDC_ISSUER = 'https://api.example.test';
        process.env.SITE_OIDC_CLIENT_SECRET = 'production-secret-with-more-than-thirty-two-characters';

        expect(() => loadServerConfig()).toThrow('SITE_ORIGIN must use HTTPS in production');
    });
});
