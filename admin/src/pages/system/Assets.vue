<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import {
    createUploadIntent,
    deleteAsset,
    fetchAssets,
    fetchConfiguredBuckets,
    finalizeUpload,
    registerExternalAsset,
    updateAssetMetadata,
    uploadToProvider,
    type AssetListQuery,
    type AssetPageDTO,
    type AssetRefDTO,
    type CreateUploadIntentResult
} from '@/api/assets';
import { errorMessage } from '@/api/errors';
import { hasCapability } from '@/auth/session';
import ConfirmAction from '@/components/feedback/ConfirmAction.vue';
import PageState from '@/components/feedback/PageState.vue';
import FilterBar from '@/components/data/FilterBar.vue';
import ListPanel from '@/components/data/ListPanel.vue';
import PageShell from '@/components/shell/PageShell.vue';
import FormDialogShell from '@/components/shell/FormDialogShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t, locale } = useI18n();
const stateOptions = ['pending', 'ready', 'failed', 'deleted'];
const filters = reactive({ state: null as string | null, search: '' });
const result = ref<AssetPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const selectedFile = ref<File | null>(null);
const bucket = ref('');
const configuredBuckets = ref<string[]>([]);
const uploadError = ref<unknown>(null);
const uploading = ref(false);
const pendingIntent = ref<CreateUploadIntentResult | null>(null);
const uploadStage = ref<'new' | 'uploaded'>('new');
const selectedAsset = ref<AssetRefDTO | null>(null);
const assetDialogVisible = ref(false);
const registerDialogVisible = ref(false);
const saving = ref(false);
const formError = ref<unknown>(null);
const altText = ref('');
const registerForm = reactive({
    providerKey: 's3',
    bucket: '',
    objectKey: '',
    mimeType: 'application/octet-stream',
    byteSize: 0,
    altText: ''
});
const canUpload = computed(() => hasCapability('assets.upload'));
const canManage = computed(() => hasCapability('assets.manage'));
const canDelete = computed(() => hasCapability('assets.delete'));

function query(): AssetListQuery {
    return {
        page: page.value,
        size: size.value,
        state: filters.state || undefined,
        search: filters.search.trim() || undefined
    };
}

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchAssets(query());
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function applyFilters(): void {
    page.value = 1;
    void load();
}

function refresh(): void {
    void load();
}

function onPage(value: number): void {
    page.value = value;
    void load();
}

function onSize(value: number): void {
    size.value = value;
    page.value = 1;
    void load();
}

function onFileSelected(event: Event): void {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) return;
    selectedFile.value = input.files?.[0] ?? null;
    uploadError.value = null;
    pendingIntent.value = null;
    uploadStage.value = 'new';
}

async function upload(): Promise<void> {
    const file = selectedFile.value;
    if (!file) return;
    uploading.value = true;
    uploadError.value = null;
    try {
        const intent =
            pendingIntent.value ??
            (await createUploadIntent({
                provider_key: 's3',
                bucket: bucket.value.trim() || undefined,
                mime_types: [file.type || 'application/octet-stream'],
                content_length_max: file.size
            }));
        pendingIntent.value = intent;
        if (uploadStage.value === 'new') {
            await uploadToProvider(intent, file);
            uploadStage.value = 'uploaded';
        }
        await finalizeUpload(intent.intent_id);
        selectedFile.value = null;
        pendingIntent.value = null;
        uploadStage.value = 'new';
        await load();
    } catch (caught) {
        uploadError.value = caught;
    } finally {
        uploading.value = false;
    }
}

function openAsset(asset: AssetRefDTO): void {
    selectedAsset.value = asset;
    altText.value = asset.alt_text ?? '';
    formError.value = null;
    assetDialogVisible.value = true;
}

async function saveMetadata(): Promise<void> {
    if (!selectedAsset.value) return;
    saving.value = true;
    formError.value = null;
    try {
        const updated = await updateAssetMetadata(selectedAsset.value.id, {
            alt_text: altText.value || null
        });
        selectedAsset.value = updated;
        assetDialogVisible.value = false;
        await load();
    } catch (caught) {
        formError.value = caught;
    } finally {
        saving.value = false;
    }
}

function openRegister(): void {
    registerForm.objectKey = '';
    registerForm.mimeType = 'application/octet-stream';
    registerForm.byteSize = 0;
    registerForm.altText = '';
    formError.value = null;
    registerDialogVisible.value = true;
}

