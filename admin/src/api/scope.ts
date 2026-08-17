const ADMIN_PREFIX = '/api/v1/admin/';
const OIDC_PREFIX = '/oidc/';

export function assertAdminSpaApiPath(path: string): void {
    const allowed = path.startsWith(ADMIN_PREFIX) || path === '/api/v1/admin' || path.startsWith(OIDC_PREFIX) || path === '/.well-known/openid-configuration';
    if (!allowed) {
        throw new Error(`Administrator SPA API boundary rejected ${path}`);
    }
}
