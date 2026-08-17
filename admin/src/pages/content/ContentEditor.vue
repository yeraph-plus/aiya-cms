<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute } from 'vue-router';
import {
    archiveContent,
    createContent,
    fetchContentItem,
    fetchReferences,
    purgeContent,
    publishContent,
    rejectContent,
    replaceReferences,
    restoreContent,
    scheduleContent,
    setContentPin,
    submitContent,
    unscheduleContent,
    updateContent,
    type ContentDTO,
    type ReferenceDTO
} from '@/api/content';
import { assignTerms, fetchDimensions, fetchTargetTerms, fetchTerms, type DimensionDTO, type TermDTO } from '@/api/taxonomy';
import { errorMessage } from '@/api/errors';
import { hasCapability } from '@/auth/session';
import ConfirmAction from '@/components/feedback/ConfirmAction.vue';
import PageState from '@/components/feedback/PageState.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t, locale } = useI18n();
const route = useRoute();
const props = withDefaults(defineProps<{ contentId?: string | null; embedded?: boolean }>(), { contentId: null, embedded: false });
const emit = defineEmits<{
    saved: [content: ContentDTO];
    purged: [contentId: string];
}>();
const typeOptions = computed(() => [
    { label: t('workbenches.content.post'), value: 'post' },
    { label: t('workbenches.content.page'), value: 'page' }
]);
const content = ref<ContentDTO | null>(null);
const loading = ref(false);
const saving = ref(false);
const actionLoading = ref(false);
const error = ref<unknown>(null);
const formError = ref<unknown>(null);
const notice = ref('');
const scheduleAt = ref('');
const referenceKind = ref('related');
const referenceTargets = ref('');
const references = ref<ReferenceDTO[]>([]);
const referenceTargetsByKind = reactive<Record<string, string>>({});
const dimensions = ref<DimensionDTO[]>([]);
const taxonomyTerms = reactive<Record<string, TermDTO[]>>({});
const assignments = reactive<Record<string, string[]>>({});
const taxonomyLoading = ref(false);
const taxonomyError = ref<unknown>(null);
const form = reactive({
    typeName: initialType(),
    title: '',
    slug: '',
    body: '',
    excerpt: ''
});

const activeContentId = ref<string | null>(props.contentId);
const activeId = computed(() => activeContentId.value);
const isNew = computed(() => activeId.value === null);
const isPost = computed(() => form.typeName === 'post');
const canWrite = computed(() => hasCapability('content.write'));
const canReadTaxonomy = computed(() => hasCapability('taxonomy.read'));
const canManageTaxonomy = computed(() => hasCapability('taxonomy.manage'));

function initialType(): string {
    const value = route.query.type_name;
    return value === 'page' ? 'page' : 'post';
}

function clearErrors(): void {
    error.value = null;
    formError.value = null;
    taxonomyError.value = null;
}

function fillForm(item: ContentDTO): void {
    form.typeName = item.type_name;
    form.title = item.title;
    form.slug = item.slug;
    form.body = item.body ?? '';
    form.excerpt = item.excerpt ?? '';
    scheduleAt.value = item.publish_at ? toLocalDateTimeInput(item.publish_at) : '';
}

