export class ApiError extends Error {
    readonly status: number;
    readonly body: unknown;
    readonly code?: string;
    readonly requestId?: string;

    constructor(status: number, body: unknown, requestId?: string) {
        super(`API request failed with status ${status}${requestId ? ` (request id: ${requestId})` : ''}`);
        this.name = 'ApiError';
        this.status = status;
        this.body = body;
        this.code = extractCode(body);
        this.requestId = requestId;
    }
}

function extractCode(body: unknown): string | undefined {
    if (isRecord(body) && typeof body.code === 'string') return body.code;
    return undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function errorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        const detail = isRecord(error.body) ? error.body.detail : undefined;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail)) return '请求参数校验失败';
        if (error.status === 401) return '会话已失效，请重新登录';
        if (error.status === 403) return '权限不足，无法执行该操作';
        if (error.status === 404) return '请求的资源不存在';
        if (error.status === 409) return '资源已被他人修改，请刷新后重试';
        if (error.status >= 500) return '服务器内部错误，请稍后重试';
        return `请求失败（${error.status}）`;
    }
    return '请求失败，请检查网络后重试';
}

export function requestIdOf(error: unknown): string | undefined {
    return error instanceof ApiError ? error.requestId : undefined;
}
