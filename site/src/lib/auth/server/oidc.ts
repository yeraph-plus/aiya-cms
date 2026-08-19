import { createHash } from 'node:crypto';

import type { APIContext } from 'astro';
import * as oidc from 'openid-client';

import {
    type AuthSession,
    type OidcTransaction,
    isAuthSessionExpired,
    isTransactionExpired,
    publicSessionUser
} from '@/lib/auth/session';
import { loadServerConfig } from '@/lib/config/server';
import type { Locale } from '@/lib/i18n';
import { safeReturnTo } from '@/lib/routing/routes';

type SiteSession = NonNullable<APIContext['session']>;

const ACCESS_TOKEN_REFRESH_WINDOW_MS = 60_000;
const refreshes = new Map<string, Promise<AuthSession>>();
let configurationPromise: Promise<oidc.Configuration> | undefined;

export class AuthFlowError extends Error {
    constructor(
        public readonly code: 'transaction_missing' | 'transaction_expired' | 'callback_invalid' | 'session_expired',
        message: string
    ) {
        super(message);
        this.name = 'AuthFlowError';
    }
}

async function configuration(): Promise<oidc.Configuration> {
    if (!configurationPromise) {
        const config = loadServerConfig();
        const options = config.environment === 'production' ? undefined : { execute: [oidc.allowInsecureRequests] };
        configurationPromise = oidc
            .discovery(
                new URL(config.oidcIssuer),
                config.oidcClientId,
                undefined,
                oidc.ClientSecretBasic(config.oidcClientSecret),
                options
            )
            .catch((error: unknown) => {
                configurationPromise = undefined;
                throw error;
            });
    }
    return configurationPromise;
}

function refreshKey(refreshToken: string): string {
    return createHash('sha256').update(refreshToken).digest('hex');
}

function authFromTokens(
    tokens: oidc.TokenEndpointResponse & oidc.TokenEndpointResponseHelpers,
    previous?: AuthSession
): AuthSession {
    const claims = tokens.claims();
    const subject = claims?.sub ?? previous?.subject;
    if (!subject) throw new AuthFlowError('callback_invalid', 'OIDC token response carries no subject');
    const now = Date.now();
    return {
        subject,
        ...(typeof claims?.name === 'string'
            ? { displayName: claims.name }
            : previous?.displayName
              ? { displayName: previous.displayName }
              : {}),
        ...(typeof claims?.email === 'string'
            ? { email: claims.email }
            : previous?.email
              ? { email: previous.email }
              : {}),
        accessToken: tokens.access_token,
        ...(tokens.refresh_token
            ? { refreshToken: tokens.refresh_token }
            : previous?.refreshToken
              ? { refreshToken: previous.refreshToken }
              : {}),
        ...(tokens.id_token ? { idToken: tokens.id_token } : previous?.idToken ? { idToken: previous.idToken } : {}),
        expiresAt: now + Math.max(1, tokens.expires_in ?? 300) * 1000,
        createdAt: previous?.createdAt ?? now,
        lastSeenAt: now
    };
}

async function refresh(previous: AuthSession): Promise<AuthSession> {
    if (!previous.refreshToken) throw new AuthFlowError('session_expired', 'OIDC refresh token is unavailable');
    const key = refreshKey(previous.refreshToken);
    const existing = refreshes.get(key);
    if (existing) return existing;

    const pending = (async () => {
        const tokens = await oidc.refreshTokenGrant(await configuration(), previous.refreshToken!);
        return authFromTokens(tokens, previous);
    })();
    refreshes.set(key, pending);
    try {
        return await pending;
    } finally {
        refreshes.delete(key);
    }
}

export async function beginAuthorization(session: SiteSession, returnTo: string | null, locale: Locale): Promise<URL> {
    const config = loadServerConfig();
    const codeVerifier = oidc.randomPKCECodeVerifier();
    const transaction: OidcTransaction = {
        codeVerifier,
        state: oidc.randomState(),
        nonce: oidc.randomNonce(),
        returnTo: safeReturnTo(returnTo, locale === 'en' ? '/en' : '/'),
        locale,
        createdAt: Date.now()
    };
    await session.regenerate();
    session.set('oidcTransaction', transaction);
    return oidc.buildAuthorizationUrl(await configuration(), {
        redirect_uri: config.oidcRedirectUri,
        response_type: 'code',
        scope: config.oidcScope,
        code_challenge: await oidc.calculatePKCECodeChallenge(codeVerifier),
        code_challenge_method: 'S256',
        state: transaction.state,
        nonce: transaction.nonce,
        ui_locales: locale
    });
}

export async function completeAuthorization(session: SiteSession, callbackUrl: URL): Promise<string> {
    const transaction = await session.get('oidcTransaction');
    if (!transaction) throw new AuthFlowError('transaction_missing', 'OIDC transaction is missing');
    if (isTransactionExpired(transaction)) {
        session.delete('oidcTransaction');
        throw new AuthFlowError('transaction_expired', 'OIDC transaction expired');
    }

    try {
        const tokens = await oidc.authorizationCodeGrant(await configuration(), callbackUrl, {
            pkceCodeVerifier: transaction.codeVerifier,
            expectedState: transaction.state,
            expectedNonce: transaction.nonce
        });
        const auth = authFromTokens(tokens);
        await session.regenerate();
        session.delete('oidcTransaction');
        session.set('auth', auth);
        session.set('csrfToken', oidc.randomState());
        return transaction.returnTo;
    } catch (error) {
        session.delete('oidcTransaction');
        if (error instanceof AuthFlowError) throw error;
        throw new AuthFlowError('callback_invalid', 'OIDC callback validation failed');
    }
}

export async function forceRefreshAuth(session: SiteSession): Promise<AuthSession | undefined> {
    const previous = await session.get('auth');
    if (!previous || isAuthSessionExpired(previous)) {
        session.destroy();
        return undefined;
    }
    try {
        const next = await refresh(previous);
        session.set('auth', next);
        return next;
    } catch {
        session.destroy();
        return undefined;
    }
}

export async function currentAuth(session: SiteSession): Promise<AuthSession | undefined> {
    const auth = await session.get('auth');
    if (!auth) return undefined;
    if (isAuthSessionExpired(auth)) {
        session.destroy();
        return undefined;
    }
    if (auth.expiresAt - Date.now() <= ACCESS_TOKEN_REFRESH_WINDOW_MS) return forceRefreshAuth(session);
    if (Date.now() - auth.lastSeenAt > 60_000) {
        const touched = { ...auth, lastSeenAt: Date.now() };
        session.set('auth', touched);
        return touched;
    }
    return auth;
}

export async function currentPublicUser(session: SiteSession) {
    const auth = await currentAuth(session);
    return auth ? publicSessionUser(auth) : undefined;
}

export async function endSession(session: SiteSession): Promise<URL | undefined> {
    const auth = await session.get('auth');
    const config = loadServerConfig();
    let redirect: URL | undefined;
    try {
        if (auth) {
            const client = await configuration();
            if (auth.refreshToken) {
                await oidc.tokenRevocation(client, auth.refreshToken, { tokenTypeHint: 'refresh_token' });
            }
            if (auth.idToken) {
                redirect = oidc.buildEndSessionUrl(client, {
                    id_token_hint: auth.idToken,
                    post_logout_redirect_uri: config.oidcPostLogoutRedirectUri
                });
            }
        }
    } catch {
        // Provider failure must never prevent local session destruction.
    } finally {
        session.destroy();
    }
    return redirect;
}