function toLocalDateTimeInput(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const pad = (part: number) => String(part).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

async function loadTaxonomy(): Promise<void> {
    dimensions.value = [];
    for (const key of Object.keys(taxonomyTerms)) delete taxonomyTerms[key];
    for (const key of Object.keys(assignments)) delete assignments[key];
    if (!isPost.value || !canReadTaxonomy.value) return;

    taxonomyLoading.value = true;
    taxonomyError.value = null;
    try {
        dimensions.value = await fetchDimensions();
        await Promise.all(
            dimensions.value.map(async (dimension) => {
                taxonomyTerms[dimension.dimension_key] = await fetchTerms(dimension.dimension_key);
                assignments[dimension.dimension_key] = [];
            })
        );
        if (activeId.value) {
            const current = await fetchTargetTerms('post', activeId.value);
            for (const dimension of dimensions.value) {
                assignments[dimension.dimension_key] = (current[dimension.dimension_key] ?? []).map((term) => term.id);
            }
        }
    } catch (caught) {
        taxonomyError.value = caught;
    } finally {
        taxonomyLoading.value = false;
    }
}

async function loadReferences(): Promise<void> {
    references.value = [];
    referenceTargets.value = '';
    for (const key of Object.keys(referenceTargetsByKind)) delete referenceTargetsByKind[key];
    if (!activeId.value) return;
    try {
        references.value = await fetchReferences(activeId.value);
        for (const item of references.value) {
            const targets = referenceTargetsByKind[item.kind] ? `${referenceTargetsByKind[item.kind]}\n` : '';
            referenceTargetsByKind[item.kind] = `${targets}${item.target_content_id}`;
        }
        if (references.value[0]) referenceKind.value = references.value[0].kind;
        referenceTargets.value = referenceTargetsByKind[referenceKind.value] ?? '';
    } catch (caught) {
        formError.value = caught;
    }
}

watch(referenceKind, (kind) => {
    referenceTargets.value = referenceTargetsByKind[kind] ?? '';
});

async function load(): Promise<void> {
    clearErrors();
    if (isNew.value) {
        form.typeName = initialType();
        await loadTaxonomy();
        return;
    }

    loading.value = true;
    try {
        const item = await fetchContentItem(activeId.value as string);
        content.value = item;
        fillForm(item);
        await Promise.all([loadTaxonomy(), loadReferences()]);
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function newContentBody() {
    return {
        type_name: form.typeName,
        title: form.title,
        slug: form.slug,
        body: form.body || null,
        excerpt: form.excerpt || null,
        data: {}
    };
}

async function save(): Promise<void> {
    saving.value = true;
    formError.value = null;
    notice.value = '';
    try {
        if (isNew.value) {
            const created = await createContent(newContentBody());
            content.value = created;
            activeContentId.value = created.id;
            fillForm(created);
            await loadTaxonomy();
            notice.value = t('workbenches.content.created');
            emit('saved', created);
        } else if (content.value) {
            const updated = await updateContent(content.value.id, {
                expected_version: content.value.version,
                title: form.title,
                body: form.body || null,
                excerpt: form.excerpt || null
            });
            content.value = updated;
            fillForm(updated);
            notice.value = t('workbenches.content.saved');
            emit('saved', updated);
        }
    } catch (caught) {
        formError.value = caught;
    } finally {
        saving.value = false;
    }
}

function singleSelection(dimensionKey: string): string | null {
    return assignments[dimensionKey]?.[0] ?? null;
}

function setSingleSelection(dimensionKey: string, value: string | null): void {
    assignments[dimensionKey] = value ? [value] : [];
}

async function saveTaxonomy(): Promise<void> {
    if (!content.value || !isPost.value || !canManageTaxonomy.value) return;
    actionLoading.value = true;
    formError.value = null;
    try {
        await Promise.all(
            dimensions.value.map((dimension) =>
                assignTerms('post', content.value?.id ?? '', {
                    dimension_key: dimension.dimension_key,
                    term_ids: assignments[dimension.dimension_key] ?? []
                })
            )
        );
        notice.value = t('workbenches.content.taxonomySaved');
    } catch (caught) {
        formError.value = caught;
    } finally {
        actionLoading.value = false;
    }
}

async function saveReferences(): Promise<void> {
    if (!content.value || !canWrite.value) return;
    actionLoading.value = true;
    formError.value = null;
    try {
        const targets = referenceTargets.value
            .split(/[\n,]/u)
            .map((value) => value.trim())
            .filter((value) => value.length > 0);
        await replaceReferences(content.value.id, {
            kind: referenceKind.value,
            targets
        });
        referenceTargetsByKind[referenceKind.value] = targets.join('\n');
        content.value = await fetchContentItem(content.value.id);
        fillForm(content.value);
        await loadReferences();
        notice.value = t('workbenches.content.referencesSaved');
    } catch (caught) {
        formError.value = caught;
    } finally {
        actionLoading.value = false;
    }
}

async function runAction(action: () => Promise<ContentDTO>, successMessage: string): Promise<void> {
    if (!content.value) return;
    actionLoading.value = true;
    formError.value = null;
    try {
        content.value = await action();
        fillForm(content.value);
        notice.value = successMessage;
    } catch (caught) {
        formError.value = caught;
    } finally {
        actionLoading.value = false;
    }
}

async function submit(): Promise<void> {
    await runAction(() => submitContent(content.value?.id ?? ''), t('workbenches.content.submitted'));
}

async function reject(): Promise<void> {
    await runAction(() => rejectContent(content.value?.id ?? '', null), t('workbenches.content.rejected'));
}

async function schedule(): Promise<void> {
    if (!scheduleAt.value) return;
    await runAction(
        () =>
            scheduleContent(content.value?.id ?? '', {
                publish_at: new Date(scheduleAt.value).toISOString()
            }),
        t('workbenches.content.scheduled')
    );
}

async function unschedule(): Promise<void> {
    await runAction(() => unscheduleContent(content.value?.id ?? ''), t('workbenches.content.unscheduled'));
}

async function publish(): Promise<void> {
    await runAction(() => publishContent(content.value?.id ?? ''), t('workbenches.content.published'));
}

async function archive(): Promise<void> {
    await runAction(() => archiveContent(content.value?.id ?? ''), t('workbenches.content.archived'));
}

async function restore(): Promise<void> {
    await runAction(() => restoreContent(content.value?.id ?? ''), t('workbenches.content.restored'));
}

async function togglePin(): Promise<void> {
    if (!content.value) return;
    await runAction(
        () =>
            setContentPin(content.value?.id ?? '', {
                is_pinned: !content.value?.is_pinned,
                pin_rank: content.value?.pin_rank ?? 0
            }),
        content.value.is_pinned ? t('workbenches.content.unpinnedNotice') : t('workbenches.content.pinnedNotice')
    );
}

async function purge(): Promise<void> {
    if (!content.value) return;
    actionLoading.value = true;
    formError.value = null;
    try {
        const purgedContentId = content.value.id;
        await purgeContent(purgedContentId);
        notice.value = t('workbenches.content.purged');
        content.value = null;
        activeContentId.value = null;
        emit('purged', purgedContentId);
    } catch (caught) {
        formError.value = caught;
    } finally {
        actionLoading.value = false;
    }
}

function canAction(capability: string): boolean {
    return hasCapability(capability) && !actionLoading.value;
}

function formatDate(value: string | null | undefined): string {
    return value
        ? new Intl.DateTimeFormat(locale.value, {
              dateStyle: 'medium',
              timeStyle: 'short'
          }).format(new Date(value))
        : '-';
}

watch(
    () => props.contentId,
    (value) => {
        activeContentId.value = value ?? null;
        content.value = null;
        void load();
    },
    { immediate: true }
);
</script>

<template>
    <PageShell :title="isNew ? t('workbenches.content.newTitle') : t('workbenches.content.editTitle')" :description="t('workbenches.content.editorDescription')" :loading="loading" :refreshable="!isNew" @refresh="load">
        <template #actions>
            <Button v-if="canWrite" :label="t('common.save')" icon="pi pi-save" :loading="saving" @click="save" />
        </template>

        <PageState v-if="loading" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" :description="t('workbenches.content.loadFailed')" />
        <template v-else>
            <Message v-if="formError" severity="error" :closable="false">{{ errorMessage(formError) }}</Message>
            <Message v-if="notice" severity="success" :closable="false">{{ notice }}</Message>

            <div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
                <div class="flex flex-col gap-4">
                    <div class="card flex flex-col gap-4">
                        <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                            <div class="flex flex-col gap-2">
                                <label for="content-type" class="font-medium">{{ t('workbenches.content.type') }}</label>
                                <Select id="content-type" v-model="form.typeName" :options="typeOptions" option-label="label" option-value="value" :disabled="!isNew" fluid />
                            </div>
                            <div class="flex flex-col gap-2">
                                <label for="content-version" class="font-medium">{{ t('workbenches.content.version') }}</label>
                                <InputText id="content-version" :model-value="String(content?.version ?? 0)" disabled />
                            </div>
                        </div>
                        <div class="flex flex-col gap-2">
                            <label for="content-title" class="font-medium">{{ t('workbenches.content.title') }}</label>
                            <InputText id="content-title" v-model="form.title" :disabled="!canWrite" maxlength="200" />
                        </div>
                        <div class="flex flex-col gap-2">
                            <label for="content-slug" class="font-medium">{{ t('workbenches.content.slug') }}</label>
                            <InputText id="content-slug" v-model="form.slug" :disabled="!canWrite" maxlength="200" />
                        </div>
                        <div class="flex flex-col gap-2">
                            <label for="content-excerpt" class="font-medium">{{ t('workbenches.content.excerpt') }}</label>
                            <Textarea id="content-excerpt" v-model="form.excerpt" :disabled="!canWrite" rows="3" auto-resize />
                        </div>
                        <div class="flex flex-col gap-2">
                            <label for="content-body" class="font-medium">{{ t('workbenches.content.body') }}</label>
                            <Textarea id="content-body" v-model="form.body" :disabled="!canWrite" rows="10" auto-resize />
                        </div>
                    </div>

                    <div v-if="!isNew && content && content.type_name === 'post' && canReadTaxonomy" class="card flex flex-col gap-4">
                        <div class="flex items-center justify-between gap-3">
                            <div>
                                <h2 class="text-lg font-semibold">
                                    {{ t('workbenches.content.taxonomy') }}
                                </h2>
                                <p class="text-sm text-muted-color">
                                    {{ t('workbenches.content.taxonomyHint') }}
                                </p>
                            </div>
                            <Button v-if="canManageTaxonomy" :label="t('workbenches.content.saveAssignments')" icon="pi pi-check" :loading="actionLoading" @click="saveTaxonomy" />
                        </div>
                        <PageState v-if="taxonomyLoading" state="loading" />
                        <Message v-else-if="taxonomyError" severity="error" :closable="false">{{ errorMessage(taxonomyError) }}</Message>
                        <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2">
                            <div v-for="dimension in dimensions" :key="dimension.dimension_key" class="flex flex-col gap-2">
                                <label :for="`taxonomy-${dimension.dimension_key}`" class="font-medium">{{ dimension.display_name }}</label>
                                <Select
                                    v-if="dimension.selection_mode === 'single'"
                                    :id="`taxonomy-${dimension.dimension_key}`"
                                    :model-value="singleSelection(dimension.dimension_key)"
                                    :options="taxonomyTerms[dimension.dimension_key] ?? []"
                                    option-label="name"
                                    option-value="id"
                                    show-clear
                                    :disabled="!canManageTaxonomy"
                                    @update:model-value="setSingleSelection(dimension.dimension_key, $event)"
                                />
                                <MultiSelect
                                    v-else
                                    :id="`taxonomy-${dimension.dimension_key}`"
                                    v-model="assignments[dimension.dimension_key]"
                                    :options="taxonomyTerms[dimension.dimension_key] ?? []"
                                    option-label="name"
                                    option-value="id"
                                    :max-selected-labels="3"
                                    :disabled="!canManageTaxonomy"
                                    fluid
                                />
                            </div>
                        </div>
                    </div>

                    <div v-if="!isNew && content" class="card flex flex-col gap-4">
                        <div>
                            <h2 class="text-lg font-semibold">
                                {{ t('workbenches.content.references') }}
                            </h2>
                            <p class="text-sm text-muted-color">
                                {{ t('workbenches.content.referencesHint') }}
                            </p>
                        </div>
                        <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
                            <div class="flex flex-col gap-2">
                                <label for="reference-kind" class="font-medium">{{ t('workbenches.content.kind') }}</label>
                                <InputText id="reference-kind" v-model="referenceKind" :disabled="!canWrite" />
                            </div>
                            <div class="flex flex-col gap-2 md:col-span-2">
                                <label for="reference-targets" class="font-medium">{{ t('workbenches.content.targetIds') }}</label>
                                <Textarea id="reference-targets" v-model="referenceTargets" :disabled="!canWrite" rows="3" auto-resize />
                            </div>
                        </div>
                        <div class="flex justify-end">
                            <Button v-if="canWrite" :label="t('workbenches.content.saveReferences')" icon="pi pi-link" :loading="actionLoading" @click="saveReferences" />
                        </div>
                        <DataTable v-if="references.length" :value="references" size="small">
                            <Column field="kind" :header="t('workbenches.content.kind')" />
                            <Column field="target_content_id" :header="t('workbenches.content.targetContent')" />
                        </DataTable>
                    </div>
                </div>

                <div v-if="!isNew && content" class="flex flex-col gap-4">
                    <SurfaceCard>
                        <h2 class="text-lg font-semibold">
                            {{ t('workbenches.content.status') }}
                        </h2>
                        <div class="flex items-center gap-2">
                            <StatusTag :value="content.status" /><span class="text-sm text-muted-color">{{ t('workbenches.content.updated') }} {{ formatDate(content.updated_at) }}</span>
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <Button v-if="content.status === 'draft' || content.status === 'rejected'" :label="t('workbenches.content.submit')" :disabled="!canAction('content.write')" :loading="actionLoading" @click="submit" />
                            <Button v-if="content.status === 'pending'" :label="t('workbenches.content.reject')" severity="warn" :disabled="!canAction('content.write')" :loading="actionLoading" @click="reject" />
                            <Button
                                v-if="content.status === 'draft' || content.status === 'pending'"
                                :label="t('workbenches.content.schedule')"
                                severity="secondary"
                                :disabled="!canAction('content.schedule')"
                                :loading="actionLoading"
                                @click="schedule"
                            />
                            <Button v-if="content.status === 'scheduled'" :label="t('workbenches.content.unschedule')" severity="secondary" :disabled="!canAction('content.schedule')" :loading="actionLoading" @click="unschedule" />
                            <Button
                                v-if="content.status === 'draft' || content.status === 'pending' || content.status === 'scheduled'"
                                :label="t('workbenches.content.publish')"
                                severity="success"
                                :disabled="!canAction('content.publish')"
                                :loading="actionLoading"
                                @click="publish"
                            />
                            <Button v-if="content.status === 'published'" :label="t('workbenches.content.archive')" severity="warn" :disabled="!canAction('content.archive')" :loading="actionLoading" @click="archive" />
                            <Button v-if="content.status === 'archived'" :label="t('workbenches.content.restore')" severity="secondary" :disabled="!canAction('content.write')" :loading="actionLoading" @click="restore" />
                        </div>
                        <div v-if="content.status === 'draft' || content.status === 'pending'" class="flex flex-col gap-2">
                            <label for="publish-at" class="font-medium">{{ t('workbenches.content.scheduleAt') }}</label>
                            <InputText id="publish-at" v-model="scheduleAt" type="datetime-local" :disabled="!canAction('content.schedule')" />
                        </div>
                    </SurfaceCard>

                    <SurfaceCard>
                        <h2 class="text-lg font-semibold">
                            {{ t('workbenches.content.pinning') }}
                        </h2>
                        <div class="flex items-center justify-between gap-3">
                            <span>{{
                                content.is_pinned
                                    ? t('workbenches.content.pinnedAtRank', {
                                          rank: content.pin_rank
                                      })
                                    : t('workbenches.content.notPinned')
                            }}</span>
                            <Button v-if="canAction('content.pin')" :label="content.is_pinned ? t('workbenches.content.unpin') : t('workbenches.content.pin')" icon="pi pi-star" severity="secondary" @click="togglePin" />
                        </div>
                    </SurfaceCard>

                    <SurfaceCard v-if="content.status === 'archived'">
                        <h2 class="text-lg font-semibold">
                            {{ t('workbenches.content.dangerZone') }}
                        </h2>
                        <ConfirmAction
                            v-if="hasCapability('content.purge')"
                            :label="t('workbenches.content.purge')"
                            :message="t('workbenches.content.purgeConfirm')"
                            :header="t('workbenches.content.purge')"
                            :disabled="actionLoading"
                            @confirmed="purge"
                        />
                    </SurfaceCard>
                </div>
            </div>
        </template>
    </PageShell>
</template>
