import { OidcClient, UserManager, type UserManagerSettings } from 'oidc-client-ts';
import { env } from '@/env';
import { oidcStateStorage, oidcUserStorage } from './storage';

export const oidcSettings: UserManagerSettings = {
    authority: env.oidcIssuer,
    client_id: env.oidcClientId,
    redirect_uri: env.oidcRedirectUri,
    post_logout_redirect_uri: env.oidcPostLogoutRedirectUri,
    response_type: 'code',
    scope: 'openid profile email',
    automaticSilentRenew: false,
    monitorSession: false,
    loadUserInfo: false,
    stateStore: oidcStateStorage,
    userStore: oidcUserStorage
};

export const userManager = new UserManager(oidcSettings);

const oidcClient = new OidcClient(oidcSettings);

function assertPkceSecurityContext(): void {
    // oidc-client-ts needs Web Crypto for S256; an env flag cannot make an
    // insecure custom HTTP host a browser secure context.
    if (typeof window !== 'undefined' && import.meta.env.MODE !== 'test' && (window.isSecureContext === false || !window.crypto?.subtle)) {
        throw new Error('PKCE 需要 HTTPS 安全上下文；本地 HTTP 请使用 localhost 或 127.0.0.1，不能通过环境变量禁用此要求');
    }
}

export interface LoginFormArgs {
    action: string;
    fields: Record<string, string>;
}

interface LoginResponse {
    redirect_uri?: string;
    error_description?: string;
}

function isLoginResponse(value: unknown): value is LoginResponse {
    return typeof value === 'object' && value !== null;
}

export async function createLoginFormArgs(): Promise<LoginFormArgs> {
    assertPkceSecurityContext();
    const request = await oidcClient.createSigninRequest({});
    const url = new URL(request.url);
    const fields: Record<string, string> = {};
    for (const [key, value] of url.searchParams.entries()) {
        fields[key] = value;
    }
    return { action: `${env.oidcIssuer}/oidc/login`, fields };
}

export async function submitLogin(loginForm: LoginFormArgs, username: string, password: string): Promise<string> {
    const form = new URLSearchParams(loginForm.fields);
    form.set('username', username);
    form.set('password', password);
    const response = await fetch(loginForm.action, {
        method: 'POST',
        headers: {
            Accept: 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        credentials: 'include',
        redirect: 'manual',
        cache: 'no-store',
        body: form
    });

    if (response.type === 'opaqueredirect') {
        throw new Error('OIDC 登录响应未返回前端回调，请检查 backend 配置');
    }
    let body: unknown;
    try {
        body = await response.json();
    } catch {
        throw new Error(`OIDC 登录失败（${response.status}）`);
    }
    if (!response.ok) {
        throw new Error(isLoginResponse(body) && body.error_description ? body.error_description : `OIDC 登录失败（${response.status}）`);
    }
    if (!isLoginResponse(body) || !body.redirect_uri) {
        throw new Error('OIDC 登录未返回前端回调地址');
    }
    return body.redirect_uri;
}

export async function signOutRedirect(): Promise<void> {
    await userManager.signoutRedirect();
}
