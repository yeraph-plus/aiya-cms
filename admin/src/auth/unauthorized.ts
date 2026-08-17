import router from '@/router';
import { sessionState } from './session';

let reauthPromise: Promise<void> | null = null;

export function handleUnauthorized(): void {
    // A cookie-first session bootstrap intentionally probes /admin/session
    // before an OIDC user exists.  Treat that expected anonymous 401 as a
    // normal login state; only an authenticated/bearer session should trigger
    // the global expiry redirect.  Otherwise the redirect races the OIDC
    // callback and can prevent the code exchange from completing.
    if ((sessionState.status === 'loading' || sessionState.status === 'anonymous') && !sessionState.accessToken) return;
    if (reauthPromise !== null) return;

    reauthPromise = (async () => {
        sessionState.status = 'expired';
        sessionState.accessToken = null;
        sessionState.me = null;
        const current = router.currentRoute.value.fullPath;
        await router.push({
            name: 'login',
            query: { redirect: current, reason: 'expired' }
        });
    })().finally(() => {
        reauthPromise = null;
    });
}
