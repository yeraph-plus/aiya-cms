export const OIDC_TRANSACTION_TTL_MS = 5 * 60 * 1000;
export const AUTH_ABSOLUTE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
export const AUTH_IDLE_TTL_MS = 30 * 60 * 1000;

export interface OidcTransaction {
    codeVerifier: string;
    state: string;
    nonce: string;
    returnTo: string;
    locale: 'zh-CN' | 'en';
    createdAt: number;
}

export interface AuthSession {
    subject: string;
    displayName?: string;
    email?: string;
    accessToken: string;
    refreshToken?: string;
    idToken?: string;
    expiresAt: number;
    createdAt: number;
    lastSeenAt: number;
}

export interface PublicSessionUser {
    subject: string;
    displayName?: string;
    email?: string;
}

export function isTransactionExpired(transaction: Pick<OidcTransaction, 'createdAt'>, now = Date.now()): boolean {
    return now - transaction.createdAt > OIDC_TRANSACTION_TTL_MS;
}

export function isAuthSessionExpired(auth: AuthSession, now = Date.now()): boolean {
    return now - auth.createdAt > AUTH_ABSOLUTE_TTL_MS || now - auth.lastSeenAt > AUTH_IDLE_TTL_MS;
}

export function publicSessionUser(auth: AuthSession): PublicSessionUser {
    return {
        subject: auth.subject,
        ...(auth.displayName ? { displayName: auth.displayName } : {}),
        ...(auth.email ? { email: auth.email } : {})
    };
}
