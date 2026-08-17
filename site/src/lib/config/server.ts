export type SiteEnvironment = 'dev' | 'test' | 'production';

const DEVELOPMENT_CLIENT_SECRET = 'dev-aiya-site-secret-change-before-use-1234567890';

export interface ServerConfig {
    environment: SiteEnvironment;
    siteOrigin: string;
    apiOrigin: string;
    oidcIssuer: string;
    oidcClientId: string;
    oidcClientSecret: string;
    oidcRedirectUri: string;
    oidcPostLogoutRedirectUri: string;
    oidcScope: string;
    redisUrl: string;
}

function readRequired(name: string, fallback?: string): string {
    const value = process.env[name]?.trim() || fallback;
    if (!value) throw new Error(`${name} is required`);
    return value;
}

function normalizedOrigin(name: string, fallback: string): string {
    const url = new URL(readRequired(name, fallback));
    if (url.pathname !== '/' || url.search || url.hash) throw new Error(`${name} must be an origin URL`);
    return url.origin;
}

export function loadServerConfig(): ServerConfig {
    const environment = readRequired('SITE_ENVIRONMENT', 'dev') as SiteEnvironment;
    if (!['dev', 'test', 'production'].includes(environment)) throw new Error('SITE_ENVIRONMENT is invalid');

    const siteOrigin = normalizedOrigin('SITE_ORIGIN', 'http://127.0.0.1:4321');
    const apiOrigin = normalizedOrigin('SITE_API_ORIGIN', 'http://127.0.0.1:8000');
    const oidcIssuer = normalizedOrigin('SITE_OIDC_ISSUER', apiOrigin);
    const oidcClientSecret = readRequired(
        'SITE_OIDC_CLIENT_SECRET',
        environment === 'production' ? undefined : DEVELOPMENT_CLIENT_SECRET
    );
    const redisUrl = readRequired('SITE_REDIS_URL', 'redis://127.0.0.1:6379/1');

    if (!redisUrl.startsWith('redis://') && !redisUrl.startsWith('rediss://'))
        throw new Error('SITE_REDIS_URL must use redis:// or rediss://');
    if (environment === 'production') {
        for (const [name, value] of [
            ['SITE_ORIGIN', siteOrigin],
            ['SITE_API_ORIGIN', apiOrigin],
            ['SITE_OIDC_ISSUER', oidcIssuer]
        ] as const) {
            if (!value.startsWith('https://')) throw new Error(`${name} must use HTTPS in production`);
        }
        if (oidcClientSecret === DEVELOPMENT_CLIENT_SECRET)
            throw new Error('SITE_OIDC_CLIENT_SECRET must be replaced in production');
    }

    return {
        environment,
        siteOrigin,
        apiOrigin,
        oidcIssuer,
        oidcClientId: readRequired('SITE_OIDC_CLIENT_ID', 'aiya-site'),
        oidcClientSecret,
        oidcRedirectUri: new URL('/auth/callback', siteOrigin).href,
        oidcPostLogoutRedirectUri: new URL('/auth/logged-out', siteOrigin).href,
        oidcScope: readRequired('SITE_OIDC_SCOPE', 'openid profile email offline_access'),
        redisUrl
    };
}
