import type { Locale } from '@/lib/i18n';

export type RouteId = 'home' | 'account' | 'community' | 'communityTags';
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
    community: {
        paths: { 'zh-CN': '/community', en: '/en/community' },
        policy: 'public'
    },
    communityTags: {
        paths: { 'zh-CN': '/community/tags', en: '/en/community/tags' },
        policy: 'public'
    }
};

const anonymousOnlyPaths = new Set(['/auth/login']);
const forbiddenReturnPrefixes = ['/auth/callback', '/auth/login', '/auth/logout'];

function containsControlCharacter(value: string): boolean {
    return [...value].some((character) => {
        const codePoint = character.codePointAt(0) ?? 0;
        return codePoint <= 0x1f || codePoint === 0x7f;
    });
}

export const navigationRoutes = ['home', 'account', 'community', 'communityTags'] as const satisfies readonly RouteId[];

export function localizedRoute(routeId: RouteId, locale: Locale): string {
    return routeManifest[routeId].paths[locale];
}

export function routeIdFromPath(pathname: string): RouteId | undefined {
    const normalized = pathname.length > 1 ? pathname.replace(/\/+$/u, '') : pathname;
    return (Object.entries(routeManifest) as [RouteId, (typeof routeManifest)[RouteId]][]).find(([, route]) =>
        Object.values(route.paths).includes(normalized)
    )?.[0];
}

export function routePolicy(pathname: string): RoutePolicy {
    const routeId = routeIdFromPath(pathname);
    if (routeId) return routeManifest[routeId].policy;
    if (anonymousOnlyPaths.has(pathname)) return 'anonymous-only';
    return 'public';
}

export function localizedEquivalent(pathname: string, locale: Locale): string {
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
