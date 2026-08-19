import type { APIContext } from 'astro';

import { verifySameOriginForm } from '@/lib/auth/server/csrf';
import { createGuardedServerFetch } from '@/lib/api/server/client';

export type CommunityMutation =
    | { method: 'POST'; path: '/api/v1/community/discussions'; body: { title: string; body: string; template_key: string } }
    | { method: 'POST'; path: `/api/v1/community/discussions/${string}/replies`; body: { body: string } }
    | { method: 'PATCH'; path: `/api/v1/community/discussions/${string}`; body: { title?: string; expected_version: number } }
    | { method: 'PATCH'; path: `/api/v1/community/posts/${string}`; body: { body: string; expected_version: number } };

function requestHeaders(context: APIContext, key: string): Headers {
    const headers = new Headers({
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'Idempotency-Key': key
    });
    headers.set('X-Request-ID', context.locals.requestId);
    return headers;
}

export async function communityMutation(
    context: APIContext,
    mutation: CommunityMutation,
    csrf: string | null,
    idempotencyKey?: string
): Promise<Response> {
    if (!context.session) return Response.json({ message: 'Authentication required' }, { status: 401 });

    const key = idempotencyKey ?? context.request.headers.get('Idempotency-Key') ?? crypto.randomUUID();
    try {
        await verifySameOriginForm(context.request, context.session, csrf);
    } catch (error) {
        return Response.json({ message: error instanceof Error ? error.message : 'Invalid CSRF token' }, { status: 403 });
    }

    const fetcher = createGuardedServerFetch(context.session, context.locals.requestId);
    const response = await fetcher(mutation.path, {
        method: mutation.method,
        headers: requestHeaders(context, key),
        body: JSON.stringify(mutation.body)
    });
    const contentType = response.headers.get('content-type') ?? '';
    const payload = contentType.includes('json') ? await response.json() : await response.text();
    const headers = new Headers({ 'Cache-Control': 'private, no-store' });
    const requestId = response.headers.get('X-Request-ID');
    if (requestId) headers.set('X-Request-ID', requestId);
    headers.set('Content-Type', contentType.includes('json') ? 'application/json' : 'text/plain');
    return new Response(typeof payload === 'string' ? payload : JSON.stringify(payload), {
        status: response.status,
        headers
    });
}

export async function mutationForm(request: Request): Promise<{ csrf: string | null; body: Record<string, string>; key: string }> {
    const form = await request.formData();
    const body: Record<string, string> = {};
    for (const [name, value] of form.entries()) if (typeof value === 'string' && name !== 'csrf') body[name] = value;
    return { csrf: typeof form.get('csrf') === 'string' ? String(form.get('csrf')) : null, body, key: crypto.randomUUID() };
}
