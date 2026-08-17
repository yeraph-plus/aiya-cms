import type { APIRoute } from 'astro';

import { verifySameOriginForm } from '@/lib/auth/server/csrf';
import { endSession } from '@/lib/auth/server/oidc';

export const POST: APIRoute = async ({ request, session, redirect }) => {
    if (!session) return new Response('Session storage is unavailable', { status: 503 });
    const form = await request.formData();
    try {
        await verifySameOriginForm(
            request,
            session,
            typeof form.get('csrf') === 'string' ? String(form.get('csrf')) : null
        );
    } catch {
        return new Response('Invalid request', { status: 403 });
    }
    const providerLogout = await endSession(session);
    return redirect(providerLogout?.href ?? '/auth/logged-out', 303);
};

export const ALL: APIRoute = () => new Response('Method not allowed', { status: 405, headers: { Allow: 'POST' } });
