import { randomUUID } from 'node:crypto';

import { defineMiddleware } from 'astro:middleware';

import { currentPublicUser } from '@/lib/auth/server/oidc';
import { LOCALE_COOKIE, localeFromPath } from '@/lib/i18n';
import { localizedRoute, routePolicy, safeReturnTo } from '@/lib/routing/routes';

const requestIdPattern = /^[A-Za-z0-9._:-]{1,128}$/u;

function securityHeaders(response: Response, requestId: string): Response {
    response.headers.set('X-Request-ID', requestId);
    response.headers.set('X-Content-Type-Options', 'nosniff');
    response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
    response.headers.set('X-Frame-Options', 'DENY');
    response.headers.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()');
    response.headers.set(
        'Content-Security-Policy',
        "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; img-src 'self' data:; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'"
    );
    return response;
}

export const onRequest = defineMiddleware(async (context, next) => {
    const incomingRequestId = context.request.headers.get('X-Request-ID') ?? '';
    const requestId = requestIdPattern.test(incomingRequestId) ? incomingRequestId : randomUUID();
    const locale = localeFromPath(context.url.pathname);
    const policy = routePolicy(context.url.pathname);
    context.locals.locale = locale;
    context.locals.requestId = requestId;

    try {
        if (context.session) context.locals.user = await currentPublicUser(context.session);
    } catch {
        if (policy === 'authenticated') {
            return securityHeaders(new Response('Authentication session unavailable', { status: 503 }), requestId);
        }
    }

    if (policy === 'authenticated' && !context.locals.user) {
        const returnTo = safeReturnTo(`${context.url.pathname}${context.url.search}`);
        return context.redirect(`/auth/login?returnTo=${encodeURIComponent(returnTo)}`, 302);
    }
    if (policy === 'anonymous-only' && context.locals.user) {
        return context.redirect(localizedRoute('account', locale), 302);
    }

    const response = await next();
    if (context.cookies.get(LOCALE_COOKIE)?.value !== locale) {
        context.cookies.set(LOCALE_COOKIE, locale, {
            path: '/',
            maxAge: 31_536_000,
            sameSite: 'lax',
            secure: context.url.protocol === 'https:'
        });
    }
    if (context.url.pathname.startsWith('/auth/') || policy === 'anonymous-only' || context.locals.user)
        response.headers.set('Cache-Control', 'private, no-store');
    return securityHeaders(response, requestId);
});
