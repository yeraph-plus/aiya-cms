import { timingSafeEqual } from 'node:crypto';

import type { APIContext } from 'astro';
import * as oidc from 'openid-client';

import { loadServerConfig } from '@/lib/config/server';

type SiteSession = NonNullable<APIContext['session']>;

function equalSecret(left: string, right: string): boolean {
    const leftBytes = Buffer.from(left);
    const rightBytes = Buffer.from(right);
    return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

export async function csrfToken(session: SiteSession): Promise<string> {
    const existing = await session.get('csrfToken');
    if (existing) return existing;
    const created = oidc.randomState();
    session.set('csrfToken', created);
    return created;
}

export async function verifySameOriginForm(
    request: Request,
    session: SiteSession,
    token: string | null
): Promise<void> {
    const expectedOrigin = loadServerConfig().siteOrigin;
    const origin = request.headers.get('origin');
    if (!origin || origin !== expectedOrigin || new URL(request.url).origin !== expectedOrigin) {
        throw new Error('cross-origin form submission rejected');
    }
    const expectedToken = await session.get('csrfToken');
    if (!token || !expectedToken || !equalSecret(token, expectedToken)) throw new Error('invalid CSRF token');
}
