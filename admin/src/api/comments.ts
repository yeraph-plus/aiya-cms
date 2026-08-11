import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type CommentDTO = components['schemas']['CommentDTO'];
export type CommentPageDTO = components['schemas']['Page_CommentDTO_'];
export type RejectCommentInput = components['schemas']['RejectCommentInput'];
export type DeleteCommentInput = components['schemas']['DeleteCommentInput'];
export type CommentQuery = NonNullable<paths['/api/v1/admin/comments']['get']['parameters']['query']>;

export async function fetchComments(query?: CommentQuery, signal?: AbortSignal): Promise<CommentPageDTO> {
    return getApi().get('/api/v1/admin/comments', query, signal);
}

export async function fetchComment(commentId: string, signal?: AbortSignal): Promise<CommentDTO> {
    return getApi().get(apiPath('/api/v1/admin/comments/{comment_id}', { comment_id: commentId }), undefined, signal);
}

export async function approveComment(commentId: string, signal?: AbortSignal): Promise<CommentDTO> {
    return getApi().post(apiPath('/api/v1/admin/comments/{comment_id}/approve', { comment_id: commentId }), undefined, { signal });
}

export async function rejectComment(commentId: string, body: RejectCommentInput, signal?: AbortSignal): Promise<CommentDTO> {
    return getApi().post(apiPath('/api/v1/admin/comments/{comment_id}/reject', { comment_id: commentId }), body, { signal });
}

export async function deleteComment(commentId: string, body: DeleteCommentInput = {}, signal?: AbortSignal): Promise<CommentDTO> {
    return getApi().post(apiPath('/api/v1/admin/comments/{comment_id}/delete', { comment_id: commentId }), body, { signal });
}
