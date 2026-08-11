import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type DimensionDTO = components['schemas']['DimensionDTO'];
export type TermDTO = components['schemas']['TermDTO'];
export type CreateTermInput = components['schemas']['CreateTermInput'];
export type UpdateTermInput = components['schemas']['UpdateTermInput'];
export type AssignBody = components['schemas']['AssignBody'];
export type TargetTermsDTO = paths['/api/v1/admin/taxonomy/targets/{target_type}/{target_id}/terms']['get']['responses'][200]['content']['application/json'];

export async function fetchDimensions(signal?: AbortSignal): Promise<DimensionDTO[]> {
    return getApi().get('/api/v1/admin/taxonomy/dimensions', undefined, signal);
}

export async function fetchTerms(dimensionKey: string, signal?: AbortSignal): Promise<TermDTO[]> {
    return getApi().get(apiPath('/api/v1/admin/taxonomy/dimensions/{dimension_key}/terms', { dimension_key: dimensionKey }), undefined, signal);
}

export async function createTerm(dimensionKey: string, body: CreateTermInput, signal?: AbortSignal): Promise<TermDTO> {
    return getApi().post(apiPath('/api/v1/admin/taxonomy/dimensions/{dimension_key}/terms', { dimension_key: dimensionKey }), body, { signal });
}

export async function updateTerm(termId: string, body: UpdateTermInput, signal?: AbortSignal): Promise<TermDTO> {
    return getApi().patch(apiPath('/api/v1/admin/taxonomy/terms/{term_id}', { term_id: termId }), body, { signal });
}

export async function archiveTerm(termId: string, signal?: AbortSignal): Promise<TermDTO> {
    return getApi().post(apiPath('/api/v1/admin/taxonomy/terms/{term_id}/archive', { term_id: termId }), undefined, { signal });
}

export async function fetchTargetTerms(targetType: string, targetId: string, signal?: AbortSignal): Promise<TargetTermsDTO> {
    return getApi().get(apiPath('/api/v1/admin/taxonomy/targets/{target_type}/{target_id}/terms', { target_type: targetType, target_id: targetId }), undefined, signal);
}

export async function assignTerms(targetType: string, targetId: string, body: AssignBody, signal?: AbortSignal): Promise<void> {
    return getApi().put(apiPath('/api/v1/admin/taxonomy/targets/{target_type}/{target_id}/terms', { target_type: targetType, target_id: targetId }), body, { signal });
}

export async function removeTargetTerms(targetType: string, targetId: string, signal?: AbortSignal): Promise<void> {
    return getApi().delete(apiPath('/api/v1/admin/taxonomy/targets/{target_type}/{target_id}/terms', { target_type: targetType, target_id: targetId }), undefined, signal);
}
