import { describe, expect, it } from 'vitest';
import { WebStorageStateStore } from 'oidc-client-ts';
import { oidcSettings } from '@/auth/oidc';
import { oidcStateStorage, oidcUserStorage } from '@/auth/storage';

describe('oidc client settings', () => {
    it('uses authorization code with PKCE against the configured issuer', () => {
        expect(oidcSettings.response_type).toBe('code');
        expect(oidcSettings.authority).toMatch(/^https?:\/\//);
        expect(oidcSettings.client_id).toBe('admin');
    });

    it('never requests offline_access and disables silent renew', () => {
        expect(oidcSettings.scope).toBe('openid profile email');
        expect(oidcSettings.scope).not.toContain('offline_access');
        expect(oidcSettings.automaticSilentRenew).toBe(false);
        expect(oidcSettings.monitorSession).toBe(false);
        expect(oidcSettings.loadUserInfo).toBe(false);
    });

    it('keeps bearer tokens in a store that never touches web storage', () => {
        expect(oidcUserStorage).toBeInstanceOf(WebStorageStateStore);
        const inner = (oidcUserStorage as unknown as { _store: Storage })._store;
        expect(inner).not.toBe(window.sessionStorage);
        expect(inner).not.toBe(window.localStorage);
    });

    it('keeps one-time protocol material in session storage only', () => {
        expect(oidcStateStorage).toBeInstanceOf(WebStorageStateStore);
        const inner = (oidcStateStorage as unknown as { _store: Storage })._store;
        expect(inner).toBe(window.sessionStorage);
    });

    it('uses the exact registered callback paths', () => {
        expect(oidcSettings.redirect_uri.endsWith('/callback')).toBe(true);
        expect(oidcSettings.post_logout_redirect_uri?.endsWith('/logged-out')).toBe(true);
    });
});
