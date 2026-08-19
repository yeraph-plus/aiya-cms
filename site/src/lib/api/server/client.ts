import type { APIContext } from 'astro';
import createClient from 'openapi-fetch';

import type { paths } from '@/lib/api/generated/schema';
import { assertUserApiPath } from '@/lib/api/paths';
import { currentAuth, forceRefreshAuth } from '@/lib/auth/server/oidc';
import { loadServerConfig } from '@/lib/config/server';

export type SiteSession = NonNullable<APIContext['session']>;

export function createGuardedServerFetch(session: SiteSession | undefined, requestId: string): typeof fetch {
    const { apiOrigin } = loadServerConfig();
    return async (input, init) => {
        const original = new Request(new URL(input instanceof Request ? input.url : String(input), apiOrigin), init);
        const target = new URL(original.url, apiOrigin);
        if (target.origin !== new URL(apiOrigin).origin) throw new Error('User API request origin is not allowed');
        assertUserApiPath(target.pathname);

        const send = async (accessToken?: string) => {
            const headers = new Headers(original.headers);
            headers.set('X-Request-ID', requestId);
            headers.set('Accept', 'application/json');
            if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
            return fetch(new Request(original.clone(), { headers }));
        };

        const auth = session ? await currentAuth(session) : null;
        let response = await send(auth?.accessToken);
        if (response.status === 401 && auth?.refreshToken) {
            const refreshed = session ? await forceRefreshAuth(session) : null;
            if (refreshed) response = await send(refreshed.accessToken);
        }
        return response;
    };
}

export function createServerApiClient(session: SiteSession | undefined, requestId: string) {
    const { apiOrigin } = loadServerConfig();
    const guardedFetch = createGuardedServerFetch(session, requestId);

    return createClient<paths>({ baseUrl: apiOrigin, fetch: guardedFetch });
}
