import type { RouteRecordRaw } from 'vue-router';
import AppLayout from '@/layout/AppLayout.vue';

export const appRoutes: RouteRecordRaw[] = [
    {
        path: '/',
        component: AppLayout,
        children: [
            {
                path: 'dashboard',
                name: 'system-dashboard',
                component: () => import('@/pages/system/Dashboard.vue'),
                meta: { title: 'Dashboard', requiresAuth: true, requiredCapability: 'admin.dashboard.read', shell: 'app' }
            },
            {
                path: 'identity/users',
                name: 'identity-users',
                component: () => import('@/pages/identity/UsersList.vue'),
                meta: { title: 'Users', requiresAuth: true, requiredCapability: 'identity.users.read', shell: 'app' }
            },
            {
                path: 'content',
                name: 'content-list',
                component: () => import('@/pages/content/ContentList.vue'),
                meta: { title: 'Articles', requiresAuth: true, requiredCapability: 'content.read', shell: 'app' }
            },
            {
                path: 'content/new',
                name: 'content-new',
                component: () => import('@/pages/content/ContentEditor.vue'),
                meta: { title: 'New Content', requiresAuth: true, requiredCapability: 'content.write', shell: 'app' }
            },
            {
                path: 'content/:contentId([0-9a-fA-F-]{36})',
                name: 'content-editor',
                component: () => import('@/pages/content/ContentEditor.vue'),
                meta: { title: 'Edit Content', requiresAuth: true, requiredCapability: 'content.read', shell: 'app' }
            },
            {
                path: 'content/taxonomy',
                name: 'content-taxonomy',
                component: () => import('@/pages/content/Taxonomy.vue'),
                meta: { title: 'Taxonomy', requiresAuth: true, requiredCapability: 'taxonomy.read', shell: 'app' }
            },
            {
                path: 'system/settings',
                name: 'system-settings',
                component: () => import('@/pages/system/SettingsGroups.vue'),
                meta: { title: 'Settings', requiresAuth: true, requiredCapability: 'settings.read', shell: 'app' }
            },
            {
                path: 'system/audit',
                name: 'system-audit',
                component: () => import('@/pages/system/AuditLog.vue'),
                meta: { title: 'Audit Log', requiresAuth: true, requiredCapability: 'audit.read', shell: 'app' }
            },
            {
                path: 'system/execution',
                name: 'system-execution',
                component: () => import('@/pages/system/ExecutionLog.vue'),
                meta: { title: 'Execution Log', requiresAuth: true, requiredCapability: 'audit.read', shell: 'app' }
            },
            {
                path: 'system/assets',
                name: 'system-assets',
                component: () => import('@/pages/system/Assets.vue'),
                meta: { title: 'Assets', requiresAuth: true, requiredCapability: 'assets.read', shell: 'app' }
            }
        ]
    }
];
