import type { components } from './schema';
import { apiPath, getApi } from './index';

export type SettingFieldDTO = components['schemas']['SettingFieldDTO'];
export type SettingGroupDTO = components['schemas']['SettingGroupDTO'];
export type UpdateSettingGroupInput = components['schemas']['UpdateSettingGroupInput'];

const groupsPath = '/api/v1/admin/settings/groups' as const;

export async function fetchSettingGroups(signal?: AbortSignal): Promise<SettingGroupDTO[]> {
    return getApi().get(groupsPath, undefined, signal);
}

export async function fetchSettingGroup(groupKey: string, signal?: AbortSignal): Promise<SettingGroupDTO> {
    return getApi().get(
        apiPath('/api/v1/admin/settings/groups/{group_key}', {
            group_key: groupKey
        }),
        undefined,
        signal
    );
}

export async function updateSettingGroup(groupKey: string, body: UpdateSettingGroupInput, signal?: AbortSignal): Promise<SettingGroupDTO> {
    return getApi().put(
        apiPath('/api/v1/admin/settings/groups/{group_key}', {
            group_key: groupKey
        }),
        body,
        { signal }
    );
}

export async function resetSettingGroup(groupKey: string, signal?: AbortSignal): Promise<SettingGroupDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/settings/groups/{group_key}/reset', {
            group_key: groupKey
        }),
        undefined,
        { signal }
    );
}
