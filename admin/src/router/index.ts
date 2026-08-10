import { createRouter, createWebHistory } from 'vue-router';
import { publicRoutes } from './public-routes';
import { appRoutes } from './app-routes';
import { demoRoutes } from '@/demo/routes';
import { hasCapability, initializeSession, isAuthenticated, sessionState } from '@/auth/session';
import { APP_NAME } from '@/env';

const routes = [...publicRoutes, ...appRoutes];

if (import.meta.env.DEV) {
    routes.push(...demoRoutes);
}

const router = createRouter({
    history: createWebHistory(),
    routes
});

const devAuthBypass = import.meta.env.DEV && import.meta.env.VITE_DEV_AUTH === '1';

router.beforeEach(async (to) => {
    if (sessionState.status === 'loading') {
        await initializeSession();
    }

    const requiresAuth = to.meta.requiresAuth !== false;

    if (requiresAuth && sessionState.status !== 'authenticated' && !devAuthBypass) {
        return { name: 'login', query: { redirect: to.fullPath } };
    }

    if (to.name === 'login' && isAuthenticated.value && !devAuthBypass) {
        return { name: 'dashboard' };
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
