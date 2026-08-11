import type { RouteRecordRaw } from 'vue-router';

export const publicRoutes: RouteRecordRaw[] = [
    {
        path: '/auth/login',
        name: 'login',
        component: () => import('@/pages/auth/Login.vue'),
        meta: { titleKey: 'routes.auth.login', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/auth/register',
        name: 'register',
        component: () => import('@/pages/auth/Register.vue'),
        meta: { titleKey: 'routes.auth.register', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/auth/verify-email',
        name: 'verify-email',
        component: () => import('@/pages/auth/VerifyEmail.vue'),
        meta: { titleKey: 'routes.auth.verifyEmail', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/auth/password-reset',
        name: 'password-reset',
        component: () => import('@/pages/auth/PasswordResetRequest.vue'),
        meta: { titleKey: 'routes.auth.passwordReset', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/auth/password-reset/confirm',
        name: 'password-reset-confirm',
        component: () => import('@/pages/auth/PasswordResetConfirm.vue'),
        meta: { titleKey: 'routes.auth.passwordResetConfirm', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/callback',
        name: 'auth-callback',
        component: () => import('@/pages/auth/Callback.vue'),
        meta: { titleKey: 'routes.auth.callback', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/logged-out',
        redirect: { name: 'login' },
        meta: { titleKey: 'routes.auth.loggedOut', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/auth/access-denied',
        name: 'accessDenied',
        component: () => import('@/pages/auth/AccessDenied.vue'),
        meta: { titleKey: 'routes.auth.accessDenied', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/auth/error',
        name: 'error',
        component: () => import('@/pages/auth/Error.vue'),
        meta: { titleKey: 'routes.auth.error', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/:pathMatch(.*)*',
        name: 'notfound',
        component: () => import('@/pages/NotFound.vue'),
        meta: { titleKey: 'routes.auth.notFound', requiresAuth: false, shell: 'auth' }
    }
];
