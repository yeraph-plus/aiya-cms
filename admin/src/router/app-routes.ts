import type { RouteRecordRaw } from 'vue-router';
import AppLayout from '@/layout/AppLayout.vue';

export const appRoutes: RouteRecordRaw[] = [
    {
        path: '/',
        component: AppLayout,
        children: [
            {
                path: 'dashboard',
                name: 'dashboard',
                component: () => import('@/pages/system/Dashboard.vue'),
                meta: { titleKey: 'routes.dashboard', requiresAuth: true, requiredCapability: 'admin.dashboard.read', shell: 'app' }
            },
            {
                path: 'users',
                name: 'users',
                component: () => import('@/pages/identity/UsersList.vue'),
                meta: { titleKey: 'routes.users.list', requiresAuth: true, requiredCapability: 'identity.users.read', shell: 'app' }
            },
            {
                path: 'users/permissions',
                name: 'user-permissions',
                component: () => import('@/pages/identity/Permissions.vue'),
                meta: { titleKey: 'routes.users.permissions', requiresAuth: true, requiredCapability: 'access.roles.read', shell: 'app' }
            },
            {
                path: 'users/points',
                name: 'user-points',
                component: () => import('@/pages/identity/PointsSystem.vue'),
                meta: { titleKey: 'routes.users.points', requiresAuth: true, requiredCapability: 'points.read', shell: 'app' }
            },
            {
                path: 'users/membership',
                name: 'user-membership',
                component: () => import('@/pages/identity/MembershipSystem.vue'),
                meta: { titleKey: 'routes.users.membership', requiresAuth: true, requiredCapability: 'membership.read', shell: 'app' }
            },
            {
                path: 'users/payments',
                name: 'user-payments',
                component: () => import('@/pages/identity/Payments.vue'),
                meta: { titleKey: 'routes.users.payments', requiresAuth: true, requiredCapability: 'payments.read', shell: 'app' }
            },
            {
                path: 'content/articles',
                name: 'content-articles',
                component: () => import('@/pages/content/ContentList.vue'),
                meta: { titleKey: 'routes.content.articles', requiresAuth: true, requiredCapability: 'content.read', shell: 'app' }
            },
            {
                path: 'content/write',
                name: 'content-write',
                component: () => import('@/pages/content/ContentEditor.vue'),
                meta: { titleKey: 'routes.content.write', requiresAuth: true, requiredCapability: 'content.write', shell: 'app' }
            },
            {
                path: 'content/taxonomies',
                name: 'content-taxonomies',
                component: () => import('@/pages/content/Taxonomy.vue'),
                meta: { titleKey: 'routes.content.taxonomies', requiresAuth: true, requiredCapability: 'taxonomy.read', shell: 'app' }
            },
            {
                path: 'content/comments',
                name: 'content-comments',
                component: () => import('@/pages/content/Comments.vue'),
                meta: { titleKey: 'routes.content.comments', requiresAuth: true, requiredCapability: 'comments.read', shell: 'app' }
            },
            {
                path: 'settings',
                name: 'settings',
                component: () => import('@/pages/system/SettingsGroups.vue'),
                meta: { titleKey: 'routes.settings', requiresAuth: true, requiredCapability: 'settings.read', shell: 'app' }
            },
            {
                path: 'system/audit',
                name: 'system-audit',
                component: () => import('@/pages/system/AuditLog.vue'),
                meta: { titleKey: 'routes.system.audit', requiresAuth: true, requiredCapability: 'audit.read', shell: 'app' }
            },
            {
                path: 'system/operations',
                name: 'system-operations',
                component: () => import('@/pages/system/ExecutionLog.vue'),
                meta: { titleKey: 'routes.system.operations', requiresAuth: true, requiredCapability: 'audit.read', shell: 'app' }
            },
            {
                path: 'system/assets',
                name: 'system-assets',
                component: () => import('@/pages/system/Assets.vue'),
                meta: { titleKey: 'routes.system.assets', requiresAuth: true, requiredCapability: 'assets.read', shell: 'app' }
            },
            {
                path: 'system/notifications',
                name: 'system-notifications',
                component: () => import('@/pages/system/Notifications.vue'),
                meta: { titleKey: 'routes.system.notifications', requiresAuth: true, requiredCapability: 'notification.read', shell: 'app' }
            },
            {
                path: 'system/oidc',
                name: 'system-oidc',
                component: () => import('@/pages/system/OidcClients.vue'),
                meta: { titleKey: 'routes.system.oidc', requiresAuth: true, requiredCapability: 'oidc_provider.clients.read', shell: 'app' }
            }
        ]
    }
];
