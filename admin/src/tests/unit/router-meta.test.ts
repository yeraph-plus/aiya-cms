import { describe, expect, it } from 'vitest';
import type { RouteRecordRaw } from 'vue-router';
import { publicRoutes } from '@/router/public-routes';
import { appRoutes } from '@/router/app-routes';

function leaves(records: RouteRecordRaw[]): RouteRecordRaw[] {
    return records.flatMap((record) => (record.children && record.children.length > 0 ? leaves(record.children) : [record]));
}

const blockedPaths = ['pages/empty', 'pages/notfound'];

describe('production route meta contract', () => {
    const records = leaves([...publicRoutes, ...appRoutes]);

    it('every record carries the fixed RouteMeta shape', () => {
        for (const record of records) {
            expect(record.meta, `route ${record.path} must declare meta`).toBeDefined();
            expect(typeof record.meta?.titleKey, `route ${record.path} titleKey`).toBe('string');
            expect((record.meta?.titleKey ?? '').length, `route ${record.path} titleKey non-empty`).toBeGreaterThan(0);
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

    it('registers the complete public authentication form chain', () => {
        expect(publicRoutes.map((route) => route.path)).toEqual(
            expect.arrayContaining(['/auth/login', '/auth/register', '/auth/verify-email', '/auth/password-reset', '/auth/password-reset/confirm', '/callback', '/logged-out'])
        );
    });

    it('registers the first contract-backed workbench routes', () => {
        const routes = leaves(appRoutes);
        expect(routes.map((route) => route.path)).toEqual(expect.arrayContaining(['dashboard', 'content/write', 'content/articles', 'content/taxonomies', 'content/comments', 'users', 'users/permissions', 'users/points', 'users/membership', 'users/payments', 'system/audit', 'system/operations', 'system/assets', 'system/notifications', 'system/oidc', 'settings']));
        expect(routes.map((route) => route.path)).not.toContain('settings/:groupKey');
        expect(routes.find((route) => route.name === 'system-assets')?.meta?.requiredCapability).toBe('assets.read');
        expect(routes.find((route) => route.name === 'settings')?.meta?.requiredCapability).toBe('settings.read');
        expect(routes.find((route) => route.name === 'system-audit')?.meta?.requiredCapability).toBe('audit.read');
        expect(routes.find((route) => route.name === 'system-operations')?.meta?.requiredCapability).toBe('audit.read');
        expect(routes.find((route) => route.name === 'user-permissions')?.meta?.requiredCapability).toBe('access.roles.read');
        expect(routes.find((route) => route.name === 'user-points')?.meta?.requiredCapability).toBe('points.read');
        expect(routes.find((route) => route.name === 'user-membership')?.meta?.requiredCapability).toBe('membership.read');
        expect(routes.find((route) => route.name === 'user-payments')?.meta?.requiredCapability).toBe('payments.read');
        expect(routes.find((route) => route.name === 'system-oidc')?.meta?.requiredCapability).toBe('oidc_provider.clients.read');
        expect(routes.find((route) => route.name === 'content-comments')?.meta?.requiredCapability).toBe('comments.read');
        expect(routes.find((route) => route.name === 'system-notifications')?.meta?.requiredCapability).toBe('notification.read');
    });

    it('uses workbenches and overlays instead of record detail routes', () => {
        const routes = leaves(appRoutes);
        expect(routes.map((route) => route.path)).not.toContain('content/:contentId([0-9a-fA-F-]{36})');
        expect(routes.map((route) => route.path)).not.toContain('users/:userId');
        expect(routes.find((route) => route.name === 'users')?.meta?.requiredCapability).toBe('identity.users.read');
    });
});
