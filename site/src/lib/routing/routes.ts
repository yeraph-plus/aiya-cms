import type { Locale } from '@/lib/i18n';

export type AccountSection = 'points' | 'membership' | 'purchases' | 'gift-card' | 'downloads';
export type RouteId =
    | 'home'
    | 'account'
    | 'community'
    | 'communityTags'
    | 'login'
    | 'register'
    | 'verifyEmail'
    | 'passwordReset';
export type RoutePolicy = 'public' | 'anonymous-only' | 'authenticated';

const routeManifest: Record<RouteId, { paths: Record<Locale, string>; policy: RoutePolicy }> = {
    home: {
        paths: { 'zh-CN': '/', en: '/en' },
        policy: 'public'
    },
    account: {
        paths: { 'zh-CN': '/account', en: '/en/account' },
        policy: 'authenticated'
    },
    login: {
        paths: { 'zh-CN': '/login', en: '/en/login' },
        policy: 'anonymous-only'
    },
    register: {
        paths: { 'zh-CN': '/register', en: '/en/register' },
        policy: 'anonymous-only'
    },
    verifyEmail: {
        paths: { 'zh-CN': '/verify-email', en: '/en/verify-email' },
        policy: 'anonymous-only'
    },
    passwordReset: {
        paths: { 'zh-CN': '/password-reset', en: '/en/password-reset' },
        policy: 'anonymous-only'
    },
    community: {
        paths: { 'zh-CN': '/community', en: '/en/community' },
        policy: 'public'
    },
    communityTags: {
        paths: { 'zh-CN': '/community/tags', en: '/en/community/tags' },
        policy: 'public'
    }
};

const accountSectionPaths: Record<AccountSection, Record<Locale, string>> = {
    points: { 'zh-CN': '/account/points', en: '/en/account/points' },
    membership: { 'zh-CN': '/account/membership', en: '/en/account/membership' },
    purchases: { 'zh-CN': '/account/purchases', en: '/en/account/purchases' },
    'gift-card': { 'zh-CN': '/account/gift-card', en: '/en/account/gift-card' },
    downloads: { 'zh-CN': '/account/downloads', en: '/en/account/downloads' }
};

const anonymousOnlyPaths = new Set(['/auth/login']);
const anonymousOnlyPrefixes = ['/password-reset/'];
const forbiddenReturnPrefixes = [
    '/auth/callback',
    '/auth/login',
    '/auth/logout',
    '/login',
    '/register',
    '/verify-email',
    '/password-reset'
];

function containsControlCharacter(value: string): boolean {
    return [...value].some((character) => {
        const codePoint = character.codePointAt(0) ?? 0;
        return codePoint <= 0x1f || codePoint === 0x7f;
    });
}

export const navigationRoutes = ['home', 'account', 'community', 'communityTags'] as const satisfies readonly RouteId[];

export function localizedAccountRoute(section: AccountSection, locale: Locale): string {
    return accountSectionPaths[section][locale];
}

export function accountSectionFromPath(pathname: string): AccountSection | undefined {
    const normalized = pathname.length > 1 ? pathname.replace(/\/+$/u, '') : pathname;
    return (Object.entries(accountSectionPaths) as [AccountSection, Record<Locale, string>][]).find(([, paths]) =>
        Object.values(paths).includes(normalized)
    )?.[0];
}

export function localizedRoute(routeId: RouteId, locale: Locale): string {
    return routeManifest[routeId].paths[locale];
}

export function routeIdFromPath(pathname: string): RouteId | undefined {
    const normalized = pathname.length > 1 ? pathname.replace(/\/+$/u, '') : pathname;
    if (normalized === '/account' || normalized === '/en/account' || accountSectionFromPath(normalized)) return 'account';
    return (Object.entries(routeManifest) as [RouteId, (typeof routeManifest)[RouteId]][]).find(([, route]) =>
        Object.values(route.paths).includes(normalized)
    )?.[0];
}

export function routePolicy(pathname: string): RoutePolicy {
    const routeId = routeIdFromPath(pathname);
    if (routeId) return routeManifest[routeId].policy;
    if (anonymousOnlyPaths.has(pathname)) return 'anonymous-only';
    if (anonymousOnlyPrefixes.some((prefix) => pathname.startsWith(prefix))) return 'anonymous-only';
    if (pathname === '/account' || pathname === '/en/account' || accountSectionFromPath(pathname)) return 'authenticated';
    return 'public';
}

export function localizedEquivalent(pathname: string, locale: Locale): string {
    const accountSection = accountSectionFromPath(pathname);
    if (accountSection) return localizedAccountRoute(accountSection, locale);
    const routeId = routeIdFromPath(pathname);
    if (routeId) return localizedRoute(routeId, locale);
    const communityPath = pathname.replace(/^\/en(?=\/|$)/u, '') || '/';
    if (communityPath === '/community' || communityPath.startsWith('/community/')) {
        return locale === 'en' ? `/en${communityPath}` : communityPath;
    }
    return localizedRoute('home', locale);
}

export function safeReturnTo(value: string | null | undefined, fallback = '/'): string {
    if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return fallback;
    if (containsControlCharacter(value)) return fallback;

    try {
        const parsed = new URL(value, 'https://site.invalid');
        if (parsed.origin !== 'https://site.invalid') return fallback;
        const decodedPath = decodeURIComponent(parsed.pathname);
        if (decodedPath.includes('\\') || decodedPath.startsWith('//') || containsControlCharacter(decodedPath))
            return fallback;
        if (forbiddenReturnPrefixes.some((prefix) => decodedPath.startsWith(prefix))) return fallback;
        return `${parsed.pathname}${parsed.search}`;
    } catch {
        return fallback;
    }
}
