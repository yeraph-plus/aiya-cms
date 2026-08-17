import type { components, paths } from './schema';
import { apiPath, getApi } from './index';

export type AssetRefDTO = components['schemas']['AssetRefDTO'];
export type AssetPageDTO = components['schemas']['AssetPageDTO'];
export type AssetListQuery = NonNullable<paths['/api/v1/admin/assets']['get']['parameters']['query']>;
export type CreateUploadIntentInput = components['schemas']['CreateUploadIntentInput'];
export type CreateUploadIntentResult = components['schemas']['CreateUploadIntentResult'];
export type FinalizeResultDTO = components['schemas']['FinalizeResultDTO'];
export type RegisterExternalAssetInput = components['schemas']['RegisterExternalAssetInput'];
export type UpdateAssetMetadataInput = components['schemas']['UpdateAssetMetadataInput'];
export type ConfiguredBucketsDTO = components['schemas']['ConfiguredBucketsDTO'];

const assetsPath = '/api/v1/admin/assets' as const;

export async function fetchAssets(query: AssetListQuery = {}, signal?: AbortSignal): Promise<AssetPageDTO> {
    return getApi().get(assetsPath, query, signal);
}

export async function fetchConfiguredBuckets(signal?: AbortSignal): Promise<ConfiguredBucketsDTO> {
    return getApi().get('/api/v1/admin/assets/buckets', undefined, signal);
}

export async function fetchAsset(assetId: string, signal?: AbortSignal): Promise<AssetRefDTO> {
    return getApi().get(apiPath('/api/v1/admin/assets/{asset_id}', { asset_id: assetId }), undefined, signal);
}

export async function createUploadIntent(body: CreateUploadIntentInput, signal?: AbortSignal): Promise<CreateUploadIntentResult> {
    return getApi().post('/api/v1/admin/assets/upload-intents', body, { signal });
}

export async function finalizeUpload(intentId: string, signal?: AbortSignal): Promise<FinalizeResultDTO> {
    return getApi().post(
        apiPath('/api/v1/admin/assets/upload-intents/{intent_id}/finalize', {
            intent_id: intentId
        }),
        undefined,
        { signal }
    );
}

export async function uploadToProvider(intent: CreateUploadIntentResult, file: File, signal?: AbortSignal): Promise<void> {
    const response = await fetch(intent.upload_url, {
        method: 'PUT',
        headers: intent.headers,
        body: file,
        signal
    });
    if (!response.ok) throw new Error('Provider upload failed.');
}

export async function registerExternalAsset(body: RegisterExternalAssetInput, signal?: AbortSignal): Promise<AssetRefDTO> {
    return getApi().post(assetsPath, body, { signal });
}

export async function updateAssetMetadata(assetId: string, body: UpdateAssetMetadataInput, signal?: AbortSignal): Promise<AssetRefDTO> {
    return getApi().patch(apiPath('/api/v1/admin/assets/{asset_id}', { asset_id: assetId }), body, { signal });
}

export async function deleteAsset(assetId: string, signal?: AbortSignal): Promise<void> {
    return getApi().delete(apiPath('/api/v1/admin/assets/{asset_id}', { asset_id: assetId }), undefined, signal);
}

export async function waitForAsset(objectKey: string, options: { attempts?: number; delayMs?: number; signal?: AbortSignal } = {}): Promise<AssetRefDTO> {
    const attempts = options.attempts ?? 20;
    const delayMs = options.delayMs ?? 500;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
        const page = await fetchAssets({ page: 1, size: 20, search: objectKey }, options.signal);
        const asset = page.items.find((item) => item.object_key === objectKey);
        if (asset) return asset;
        if (attempt + 1 < attempts) {
            await new Promise<void>((resolve, reject) => {
                const timer = window.setTimeout(resolve, delayMs);
                options.signal?.addEventListener(
                    'abort',
                    () => {
                        window.clearTimeout(timer);
                        reject(options.signal?.reason ?? new DOMException('Aborted', 'AbortError'));
                    },
                    { once: true }
                );
            });
        }
    }
    throw new Error('Upload finalized but the asset is not observable yet. Refresh and retry.');
}
