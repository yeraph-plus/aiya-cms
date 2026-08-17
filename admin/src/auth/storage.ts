import { InMemoryWebStorage, WebStorageStateStore } from 'oidc-client-ts';

export const oidcUserStorage = new WebStorageStateStore({
    store: new InMemoryWebStorage()
});

export const oidcStateStorage = new WebStorageStateStore({
    store: window.sessionStorage
});

const PENDING_REDIRECT_KEY = 'aiya.pendingRedirect';

export function isSafeRedirectPath(target: string | null | undefined): target is string {
    return typeof target === 'string' && target.startsWith('/') && !target.startsWith('//') && !target.startsWith('/\\');
}

export function storePendingRedirect(target: string | null | undefined): void {
    if (isSafeRedirectPath(target)) {
        window.sessionStorage.setItem(PENDING_REDIRECT_KEY, target);
    } else {
        window.sessionStorage.removeItem(PENDING_REDIRECT_KEY);
    }
}

export function takePendingRedirect(): string | null {
    const stored = window.sessionStorage.getItem(PENDING_REDIRECT_KEY);
    window.sessionStorage.removeItem(PENDING_REDIRECT_KEY);
    return stored;
}