async function registerAsset(): Promise<void> {
    saving.value = true;
    formError.value = null;
    try {
        await registerExternalAsset({
            provider_key: registerForm.providerKey,
            bucket: registerForm.bucket.trim() || undefined,
            object_key: registerForm.objectKey,
            mime_type: registerForm.mimeType,
            byte_size: registerForm.byteSize,
            alt_text: registerForm.altText || undefined
        });
        registerDialogVisible.value = false;
        await load();
    } catch (caught) {
        formError.value = caught;
    } finally {
        saving.value = false;
    }
}

async function removeAsset(asset: AssetRefDTO): Promise<void> {
    try {
        await deleteAsset(asset.id);
        await load();
    } catch (caught) {
        error.value = caught;
    }
}

function formatBytes(value: number): string {
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value: string): string {
    return new Intl.DateTimeFormat(locale.value, {
        dateStyle: 'medium',
        timeStyle: 'short'
    }).format(new Date(value));
}

onMounted(() => {
    void load();
    void fetchConfiguredBuckets().then((result) => {
        configuredBuckets.value = result.buckets;
    });
});
</script>

<template>
    <PageShell :title="t('routes.system.assets')" :description="t('workbenches.assets.description')" :loading="loading" @refresh="refresh">
        <template #actions>
            <Button v-if="canManage" icon="pi pi-external-link" :label="t('workbenches.assets.registerExternal')" severity="secondary" @click="openRegister" />
        </template>

        <SurfaceCard v-if="canUpload" :title="t('workbenches.assets.uploadObject')" :description="t('workbenches.assets.uploadHint')" compact>
            <div class="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,1fr)_18rem_auto] md:items-end">
                <div class="flex flex-col gap-2">
                    <label for="asset-file" class="font-medium">{{ t('workbenches.assets.file') }}</label>
                    <input id="asset-file" type="file" class="block w-full rounded-border border border-surface-300 p-2 dark:border-surface-600" @change="onFileSelected" />
                    <span v-if="selectedFile" class="text-sm text-muted-color">{{ selectedFile.name }} ({{ formatBytes(selectedFile.size) }})</span>
                </div>
                <div class="flex flex-col gap-2">
                    <label for="asset-bucket" class="font-medium">{{ t('workbenches.assets.bucketOptional') }}</label>
                    <InputText id="asset-bucket" v-model="bucket" :placeholder="t('workbenches.assets.providerDefault')" />
                    <small v-if="configuredBuckets.length" class="text-muted-color">{{ t('workbenches.assets.configured') }}: {{ configuredBuckets.join(', ') }}</small>
                </div>
                <Button :label="uploadStage === 'uploaded' ? t('workbenches.assets.retryFinalize') : t('common.upload')" icon="pi pi-upload" :loading="uploading" :disabled="!selectedFile" @click="upload" />
            </div>
            <Message v-if="uploadError" severity="error" :closable="false">{{ errorMessage(uploadError) }}</Message>
        </SurfaceCard>

        <SurfaceCard>
            <FilterBar :label="t('common.applyFilters')" @submit="applyFilters">
                <div class="flex min-w-52 flex-col gap-2">
                    <label for="asset-state" class="font-medium">{{ t('workbenches.assets.state') }}</label>
                    <Select id="asset-state" v-model="filters.state" :options="stateOptions" show-clear :placeholder="t('common.all')" fluid />
                </div>
                <div class="flex min-w-64 flex-col gap-2">
                    <label for="asset-search" class="font-medium">{{ t('workbenches.assets.objectKey') }}</label>
                    <InputText id="asset-search" v-model="filters.search" :placeholder="t('workbenches.assets.searchObjectKey')" />
                </div>
            </FilterBar>
        </SurfaceCard>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="result && result.total === 0" state="empty" :title="t('workbenches.assets.empty')" :description="t('workbenches.assets.emptyDescription')" />
        <ListPanel v-else-if="result">
            <PagedTable :value="result.items" :loading="loading" :total-records="result.total" :page="result.page" :size="result.size" @update:page="onPage" @update:size="onSize">
                <Column field="object_key" :header="t('workbenches.assets.objectKey')" style="min-width: 20rem" />
                <Column field="bucket" :header="t('workbenches.assets.bucket')" style="min-width: 12rem">
                    <template #body="{ data }">{{ data.bucket || '-' }}</template>
                </Column>
                <Column field="mime_type" :header="t('workbenches.assets.mimeType')" style="min-width: 13rem" />
                <Column field="byte_size" :header="t('workbenches.assets.size')" style="min-width: 8rem">
                    <template #body="{ data }">{{ formatBytes(data.byte_size) }}</template>
                </Column>
                <Column field="state" :header="t('workbenches.assets.state')" style="min-width: 8rem">
                    <template #body="{ data }"><StatusTag :value="data.state" /></template>
                </Column>
                <Column field="created_at" :header="t('workbenches.assets.created')" style="min-width: 13rem">
                    <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
                </Column>
                <Column :header="t('common.actions')" style="width: 12rem">
                    <template #body="{ data }">
                        <div class="flex flex-wrap gap-1">
                            <Button v-if="canManage" :label="t('common.edit')" text icon="pi pi-pencil" @click="openAsset(data)" />
                            <ConfirmAction v-if="canDelete && data.state === 'ready'" :label="t('common.delete')" severity="danger" :message="t('workbenches.assets.deleteConfirm')" @confirmed="removeAsset(data)" />
                        </div>
                    </template>
                </Column>
            </PagedTable>
        </ListPanel>

        <FormDialogShell v-model="assetDialogVisible" :title="t('workbenches.assets.metadata')">
            <form class="flex flex-col gap-4" @submit.prevent="saveMetadata">
                <Message v-if="formError" severity="error" :closable="false">{{ errorMessage(formError) }}</Message>
                <div class="text-sm text-muted-color">
                    {{ selectedAsset?.object_key }}
                </div>
                <div class="flex flex-col gap-2">
                    <label for="asset-alt-text" class="font-medium">{{ t('workbenches.assets.altText') }}</label>
                    <InputText id="asset-alt-text" v-model="altText" maxlength="500" />
                </div>
                <div class="flex justify-end gap-2">
                    <Button type="button" :label="t('common.cancel')" severity="secondary" text @click="assetDialogVisible = false" />
                    <Button type="submit" :label="t('common.save')" icon="pi pi-check" :loading="saving" />
                </div>
            </form>
        </FormDialogShell>

        <FormDialogShell v-model="registerDialogVisible" :title="t('workbenches.assets.externalTitle')">
            <form class="flex flex-col gap-4" @submit.prevent="registerAsset">
                <Message v-if="formError" severity="error" :closable="false">{{ errorMessage(formError) }}</Message>
                <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <div class="flex flex-col gap-2">
                        <label for="register-provider" class="font-medium">{{ t('workbenches.assets.provider') }}</label>
                        <InputText id="register-provider" v-model="registerForm.providerKey" required />
                    </div>
                    <div class="flex flex-col gap-2">
                        <label for="register-bucket" class="font-medium">{{ t('workbenches.assets.bucket') }}</label>
                        <InputText id="register-bucket" v-model="registerForm.bucket" />
                    </div>
                </div>
                <div class="flex flex-col gap-2">
                    <label for="register-key" class="font-medium">{{ t('workbenches.assets.objectKey') }}</label>
                    <InputText id="register-key" v-model="registerForm.objectKey" required maxlength="500" />
                </div>
                <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <div class="flex flex-col gap-2">
                        <label for="register-mime" class="font-medium">{{ t('workbenches.assets.mimeType') }}</label>
                        <InputText id="register-mime" v-model="registerForm.mimeType" required />
                    </div>
                    <div class="flex flex-col gap-2">
                        <label for="register-size" class="font-medium">{{ t('workbenches.assets.byteSize') }}</label>
                        <InputNumber id="register-size" v-model="registerForm.byteSize" :min="0" fluid />
                    </div>
                </div>
                <div class="flex flex-col gap-2">
                    <label for="register-alt" class="font-medium">{{ t('workbenches.assets.altText') }}</label>
                    <InputText id="register-alt" v-model="registerForm.altText" maxlength="500" />
                </div>
                <div class="flex justify-end gap-2">
                    <Button type="button" :label="t('common.cancel')" severity="secondary" text @click="registerDialogVisible = false" />
                    <Button type="submit" :label="t('common.register')" icon="pi pi-check" :loading="saving" />
                </div>
            </form>
        </FormDialogShell>
    </PageShell>
</template>
