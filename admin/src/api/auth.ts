import type { components } from './schema';
import { apiPath, getApi } from './index';

export type AdminSessionDTO = components['schemas']['AdminSessionDTO'];
export type GrantConsentDTO = components['schemas']['GrantConsentDTO'];
export type RegisterInput = components['schemas']['RegisterInput'];
export type VerifyEmailInput = components['schemas']['VerifyEmailInput'];
export type PasswordResetRequestInput = components['schemas']['PasswordResetRequestInput'];
export type PasswordResetConfirmInput = components['schemas']['PasswordResetConfirmInput'];
export type SubjectDTO = components['schemas']['SubjectDTO'];

export async function fetchAdminSession(signal?: AbortSignal): Promise<AdminSessionDTO> {
    return getApi().get('/api/v1/admin/session', undefined, signal);
}

export async function logoutAdminSession(signal?: AbortSignal): Promise<void> {
    await getApi().post('/api/v1/admin/session/logout', undefined, { signal });
}

export async function fetchGrants(signal?: AbortSignal): Promise<GrantConsentDTO[]> {
    return getApi().get('/api/v1/auth/grants', undefined, signal);
}

export async function revokeGrant(clientId: string, signal?: AbortSignal): Promise<void> {
    return getApi().delete(apiPath('/api/v1/auth/grants/{client_id}', { client_id: clientId }), undefined, signal);
}

export async function register(input: RegisterInput, signal?: AbortSignal): Promise<SubjectDTO> {
    return getApi().post('/api/v1/auth/register', input, { signal });
}

export async function verifyEmail(input: VerifyEmailInput, signal?: AbortSignal): Promise<SubjectDTO> {
    return getApi().post('/api/v1/auth/verify-email', input, { signal });
}

export async function requestPasswordReset(input: PasswordResetRequestInput, signal?: AbortSignal): Promise<void> {
    await getApi().post('/api/v1/auth/password-reset/request', input, { signal });
}

export async function confirmPasswordReset(input: PasswordResetConfirmInput, signal?: AbortSignal): Promise<SubjectDTO> {
    return getApi().post('/api/v1/auth/password-reset/confirm', input, {
        signal
    });
}
