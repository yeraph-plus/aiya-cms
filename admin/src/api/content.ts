import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type ContentDTO = components['schemas']['ContentDTO'];
export type ContentPageDTO = components['schemas']['ContentPageDTO'];
export type ContentListQuery = NonNullable<paths['/api/v1/admin/content']['get']['parameters']['query']>;
export type CreateContentInput = components['schemas']['CreateContentInput'];
export type UpdateContentInput = components['schemas']['UpdateContentInput'];
export type ScheduleContentInput = components['schemas']['ScheduleContentInput'];
export type SetContentPinInput = components['schemas']['SetContentPinInput'];
export type ReplaceReferencesInput = components['schemas']['ReplaceReferencesInput'];
export type ReferenceDTO = components['schemas']['ReferenceDTO'];
export type PurgeResultDTO = components['schemas']['PurgeResultDTO'];

const contentPath = '/api/v1/admin/content' as const;

export async function fetchContent(query: ContentListQuery = {}, signal?: AbortSignal): Promise<ContentPageDTO> {
    return getApi().get(contentPath, query, signal);
}

export async function fetchContentItem(contentId: string, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().get(apiPath('/api/v1/admin/content/{content_id}', { content_id: contentId }), undefined, signal);
}

export async function createContent(body: CreateContentInput, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().post(contentPath, body, { signal });
}

export async function updateContent(contentId: string, body: UpdateContentInput, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().patch(apiPath('/api/v1/admin/content/{content_id}', { content_id: contentId }), body, { signal });
}

export async function submitContent(contentId: string, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/content/{content_id}/submit', {
            content_id: contentId
        }),
        undefined,
        { signal }
    );
}

export async function rejectContent(contentId: string, reason: string | null, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/content/{content_id}/reject', {
            content_id: contentId
        }),
        { reason },
        { signal }
    );
}

export async function scheduleContent(contentId: string, body: ScheduleContentInput, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/content/{content_id}/schedule', {
            content_id: contentId
        }),
        body,
        { signal }
    );
}

export async function unscheduleContent(contentId: string, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/content/{content_id}/unschedule', {
            content_id: contentId
        }),
        undefined,
        { signal }
    );
}

export async function publishContent(contentId: string, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/content/{content_id}/publish', {
            content_id: contentId
        }),
        undefined,
        { signal }
    );
}

export async function archiveContent(contentId: string, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/content/{content_id}/archive', {
            content_id: contentId
        }),
        undefined,
        { signal }
    );
}

export async function restoreContent(contentId: string, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/content/{content_id}/restore', {
            content_id: contentId
        }),
        undefined,
        { signal }
    );
}

export async function setContentPin(contentId: string, body: SetContentPinInput, signal?: AbortSignal): Promise<ContentDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/content/{content_id}/pin', {
            content_id: contentId
        }),
        body,
        { signal }
    );
}

export async function purgeContent(contentId: string, dryRun = false, signal?: AbortSignal): Promise<PurgeResultDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/content/{content_id}/purge', {
            content_id: contentId
        }),
        undefined,
        {
            query: { dry_run: dryRun },
            signal
        }
    );
}

export async function fetchReferences(contentId: string, signal?: AbortSignal): Promise<ReferenceDTO[]> {
    return getApi().get(
        apiPath('/api/v1/admin/content/{content_id}/references', {
            content_id: contentId
        }),
        undefined,
        signal
    );
}

export async function replaceReferences(contentId: string, body: ReplaceReferencesInput, signal?: AbortSignal): Promise<void> {
    return getApi().put(
        apiPath('/api/v1/admin/content/{content_id}/references', {
            content_id: contentId
        }),
        body,
        { signal }
    );
}
