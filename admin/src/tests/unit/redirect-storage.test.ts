import { beforeEach, describe, expect, it } from 'vitest';
import { isSafeRedirectPath, storePendingRedirect, takePendingRedirect } from '@/auth/storage';

describe('pending redirect storage', () => {
    beforeEach(() => {
        window.sessionStorage.clear();
    });

    it('stores and takes back a same-origin path exactly once', () => {
        storePendingRedirect('/identity/users?page=2');
        expect(takePendingRedirect()).toBe('/identity/users?page=2');
        expect(takePendingRedirect()).toBeNull();
    });

    it('rejects protocol-relative and scheme URLs', () => {
        storePendingRedirect('//evil.example/phish');
        storePendingRedirect('https://evil.example/phish');
        expect(takePendingRedirect()).toBeNull();
    });

    it('clears a stale pending redirect when login starts without one', () => {
        storePendingRedirect('/content');
        storePendingRedirect(null);
        expect(takePendingRedirect()).toBeNull();
    });

    it('validates candidate paths', () => {
        expect(isSafeRedirectPath('/content')).toBe(true);
        expect(isSafeRedirectPath('//evil.example')).toBe(false);
        expect(isSafeRedirectPath('/\\evil.example')).toBe(false);
        expect(isSafeRedirectPath('https://evil.example')).toBe(false);
        expect(isSafeRedirectPath(null)).toBe(false);
        expect(isSafeRedirectPath(undefined)).toBe(false);
    });
});
