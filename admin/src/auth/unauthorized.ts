import router from '@/router';
import { sessionState } from './session';

let reauthPromise: Promise<void> | null = null;

export function handleUnauthorized(): void {
    if (reauthPromise !== null) return;

    reauthPromise = (async () => {
        sessionState.status = 'expired';
        sessionState.accessToken = null;
        sessionState.me = null;
        const current = router.currentRoute.value.fullPath;
        await router.push({ name: 'login', query: { redirect: current, reason: 'expired' } });
    })().finally(() => {
        reauthPromise = null;
    });
}
