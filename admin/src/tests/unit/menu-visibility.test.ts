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
        expect(productMenu.map((group) => group.label)).toEqual(['Identity', 'Content', 'System', 'Operations']);
        const content = productMenu.find((group) => group.label === 'Content');
        const system = productMenu.find((group) => group.label === 'System');
        expect(content?.items?.map((item) => item.to)).toEqual(['/content', '/content/taxonomy']);
        expect(system?.items?.map((item) => item.to)).toContain('/system/assets');
    });

    it('does not contain demo or blocked contract entries', () => {
        const items = allItems(productMenu);
        const labels = items.map((item) => item.label.toLowerCase());
        expect(labels.join(' ')).not.toContain('demo');
        expect(labels).not.toContain('seo');
        for (const blocked of ['oidc', 'notification', 'payment', 'ledger', 'media library', 'overview placeholder']) {
            expect(labels.join(' ')).not.toContain(blocked);
        }
    });

    it('every item with a route declares a capability and a route name', () => {
        for (const item of allItems(productMenu)) {
            if (item.to) {
                expect(item.capability, `menu item ${item.label}`).toBeDefined();
                expect(item.routeName, `menu item ${item.label}`).toBeDefined();
            }
        }
    });
});

describe('menu capability filtering', () => {
    it('hides items without the required capability', () => {
        const visible = filterMenu(productMenu, { capabilities: capabilities(['settings.read']), isRouteRegistered: allRegistered() });
        const labels = allItems(visible).map((item) => item.label);
        expect(labels).toContain('Settings');
        expect(labels).not.toContain('Users');
        expect(labels).not.toContain('Posts');
        expect(labels).not.toContain('Pages');
    });

    it('hides a parent group when no child survives', () => {
        const visible = filterMenu(productMenu, { capabilities: capabilities(['settings.read']), isRouteRegistered: allRegistered() });
        const groups = visible.map((group) => group.label);
        expect(groups).not.toContain('Identity');
        expect(groups).not.toContain('Content');
        expect(groups).not.toContain('Operations');
        expect(groups).toContain('System');
    });

    it('does not expose an overview placeholder before a summary provider exists', () => {
        const visible = filterMenu(productMenu, { capabilities: capabilities([]), isRouteRegistered: allRegistered() });
        expect(visible.map((group) => group.label)).not.toContain('Home');
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
            isRouteRegistered: registered(['identity-users'])
        });
        expect(visible).toHaveLength(1);
        expect(visible[0].label).toBe('Identity');
        expect(visible[0].items?.map((item) => item.label)).toEqual(['Users']);
    });
});
