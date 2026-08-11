import type { components, paths } from './schema';
import { getApi } from './index';

export type ExecutionEntryDTO = components['schemas']['ExecutionEntryDTO'];
export type ExecutionPageDTO = components['schemas']['Page_ExecutionEntryDTO_'];
export type ExecutionQuery = NonNullable<paths['/api/v1/admin/execution/entries']['get']['parameters']['query']>;

export async function fetchExecutionEntries(query: ExecutionQuery = {}, signal?: AbortSignal): Promise<ExecutionPageDTO> {
    return getApi().get('/api/v1/admin/execution/entries', query, signal);
}
