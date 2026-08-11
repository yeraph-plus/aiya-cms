import type { components } from './schema';
import { apiPath, getApi } from './index';

export type CapabilityDTO = components['schemas']['CapabilityDTO'];
export type RoleDTO = components['schemas']['RoleDTO'];
export type CreateRoleBody = components['schemas']['CreateRoleBody'];
export type AssignRoleBody = components['schemas']['AssignRoleBody'];
export type ReplaceCapabilitiesBody = components['schemas']['ReplaceCapabilitiesBody'];
export type GrantSummary = components['schemas']['GrantSummary'];

export async function fetchCapabilities(signal?: AbortSignal): Promise<CapabilityDTO> {
    return getApi().get('/api/v1/admin/capabilities', undefined, signal);
}

export async function fetchRoles(signal?: AbortSignal): Promise<RoleDTO[]> {
    return getApi().get('/api/v1/admin/roles', undefined, signal);
}

export async function createRole(body: CreateRoleBody, signal?: AbortSignal): Promise<RoleDTO> {
    return getApi().post('/api/v1/admin/roles', body, { signal });
}

export async function replaceRoleCapabilities(roleId: string, body: ReplaceCapabilitiesBody, signal?: AbortSignal): Promise<RoleDTO> {
    return getApi().put(apiPath('/api/v1/admin/roles/{role_id}/capabilities', { role_id: roleId }), body, { signal });
}

export async function assignRole(roleId: string, body: AssignRoleBody, signal?: AbortSignal): Promise<GrantSummary> {
    return getApi().post(apiPath('/api/v1/admin/roles/{role_id}/assign', { role_id: roleId }), body, { signal });
}

export async function revokeRole(roleId: string, body: AssignRoleBody, signal?: AbortSignal): Promise<void> {
    await getApi().post(apiPath('/api/v1/admin/roles/{role_id}/revoke', { role_id: roleId }), body, { signal });
}

export async function deleteRole(roleId: string, signal?: AbortSignal): Promise<void> {
    await getApi().delete(apiPath('/api/v1/admin/roles/{role_id}', { role_id: roleId }), undefined, signal);
}
