import type { MenuItem as LayoutMenuItem } from '@/layout/composables/layout';

export interface NavMenuItem extends Omit<LayoutMenuItem, 'items' | 'label'> {
    labelKey: string;
    to?: string;
    capability?: string;
    routeName?: string;
    items?: NavMenuItem[];
}

export const productMenu: NavMenuItem[] = [
    {
        labelKey: 'nav.dashboard',
        icon: 'pi pi-fw pi-chart-bar',
        to: '/dashboard',
        routeName: 'dashboard',
        capability: 'admin.dashboard.read'
    },
    {
        labelKey: 'nav.content.group',
        icon: 'pi pi-fw pi-file-edit',
        path: '/content',
        items: [
            {
                labelKey: 'nav.content.write',
                icon: 'pi pi-fw pi-pencil',
                to: '/content/write',
                routeName: 'content-write',
                capability: 'content.write'
            },
            {
                labelKey: 'nav.content.articles',
                icon: 'pi pi-fw pi-file',
                to: '/content/articles',
                routeName: 'content-articles',
                capability: 'content.read'
            },
            {
                labelKey: 'nav.content.taxonomies',
                icon: 'pi pi-fw pi-tags',
                to: '/content/taxonomies',
                routeName: 'content-taxonomies',
                capability: 'taxonomy.read'
            },
            {
                labelKey: 'nav.content.comments',
                icon: 'pi pi-fw pi-comments',
                to: '/content/comments',
                routeName: 'content-comments',
                capability: 'comments.read'
            }
        ]
    },
    {
        labelKey: 'nav.users.group',
        icon: 'pi pi-fw pi-users',
        path: '/users',
        items: [
            {
                labelKey: 'nav.users.list',
                icon: 'pi pi-fw pi-users',
                to: '/users',
                routeName: 'users',
                capability: 'identity.users.read'
            },
            {
                labelKey: 'nav.users.permissions',
                icon: 'pi pi-fw pi-shield',
                to: '/users/permissions',
                routeName: 'user-permissions',
                capability: 'access.roles.read'
            },
            {
                labelKey: 'nav.users.points',
                icon: 'pi pi-fw pi-star',
                to: '/users/points',
                routeName: 'user-points',
                capability: 'points.read'
            },
            {
                labelKey: 'nav.users.membership',
                icon: 'pi pi-fw pi-id-card',
                to: '/users/membership',
                routeName: 'user-membership',
                capability: 'membership.read'
            },
            {
                labelKey: 'nav.users.payments',
                icon: 'pi pi-fw pi-credit-card',
                to: '/users/payments',
                routeName: 'user-payments',
                capability: 'payments.read'
            }
        ]
    },
    {
        labelKey: 'nav.system.group',
        icon: 'pi pi-fw pi-cog',
        path: '/system',
        items: [
            {
                labelKey: 'nav.system.audit',
                icon: 'pi pi-fw pi-history',
                to: '/system/audit',
                routeName: 'system-audit',
                capability: 'audit.read'
            },
            {
                labelKey: 'nav.system.operations',
                icon: 'pi pi-fw pi-sync',
                to: '/system/operations',
                routeName: 'system-operations',
                capability: 'audit.read'
            },
            {
                labelKey: 'nav.system.assets',
                icon: 'pi pi-fw pi-images',
                to: '/system/assets',
                routeName: 'system-assets',
                capability: 'assets.read'
            },
            {
                labelKey: 'nav.system.notifications',
                icon: 'pi pi-fw pi-bell',
                to: '/system/notifications',
                routeName: 'system-notifications',
                capability: 'notification.read'
            },
            {
                labelKey: 'nav.system.oidc',
                icon: 'pi pi-fw pi-lock',
                to: '/system/oidc',
                routeName: 'system-oidc',
                capability: 'oidc_provider.clients.read'
            }
        ]
    },
    {
        labelKey: 'nav.settings',
        icon: 'pi pi-fw pi-sliders-h',
        to: '/settings',
        routeName: 'settings',
        capability: 'settings.read'
    }
];
