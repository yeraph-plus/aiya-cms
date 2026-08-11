import { createRouter, createWebHistory } from 'vue-router';
import { publicRoutes } from './public-routes';
import { appRoutes } from './app-routes';
import { hasCapability, initializeSession, isAuthenticated, sessionState } from '@/auth/session';
import { APP_NAME } from '@/env';

const routes = [...publicRoutes, ...appRoutes];

const router = createRouter({
    history: createWebHistory(),
    routes
});

const devAuthBypass = import.meta.env.DEV && import.meta.env.VITE_DEV_AUTH === '1';

function authenticatedHome(): string {
    for (const name of ['system-dashboard', 'identity-users', 'content-list', 'system-settings', 'system-audit', 'system-assets', 'system-execution']) {
        const requiredCapability = router.resolve({ name }).meta.requiredCapability;
        if (typeof requiredCapability !== 'string' || hasCapability(requiredCapability)) return name;
    }
    return 'accessDenied';
}

router.beforeEach(async (to) => {
    if (sessionState.status === 'loading' || sessionState.status === 'error') {
        await initializeSession();
    }

    const requiresAuth = to.meta.requiresAuth !== false;

    if (requiresAuth && sessionState.status !== 'authenticated' && !devAuthBypass) {
        return { name: 'login', query: { redirect: to.fullPath } };
    }

    const isAuthCompletion = to.name === 'login' || to.name === 'auth-callback';
    if (isAuthCompletion && isAuthenticated.value && !devAuthBypass) {
        return { name: authenticatedHome() };
    }

    if (to.meta.requiredCapability && !hasCapability(to.meta.requiredCapability) && !devAuthBypass) {
        return { name: 'accessDenied' };
    }

    if (to.meta.title) {
        document.title = `${to.meta.title} · ${APP_NAME}`;
    }

    return true;
});

router.afterEach((to) => {
    if (!to.meta.title) {
        document.title = APP_NAME;
    }
});

export default router;
