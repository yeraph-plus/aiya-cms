import type { APIRoute } from 'astro';

import { communityMutation, mutationForm, type CommunityMutation } from '@/lib/community/bff';

async function redirectFor(request: Request, location: string, response: Response): Promise<Response> {
    if ((request.headers.get('accept') ?? '').includes('application/json')) return response;
    if (!response.ok) return response;
    if (location === '/community/d/' && (response.headers.get('content-type') ?? '').includes('json')) {
        const created = (await response.clone().json()) as { id?: string };
        if (created.id) location = `/community/d/${created.id}`;
    }
    return Response.redirect(new URL(location, request.url), 303);
}

function mutationFromPath(path: string[], method: string, body: Record<string, string>): CommunityMutation | null {
    if (path.length === 1 && path[0] === 'discussions' && method === 'POST')
        return { method: 'POST', path: '/api/v1/community/discussions', body: { title: body.title ?? '', body: body.body ?? '', template_key: body.template_key ?? 'general' } };
    if (path.length === 3 && path[0] === 'discussions' && path[2] === 'replies' && method === 'POST')
        return { method: 'POST', path: `/api/v1/community/discussions/${path[1]}/replies`, body: { body: body.body ?? '' } };
    if (path.length === 2 && path[0] === 'discussions' && (method === 'PATCH' || method === 'POST'))
        return { method: 'PATCH', path: `/api/v1/community/discussions/${path[1]}`, body: { ...(body.title ? { title: body.title } : {}), expected_version: Number(body.expected_version) } };
    if (path.length === 2 && path[0] === 'posts' && (method === 'PATCH' || method === 'POST'))
        return { method: 'PATCH', path: `/api/v1/community/posts/${path[1]}`, body: { body: body.body ?? '', expected_version: Number(body.expected_version) } };
    return null;
}

export const ALL: APIRoute = async (context) => {
    const path = context.params.path?.split('/').filter(Boolean) ?? [];
    const parsed = context.request.method === 'POST' && !(context.request.headers.get('content-type') ?? '').includes('json')
        ? await mutationForm(context.request)
        : { csrf: context.request.headers.get('X-CSRF-Token'), body: (await context.request.json()) as Record<string, string>, key: crypto.randomUUID() };
    const mutation = mutationFromPath(path, context.request.method, parsed.body);
    if (!mutation) return new Response('Not found', { status: 404 });
    const response = await communityMutation(
        context,
        mutation,
        parsed.csrf,
        context.request.headers.get('Idempotency-Key') ?? parsed.key
    );
    return redirectFor(context.request, path[0] === 'posts' ? '/community' : `/community/d/${path[1] ?? ''}`, response);
};
