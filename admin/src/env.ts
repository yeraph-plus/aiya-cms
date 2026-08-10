export const APP_NAME = 'AIYA-CMS';

export const DEFAULT_ISSUER = 'http://127.0.0.1:8000';
const DEFAULT_CLIENT_ID = 'admin';

type PublicEnv = Record<string, string | boolean | undefined>;

export interface AdminEnv {
    apiBaseUrl: string;
    oidcIssuer: string;
    oidcClientId: string;
    oidcRedirectUri: string;
    oidcPostLogoutRedirectUri: string;
}

function valueFromEnv(values: PublicEnv, name: string): string | undefined {
    const raw = values[name];
    return raw === undefined || raw === '' ? undefined : String(raw);
}

export function resolveOidcIssuer(values: PublicEnv): string {
    return (valueFromEnv(values, 'AIYA_ISSUER') ?? DEFAULT_ISSUER).replace(/\/+$/, '');
}

function envValue(name: string): string | undefined {
    return valueFromEnv(import.meta.env, name);
}

function originOf(url: string): string {
    try {
        return new URL(url).origin;
    } catch {
        return '';
    }
}

function validateUrl(name: string, value: string): string {
    const normalized = value.replace(/\/+$/, '');
    try {
        const parsed = new URL(normalized);
        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
            throw new Error('protocol');
        }
        const isLocal = parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1' || parsed.hostname === 'local.host';
        const isDev = import.meta.env.DEV;
        if (parsed.protocol !== 'https:' && !isLocal && !isDev) {
            throw new Error('non-local http');
        }
        return normalized;
    } catch {
        throw new Error(`${name} 配置了无效的 URL: ${value}`);
    }
}

function localRedirectUri(path: string): string {
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    return `${origin}${path}`;
}

const oidcIssuerRaw = resolveOidcIssuer(import.meta.env);
const publicBaseRaw = envValue('VITE_PUBLIC_BASE_URL') ?? envValue('AIYA_PUBLIC_BASE_URL') ?? '';

export const env: AdminEnv = {
    apiBaseUrl: envValue('VITE_API_BASE_URL') ?? originOf(oidcIssuerRaw),
    oidcIssuer: validateUrl('OIDC issuer', oidcIssuerRaw),
    oidcClientId: envValue('VITE_OIDC_CLIENT_ID') ?? DEFAULT_CLIENT_ID,
    oidcRedirectUri: validateUrl('OIDC redirect URI', envValue('VITE_OIDC_REDIRECT_URI') ?? (publicBaseRaw ? `${publicBaseRaw}/callback` : localRedirectUri('/callback'))),
    oidcPostLogoutRedirectUri: validateUrl('OIDC post logout URI', envValue('VITE_OIDC_POST_LOGOUT_URI') ?? (publicBaseRaw ? `${publicBaseRaw}/logged-out` : localRedirectUri('/logged-out')))
};
