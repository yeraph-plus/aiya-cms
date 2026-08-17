import { createRouter, createWebHistory } from 'vue-router';
import { publicRoutes } from './public-routes';
import { appRoutes } from './app-routes';
import { hasCapability, initializeSession, isAuthenticated, sessionState } from '@/auth/session';
import { APP_NAME } from '@/env';
import { i18n, translate } from '@/i18n';
import { watch } from 'vue';

const routes = [...publicRoutes, ...appRoutes];

const router = createRouter({
    history: createWebHistory(),
    routes
});

const devAuthBypass = import.meta.env.DEV && import.meta.env.VITE_DEV_AUTH === '1';

function authenticatedHome(): string {
    for (const name of ['dashboard', 'users', 'content-articles', 'user-permissions', 'user-points', 'user-membership', 'settings', 'system-audit', 'system-assets', 'system-operations', 'system-oidc']) {
        const requiredCapability = router.resolve({ name }).meta.requiredCapability;
        if (typeof requiredCapability !== 'string' || hasCapability(requiredCapability)) return name;
    }
    return 'accessDenied';
}

router.beforeEach(async (to) => {
    const isAuthCallback = to.name === 'auth-callback';
    const hasAuthorizationCode = typeof to.query.code === 'string' && to.query.code.length > 0;
    const isAuthCompletion = to.name === 'login' || isAuthCallback;

    // The callback component must consume the one-time authorization code
    // before any cookie-first session probe.  Probing here can issue an
    // anonymous 401 and race signinRedirectCallback on a fresh page load.
    if (!(isAuthCallback && hasAuthorizationCode) && (sessionState.status === 'loading' || sessionState.status === 'error')) {
        await initializeSession();
    }

    const requiresAuth = to.meta.requiresAuth !== false;

    if (requiresAuth && sessionState.status !== 'authenticated' && !devAuthBypass) {
        return { name: 'login', query: { redirect: to.fullPath } };
    }

    if (isAuthCompletion && isAuthenticated.value && !devAuthBypass) {
        return { name: authenticatedHome() };
    }

    if (to.meta.requiredCapability && !hasCapability(to.meta.requiredCapability) && !devAuthBypass) {
        return { name: 'accessDenied' };
    }

    document.title = `${translate(to.meta.titleKey)} · ${APP_NAME}`;

    return true;
});

router.afterEach((to) => {
    document.title = to.meta.titleKey ? `${translate(to.meta.titleKey)} · ${APP_NAME}` : APP_NAME;
});

watch(i18n.global.locale, () => {
    const titleKey = router.currentRoute.value.meta.titleKey;
    document.title = titleKey ? `${translate(titleKey)} · ${APP_NAME}` : APP_NAME;
});

export default router;
