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
        const message = isRecord(error.body) ? error.body.message : undefined;
        if (typeof message === 'string') return message;
        const detail = isRecord(error.body) ? error.body.detail : undefined;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail)) return translate('errors.validation');
        if (error.status === 401) return translate('errors.unauthorized');
        if (error.status === 403) return translate('errors.forbidden');
        if (error.status === 404) return translate('errors.notFound');
        if (error.status === 409) return translate('errors.conflict');
        if (error.status >= 500) return translate('errors.server');
        return translate('errors.requestFailed', { status: error.status });
    }
    return translate('errors.network');
}

export function requestIdOf(error: unknown): string | undefined {
    return error instanceof ApiError ? error.requestId : undefined;
}
import { translate } from '@/i18n';
