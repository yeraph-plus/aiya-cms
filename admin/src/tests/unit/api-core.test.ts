import { describe, expect, it } from 'vitest';
import { ApiError, errorMessage, requestIdOf } from '@/api/errors';
import { pageCount, pageQuery, isPageDTO } from '@/api/pagination';

describe('ApiError', () => {
    it('extracts status, code, body and request id', () => {
        const error = new ApiError(409, { code: 'version_conflict', detail: 'conflict' }, 'req-123');
        expect(error.status).toBe(409);
        expect(error.code).toBe('version_conflict');
        expect(error.requestId).toBe('req-123');
    });

    it('maps safe messages without leaking payloads', () => {
        expect(errorMessage(new ApiError(422, { detail: 'invalid input' }))).toBe('invalid input');
        expect(errorMessage(new ApiError(422, { detail: [] }))).toBe('请求参数校验失败');
        expect(errorMessage(new ApiError(401, { detail: 'token expired' }))).toBe('token expired');
        expect(errorMessage(new ApiError(401, null))).toBe('会话已失效，请重新登录');
        expect(errorMessage(new ApiError(403, null))).toBe('权限不足，无法执行该操作');
        expect(errorMessage(new ApiError(404, null))).toBe('请求的资源不存在');
        expect(errorMessage(new ApiError(409, null))).toBe('资源已被他人修改，请刷新后重试');
        expect(errorMessage(new ApiError(500, null))).toBe('服务器内部错误，请稍后重试');
        expect(errorMessage(new Error('boom'))).toBe('请求失败，请检查网络后重试');
    });

    it('requestIdOf only resolves for ApiError', () => {
        expect(requestIdOf(new ApiError(400, null, 'req-1'))).toBe('req-1');
        expect(requestIdOf(new Error('boom'))).toBeUndefined();
    });
});

describe('pagination helpers', () => {
    it('builds 1-based page query', () => {
        expect(pageQuery(2, 25)).toEqual({ page: 2, size: 25 });
    });

    it('computes page count', () => {
        expect(pageCount(0, 10)).toBe(0);
        expect(pageCount(25, 10)).toBe(3);
    });

    it('guards page DTO shape', () => {
        expect(isPageDTO({ items: [], page: 1, size: 10, total: 0 })).toBe(true);
        expect(isPageDTO({ items: 'no' })).toBe(false);
        expect(isPageDTO(null)).toBe(false);
    });
});
