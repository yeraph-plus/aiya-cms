import { describe, expect, it } from 'vitest';
import type { RouteRecordRaw } from 'vue-router';
import { publicRoutes } from '@/router/public-routes';
import { appRoutes } from '@/router/app-routes';

function leaves(records: RouteRecordRaw[]): RouteRecordRaw[] {
    return records.flatMap((record) => (record.children && record.children.length > 0 ? leaves(record.children) : [record]));
}

const blockedPaths = ['/identity/oidc-clients', '/operations/notifications', '/operations/payments', '/operations/points/ledger', '/content/assets', '/pages/empty', '/pages/notfound'];

describe('production route meta contract', () => {
    const records = leaves([...publicRoutes, ...appRoutes]);

    it('every record carries the fixed RouteMeta shape', () => {
        for (const record of records) {
            expect(record.meta, `route ${record.path} must declare meta`).toBeDefined();
            expect(typeof record.meta?.title, `route ${record.path} title`).toBe('string');
            expect((record.meta?.title ?? '').length, `route ${record.path} title non-empty`).toBeGreaterThan(0);
            expect(typeof record.meta?.requiresAuth, `route ${record.path} requiresAuth`).toBe('boolean');
            expect(['auth', 'app'], `route ${record.path} shell`).toContain(record.meta?.shell);
        }
    });

    it('does not register blocked or legacy routes', () => {
        const paths = leaves(records).map((record) => record.path);
        for (const blocked of blockedPaths) {
            expect(paths, `blocked route ${blocked}`).not.toContain(blocked);
        }
    });

    it('does not register an overview placeholder before the summary provider exists', () => {
        const root = appRoutes.find((record) => record.path === '/');
        const landing = root?.children?.find((record) => record.path === '');
        expect(landing).toBeUndefined();
    });

    it('registers the settings, audit and assets endpoint groups as explicit pages', () => {
        const routes = leaves(appRoutes);
        expect(routes.map((route) => route.path)).toEqual(expect.arrayContaining(['system/settings', 'system/audit', 'system/execution', 'system/assets']));
        expect(routes.map((route) => route.path)).not.toContain('system/settings/:groupKey');
        expect(routes.map((route) => route.path)).not.toContain('system/seo');
        expect(routes.find((route) => route.name === 'system-assets')?.meta?.requiredCapability).toBe('assets.read');
        expect(routes.find((route) => route.name === 'system-settings')?.meta?.requiredCapability).toBe('settings.read');
        expect(routes.find((route) => route.name === 'system-audit')?.meta?.requiredCapability).toBe('audit.read');
        expect(routes.find((route) => route.name === 'system-execution')?.meta?.requiredCapability).toBe('audit.read');
    });

    it('uses one content list for every registered content type', () => {
        const routes = leaves(appRoutes);
        expect(routes.map((route) => route.path)).toEqual(expect.arrayContaining(['content', 'content/new', 'content/:contentId([0-9a-fA-F-]{36})', 'content/taxonomy']));
        expect(routes.map((route) => route.path)).not.toContain('content/posts');
        expect(routes.map((route) => route.path)).not.toContain('content/pages');
    });

    it('registers the user list behind the read capability without a detail sub-route', () => {
        const routes = leaves(appRoutes);
        expect(routes.map((route) => route.path)).toContain('identity/users');
        expect(routes.map((route) => route.path)).not.toContain('identity/users/:userId');
        expect(routes.find((route) => route.name === 'identity-users')?.meta?.requiredCapability).toBe('identity.users.read');
    });
});
