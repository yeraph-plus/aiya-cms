import type { APIRoute } from 'astro';

import { beginAuthorization } from '@/lib/auth/server/oidc';
import { localeFromPath } from '@/lib/i18n';

export const GET: APIRoute = async ({ session, url, redirect }) => {
    if (!session) return new Response('Session storage is unavailable', { status: 503 });
    try {
        const locale =
            url.searchParams.get('locale') === 'en' ? 'en' : localeFromPath(url.searchParams.get('returnTo') ?? '/');
        const authorizationUrl = await beginAuthorization(session, url.searchParams.get('returnTo'), locale);
        return redirect(authorizationUrl.href, 302);
    } catch {
        return redirect('/auth/error', 302);
    }
};
