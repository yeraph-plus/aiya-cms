import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type DiscussionDTO = components['schemas']['DiscussionDTO'];
export type DiscussionPageDTO = components['schemas']['CommunityPageDTO_DiscussionDTO_'];
export type PostDTO = components['schemas']['PostDTO'];
export type PostPageDTO = components['schemas']['CommunityPageDTO_PostDTO_'];
export type TagDTO = components['schemas']['TagDTO'];
export type CreateTagInput = components['schemas']['CreateTagInput'];
export type UpdateTagInput = components['schemas']['UpdateTagInput'];
export type ReplaceDiscussionTagsInput = components['schemas']['ReplaceDiscussionTagsInput'];
export type ReorderTagsInput = components['schemas']['ReorderTagsInput'];
export type DiscussionQuery = NonNullable<paths['/api/v1/admin/community/discussions']['get']['parameters']['query']>;
export type PostQuery = NonNullable<paths['/api/v1/admin/community/posts']['get']['parameters']['query']>;

export async function fetchDiscussions(query?: DiscussionQuery, signal?: AbortSignal): Promise<DiscussionPageDTO> {
    return getApi().get('/api/v1/admin/community/discussions', query, signal);
}

export async function fetchDiscussion(discussionId: string, signal?: AbortSignal): Promise<DiscussionDTO> {
    return getApi().get(
        apiPath('/api/v1/admin/community/discussions/{discussion_id}', {
            discussion_id: discussionId
        }),
        undefined,
        signal
    );
}

export async function fetchPosts(query?: PostQuery, signal?: AbortSignal): Promise<PostPageDTO> {
    return getApi().get('/api/v1/admin/community/posts', query, signal);
}

export async function publishDiscussion(discussionId: string, signal?: AbortSignal): Promise<DiscussionDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/community/discussions/{discussion_id}/publish', {
            discussion_id: discussionId
        }),
        undefined,
        { signal }
    );
}

export async function hideDiscussion(discussionId: string, signal?: AbortSignal): Promise<DiscussionDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/community/discussions/{discussion_id}/hide', {
            discussion_id: discussionId
        }),
        undefined,
        { signal }
    );
}

export async function restoreDiscussion(discussionId: string, signal?: AbortSignal): Promise<DiscussionDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/community/discussions/{discussion_id}/restore', {
            discussion_id: discussionId
        }),
        undefined,
        { signal }
    );
}

export async function archiveDiscussion(discussionId: string, signal?: AbortSignal): Promise<DiscussionDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/community/discussions/{discussion_id}/archive', {
            discussion_id: discussionId
        }),
        undefined,
        { signal }
    );
}

export async function lockDiscussion(discussionId: string, signal?: AbortSignal): Promise<DiscussionDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/community/discussions/{discussion_id}/lock', {
            discussion_id: discussionId
        }),
        undefined,
        { signal }
    );
}

export async function unlockDiscussion(discussionId: string, signal?: AbortSignal): Promise<DiscussionDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/community/discussions/{discussion_id}/unlock', {
            discussion_id: discussionId
        }),
        undefined,
        { signal }
    );
}

export async function replaceDiscussionTags(discussionId: string, body: ReplaceDiscussionTagsInput, signal?: AbortSignal): Promise<DiscussionDTO> {
    return getApi().put(
        apiPath('/api/v1/admin/community/discussions/{discussion_id}/tags', {
            discussion_id: discussionId
        }),
        body,
        { signal }
    );
}

export async function approvePost(postId: string, signal?: AbortSignal): Promise<PostDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/community/posts/{post_id}/approve', {
            post_id: postId
        }),
        undefined,
        { signal }
    );
}

export async function hidePost(postId: string, signal?: AbortSignal): Promise<PostDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/community/posts/{post_id}/hide', {
            post_id: postId
        }),
        undefined,
        { signal }
    );
}

export async function deletePost(postId: string, signal?: AbortSignal): Promise<PostDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/community/posts/{post_id}/delete', {
            post_id: postId
        }),
        undefined,
        { signal }
    );
}

export async function fetchTags(includeArchived = true, signal?: AbortSignal): Promise<TagDTO[]> {
    return getApi().get('/api/v1/admin/community/tags', { include_archived: includeArchived }, signal);
}

export async function createTag(body: CreateTagInput, signal?: AbortSignal): Promise<TagDTO> {
    return getApi().post('/api/v1/admin/community/tags', body, { signal });
}

export async function updateTag(tagId: string, body: UpdateTagInput, signal?: AbortSignal): Promise<TagDTO> {
    return getApi().patch(apiPath('/api/v1/admin/community/tags/{tag_id}', { tag_id: tagId }), body, { signal });
}

export async function archiveTag(tagId: string, signal?: AbortSignal): Promise<TagDTO> {
    return getApi().post(apiPath('/api/v1/admin/community/tags/{tag_id}/archive', { tag_id: tagId }), undefined, { signal });
}

export async function restoreTag(tagId: string, signal?: AbortSignal): Promise<TagDTO> {
    return getApi().post(apiPath('/api/v1/admin/community/tags/{tag_id}/restore', { tag_id: tagId }), undefined, { signal });
}

export async function reorderTags(body: ReorderTagsInput, signal?: AbortSignal): Promise<TagDTO[]> {
    return getApi().put('/api/v1/admin/community/tags/reorder', body, { signal });
}
