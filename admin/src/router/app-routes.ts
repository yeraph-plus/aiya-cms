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
                meta: {
                    titleKey: 'routes.dashboard',
                    requiresAuth: true,
                    requiredCapability: 'admin.dashboard.read',
                    shell: 'app'
                }
            },
            {
                path: 'users',
                name: 'users',
                component: () => import('@/pages/identity/UsersList.vue'),
                meta: {
                    titleKey: 'routes.users.list',
                    requiresAuth: true,
                    requiredCapability: 'identity.users.read',
                    shell: 'app'
                }
            },
            {
                path: 'users/permissions',
                name: 'user-permissions',
                component: () => import('@/pages/identity/Permissions.vue'),
                meta: {
                    titleKey: 'routes.users.permissions',
                    requiresAuth: true,
                    requiredCapability: 'access.roles.read',
                    shell: 'app'
                }
            },
            {
                path: 'users/points',
                name: 'user-points',
                component: () => import('@/pages/identity/PointsSystem.vue'),
                meta: {
                    titleKey: 'routes.users.points',
                    requiresAuth: true,
                    requiredCapability: 'points.programs.read',
                    shell: 'app'
                }
            },
            {
                path: 'users/membership',
                name: 'user-membership',
                component: () => import('@/pages/identity/MembershipSystem.vue'),
                meta: {
                    titleKey: 'routes.users.membership',
                    requiresAuth: true,
                    requiredCapability: 'membership.read',
                    shell: 'app'
                }
            },
            {
                path: 'users/gift-cards',
                name: 'user-gift-cards',
                component: () => import('@/pages/identity/GiftCardsSystem.vue'),
                meta: {
                    titleKey: 'routes.users.giftCards',
                    requiresAuth: true,
                    requiredCapability: 'gift_cards.manage',
                    shell: 'app'
                }
            },
            {
                path: 'content/articles',
                name: 'content-articles',
                component: () => import('@/pages/content/ContentList.vue'),
                meta: {
                    titleKey: 'routes.content.articles',
                    requiresAuth: true,
                    requiredCapability: 'content.read',
                    shell: 'app'
                }
            },
            {
                path: 'content/write',
                name: 'content-write',
                component: () => import('@/pages/content/ContentEditor.vue'),
                meta: {
                    titleKey: 'routes.content.write',
                    requiresAuth: true,
                    requiredCapability: 'content.write',
                    shell: 'app'
                }
            },
            {
                path: 'content/taxonomies',
                name: 'content-taxonomies',
                component: () => import('@/pages/content/Taxonomy.vue'),
                meta: {
                    titleKey: 'routes.content.taxonomies',
                    requiresAuth: true,
                    requiredCapability: 'taxonomy.read',
                    shell: 'app'
                }
            },
            {
                path: 'content/comments',
                name: 'content-comments',
                component: () => import('@/pages/content/Comments.vue'),
                meta: {
                    titleKey: 'routes.content.comments',
                    requiresAuth: true,
                    requiredCapability: 'comments.read',
                    shell: 'app'
                }
            },
            {
                path: 'community/discussions',
                name: 'community-discussions',
                component: () => import('@/pages/community/Discussions.vue'),
                meta: {
                    titleKey: 'routes.community.discussions',
                    requiresAuth: true,
                    requiredCapability: 'community.read_admin',
                    shell: 'app'
                }
            },
            {
                path: 'community/tags',
                name: 'community-tags',
                component: () => import('@/pages/community/Tags.vue'),
                meta: {
                    titleKey: 'routes.community.tags',
                    requiresAuth: true,
                    requiredCapability: 'community.tags.manage',
                    shell: 'app'
                }
            },
            {
                path: 'settings',
                name: 'settings',
                redirect: '/settings/general',
                meta: {
                    titleKey: 'routes.settings',
                    requiresAuth: true,
                    requiredCapability: 'settings.read',
                    shell: 'app'
                }
            },
            {
                path: 'settings/general',
                name: 'settings-general',
                component: () => import('@/pages/system/SettingsGroups.vue'),
                meta: {
                    titleKey: 'routes.settings',
                    requiresAuth: true,
                    requiredCapability: 'settings.read',
                    shell: 'app'
                }
            },
            {
                path: 'settings/membership',
                name: 'settings-membership',
                component: () => import('@/pages/identity/MembershipSettings.vue'),
                meta: {
                    titleKey: 'nav.settingsMembership',
                    requiresAuth: true,
                    requiredCapability: 'membership.levels.read',
                    shell: 'app'
                }
            },
            {
                path: 'system/audit',
                name: 'system-audit',
                component: () => import('@/pages/system/AuditLog.vue'),
                meta: {
                    titleKey: 'routes.system.audit',
                    requiresAuth: true,
                    requiredCapability: 'audit.read',
                    shell: 'app'
                }
            },
            {
                path: 'system/operations',
                name: 'system-operations',
                component: () => import('@/pages/system/ExecutionLog.vue'),
                meta: {
                    titleKey: 'routes.system.operations',
                    requiresAuth: true,
                    requiredCapability: 'audit.read',
                    shell: 'app'
                }
            },
            {
                path: 'system/assets',
                name: 'system-assets',
                component: () => import('@/pages/system/Assets.vue'),
                meta: {
                    titleKey: 'routes.system.assets',
                    requiresAuth: true,
                    requiredCapability: 'assets.read',
                    shell: 'app'
                }
            },
            {
                path: 'system/notifications',
                name: 'system-notifications',
                component: () => import('@/pages/system/Notifications.vue'),
                meta: {
                    titleKey: 'routes.system.notifications',
                    requiresAuth: true,
                    requiredCapability: 'notification.read',
                    shell: 'app'
                }
            },
            {
                path: 'system/oidc',
                name: 'system-oidc',
                component: () => import('@/pages/system/OidcClients.vue'),
                meta: {
                    titleKey: 'routes.system.oidc',
                    requiresAuth: true,
                    requiredCapability: 'oidc_provider.clients.read',
                    shell: 'app'
                }
            }
        ]
    }
];
