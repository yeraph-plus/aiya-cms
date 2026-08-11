import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type SubjectDTO = components['schemas']['SubjectDTO'];
export type SubjectPageDTO = components['schemas']['Page_SubjectDTO_'];
export type BanInput = components['schemas']['BanInput'];
export type UserListQuery = NonNullable<paths['/api/v1/admin/users']['get']['parameters']['query']>;

const usersPath = '/api/v1/admin/users' as const;

export async function fetchUsers(query: UserListQuery, signal?: AbortSignal): Promise<SubjectPageDTO> {
    return getApi().get(usersPath, query, signal);
}

export async function fetchUser(userId: string, signal?: AbortSignal): Promise<SubjectDTO> {
    return getApi().get(apiPath('/api/v1/admin/users/{user_id}', { user_id: userId }), undefined, signal);
}

export async function banUser(userId: string, body: BanInput, signal?: AbortSignal): Promise<SubjectDTO> {
    return getApi().post(apiPath('/api/v1/admin/users/{user_id}/ban', { user_id: userId }), body, { signal });
}

export async function unbanUser(userId: string, signal?: AbortSignal): Promise<SubjectDTO> {
    return getApi().post(apiPath('/api/v1/admin/users/{user_id}/unban', { user_id: userId }), undefined, { signal });
}

export async function deleteUser(userId: string, signal?: AbortSignal): Promise<void> {
    return getApi().delete(apiPath('/api/v1/admin/users/{user_id}', { user_id: userId }), undefined, signal);
}
