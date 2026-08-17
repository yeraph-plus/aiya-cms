import { describe, expect, it } from 'vitest';
import { productMenu, type NavMenuItem } from '@/navigation/menu';
import { filterMenu } from '@/navigation/visibility';

function allItems(items: NavMenuItem[]): NavMenuItem[] {
    return items.flatMap((item) => (item.items ? [item, ...allItems(item.items)] : [item]));
}

const capabilities = (keys: string[]) => new Set(keys);
const allRegistered = () => () => true;
const noneRegistered = () => () => false;
const registered = (names: string[]) => {
    const set = new Set(names);
    return (name?: string) => (name ? set.has(name) : true);
};

describe('product menu', () => {
    it('defines the explicit product groups from the plan', () => {
        expect(productMenu.map((group) => group.labelKey)).toEqual(['nav.dashboard', 'nav.content.group', 'nav.users.group', 'nav.community.group', 'nav.system.group', 'nav.settings']);
        const content = productMenu.find((group) => group.labelKey === 'nav.content.group');
        const users = productMenu.find((group) => group.labelKey === 'nav.users.group');
        const community = productMenu.find((group) => group.labelKey === 'nav.community.group');
        const system = productMenu.find((group) => group.labelKey === 'nav.system.group');
        expect(content?.items?.map((item) => item.to)).toEqual(['/content/write', '/content/articles', '/content/taxonomies', '/content/comments']);
        expect(users?.items?.map((item) => item.to)).toEqual(['/users', '/users/permissions', '/users/points', '/users/membership']);
        const settings = productMenu.find((group) => group.labelKey === 'nav.settings');
        expect(settings?.items?.map((item) => item.labelKey)).not.toContain('nav.settingsPoints');
        expect(community?.items?.map((item) => item.to)).toEqual(['/community/discussions', '/community/tags']);
        expect(system?.items?.map((item) => item.to)).toContain('/system/assets');
        expect(system?.items?.map((item) => item.to)).toContain('/system/notifications');
        expect(system?.items?.map((item) => item.to)).toContain('/system/oidc');
    });

    it('does not contain demo or blocked contract entries', () => {
        const items = allItems(productMenu);
        const labels = items.map((item) => item.labelKey.toLowerCase());
        expect(labels.join(' ')).not.toContain('demo');
        expect(labels).not.toContain('seo');
        for (const blocked of ['media library', 'overview placeholder']) {
            expect(labels.join(' ')).not.toContain(blocked);
        }
    });

    it('every item with a route declares a capability and a route name', () => {
        for (const item of allItems(productMenu)) {
            if (item.to) {
                expect(item.capability, `menu item ${item.labelKey}`).toBeDefined();
                expect(item.routeName, `menu item ${item.labelKey}`).toBeDefined();
            }
        }
    });
});

describe('menu capability filtering', () => {
    it('hides items without the required capability', () => {
        const visible = filterMenu(productMenu, {
            capabilities: capabilities(['settings.read']),
            isRouteRegistered: allRegistered()
        });
        const labels = allItems(visible).map((item) => item.labelKey);
        expect(labels).toContain('nav.settings');
        expect(labels).not.toContain('nav.users.list');
    });

    it('hides a parent group when no child survives', () => {
        const visible = filterMenu(productMenu, {
            capabilities: capabilities(['settings.read']),
            isRouteRegistered: allRegistered()
        });
        const groups = visible.map((group) => group.labelKey);
        expect(groups).not.toContain('nav.users.group');
        expect(groups).not.toContain('nav.content.group');
        expect(groups).toContain('nav.settings');
    });

    it('does not expose an overview placeholder before a summary provider exists', () => {
        const visible = filterMenu(productMenu, {
            capabilities: capabilities([]),
            isRouteRegistered: allRegistered()
        });
        expect(visible.map((group) => group.labelKey)).not.toContain('nav.placeholder');
    });
});

describe('menu route registration filtering', () => {
    it('hides items whose route is not yet registered', () => {
        const visible = filterMenu(productMenu, {
            capabilities: capabilities(['identity.users.read', 'access.roles.read']),
            isRouteRegistered: noneRegistered()
        });
        expect(visible).toEqual([]);
    });

    it('keeps items whose route is registered', () => {
        const visible = filterMenu(productMenu, {
            capabilities: capabilities(['identity.users.read']),
            isRouteRegistered: registered(['users'])
        });
        expect(visible).toHaveLength(1);
        expect(visible[0].labelKey).toBe('nav.users.group');
        expect(visible[0].items?.map((item) => item.labelKey)).toEqual(['nav.users.list']);
    });
});
