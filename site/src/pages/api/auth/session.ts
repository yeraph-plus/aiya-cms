import type { APIRoute } from 'astro';

import { currentPublicUser } from '@/lib/auth/server/oidc';

export const GET: APIRoute = async ({ session }) => {
    if (!session) return Response.json({ authenticated: false }, { status: 503 });
    try {
        const user = await currentPublicUser(session);
        return Response.json(user ? { authenticated: true, user } : { authenticated: false }, {
            headers: { 'Cache-Control': 'private, no-store' }
        });
    } catch {
        return Response.json(
            { authenticated: false },
            { status: 503, headers: { 'Cache-Control': 'private, no-store' } }
        );
    }
};
