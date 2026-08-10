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

    it('keeps the shell landing route for authenticated redirect', () => {
        const root = appRoutes.find((record) => record.path === '/');
        const landing = root?.children?.find((record) => record.path === '');
        expect(landing?.meta?.shell).toBe('app');
    });
});
