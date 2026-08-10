import type { RouteRecordRaw } from 'vue-router';

export const publicRoutes: RouteRecordRaw[] = [
    {
        path: '/auth/login',
        name: 'login',
        component: () => import('@/pages/auth/Login.vue'),
        meta: { title: 'Sign In', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/callback',
        name: 'auth-callback',
        component: () => import('@/pages/auth/Callback.vue'),
        meta: { title: 'Signing In', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/logged-out',
        redirect: { name: 'login' },
        meta: { title: 'Signed Out', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/auth/access-denied',
        name: 'accessDenied',
        component: () => import('@/pages/auth/AccessDenied.vue'),
        meta: { title: 'Access Denied', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/auth/error',
        name: 'error',
        component: () => import('@/pages/auth/Error.vue'),
        meta: { title: 'Error', requiresAuth: false, shell: 'auth' }
    },
    {
        path: '/:pathMatch(.*)*',
        name: 'notfound',
        component: () => import('@/pages/NotFound.vue'),
        meta: { title: 'Not Found', requiresAuth: false, shell: 'auth' }
    }
];
