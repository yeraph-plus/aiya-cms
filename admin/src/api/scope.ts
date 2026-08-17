const ADMIN_PREFIX = '/api/v1/admin/';
const AUTH_PREFIX = '/api/v1/auth/';
const OIDC_PREFIX = '/oidc/';

export function assertAdminSpaApiPath(path: string): void {
    const allowed = path.startsWith(ADMIN_PREFIX) || path.startsWith(AUTH_PREFIX) || path === '/api/v1/admin' || path === '/api/v1/auth' || path.startsWith(OIDC_PREFIX) || path === '/.well-known/openid-configuration';
    if (!allowed) {
        throw new Error(`Administrator SPA API boundary rejected ${path}`);
    }
}
