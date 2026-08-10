import type { RouteRecordRaw } from 'vue-router';
import AppLayout from '@/layout/AppLayout.vue';

export const appRoutes: RouteRecordRaw[] = [
    {
        path: '/',
        component: AppLayout,
        children: [
            {
                path: '',
                name: 'dashboard',
                component: () => import('@/pages/dashboard/Dashboard.vue'),
                meta: { title: 'Dashboard', requiresAuth: true, shell: 'app' }
            }
        ]
    }
];
