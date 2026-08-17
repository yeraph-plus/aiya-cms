import type { APIRoute } from 'astro';

import { completeAuthorization } from '@/lib/auth/server/oidc';

export const GET: APIRoute = async ({ session, url, redirect }) => {
    if (!session) return new Response('Session storage is unavailable', { status: 503 });
    const transaction = await session.get('oidcTransaction');
    try {
        const returnTo = await completeAuthorization(session, url);
        return redirect(returnTo, 303);
    } catch {
        const locale = transaction?.locale === 'en' ? '?locale=en' : '';
        return redirect(`/auth/error${locale}`, 303);
    }
};
