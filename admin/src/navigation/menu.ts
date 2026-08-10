import type { MenuItem as LayoutMenuItem } from '@/layout/composables/layout';

export interface NavMenuItem extends Omit<LayoutMenuItem, 'items'> {
    label: string;
    to?: string;
    capability?: string;
    routeName?: string;
    items?: NavMenuItem[];
}

export const productMenu: NavMenuItem[] = [
    {
        label: 'Home',
        icon: 'pi pi-fw pi-home',
        items: [
            {
                label: 'Overview',
                icon: 'pi pi-fw pi-home',
                to: '/',
                routeName: 'dashboard',
                capability: 'admin.summary.read'
            }
        ]
    },
    {
        label: 'Identity',
        icon: 'pi pi-fw pi-id-card',
        path: '/identity',
        items: [
            {
                label: 'Users',
                icon: 'pi pi-fw pi-users',
                to: '/identity/users',
                routeName: 'identity-users',
                capability: 'identity.users.read'
            },
            {
                label: 'Roles & Permissions',
                icon: 'pi pi-fw pi-lock',
                to: '/identity/roles',
                routeName: 'identity-roles',
                capability: 'access.roles.read'
            },
            {
                label: 'Capability Catalog',
                icon: 'pi pi-fw pi-key',
                to: '/identity/capabilities',
                routeName: 'identity-capabilities',
                capability: 'access.roles.read'
            }
        ]
    },
    {
        label: 'Content',
        icon: 'pi pi-fw pi-briefcase',
        path: '/content',
        items: [
            {
                label: 'Posts',
                icon: 'pi pi-fw pi-file',
                to: '/content/posts',
                routeName: 'content-posts',
                capability: 'content.read'
            },
            {
                label: 'Pages',
                icon: 'pi pi-fw pi-file-edit',
                to: '/content/pages',
                routeName: 'content-pages',
                capability: 'content.read'
            },
            {
                label: 'Taxonomy',
                icon: 'pi pi-fw pi-tags',
                to: '/content/taxonomy',
                routeName: 'content-taxonomy',
                capability: 'taxonomy.read'
            }
        ]
    },
    {
        label: 'System',
        icon: 'pi pi-fw pi-cog',
        path: '/system',
        items: [
            {
                label: 'Settings',
                icon: 'pi pi-fw pi-sliders-h',
                to: '/system/settings',
                routeName: 'system-settings',
                capability: 'settings.read'
            },
            {
                label: 'SEO',
                icon: 'pi pi-fw pi-search',
                to: '/system/seo',
                routeName: 'system-seo',
                capability: 'settings.read'
            },
            {
                label: 'Audit Log',
                icon: 'pi pi-fw pi-history',
                to: '/system/audit',
                routeName: 'system-audit',
                capability: 'audit.read'
            },
            {
                label: 'Diagnostics',
                icon: 'pi pi-fw pi-heart',
                to: '/system/diagnostics',
                routeName: 'system-diagnostics',
                capability: 'access.roles.read'
            }
        ]
    },
    {
        label: 'Operations',
        icon: 'pi pi-fw pi-sync',
        path: '/operations',
        items: [
            {
                label: 'Points Adjustment',
                icon: 'pi pi-fw pi-star',
                to: '/operations/points',
                routeName: 'operations-points',
                capability: 'points.adjust'
            }
        ]
    }
];
