<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { approveComment, deleteComment, fetchComment, fetchComments, rejectComment, type CommentDTO, type CommentPageDTO } from '@/api/comments';
import { hasCapability } from '@/auth/session';
import PagedTable from '@/components/data/PagedTable.vue';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import PageState from '@/components/feedback/PageState.vue';
import EntityDrawerShell from '@/components/shell/EntityDrawerShell.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SensitiveActionDialog from '@/components/shell/SensitiveActionDialog.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t, locale } = useI18n();
const statuses = ['pending', 'published', 'rejected', 'deleted'];
const filters = reactive({
    status: null as string | null,
    targetType: '',
    targetId: '',
    authorId: ''
});
const result = ref<CommentPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const selected = ref<CommentDTO | null>(null);
const drawerVisible = ref(false);
const detailLoading = ref(false);
const actionLoading = ref(false);
const actionError = ref<unknown>(null);
const rejectVisible = ref(false);
const deleteVisible = ref(false);
const reason = ref('');
const canModerate = computed(() => hasCapability('comments.moderate'));
const canDelete = computed(() => hasCapability('comments.delete'));

async function load(resetPage = false): Promise<void> {
    if (resetPage) page.value = 1;
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchComments({
            page: page.value,
            size: size.value,
            status: filters.status || undefined,
            target_type: filters.targetType.trim() || undefined,
            target_id: filters.targetId.trim() || undefined,
            author_id: filters.authorId.trim() || undefined
        });
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

async function openComment(comment: CommentDTO): Promise<void> {
    drawerVisible.value = true;
    detailLoading.value = true;
    actionError.value = null;
    try {
        selected.value = await fetchComment(comment.id);
    } catch (caught) {
        actionError.value = caught;
    } finally {
        detailLoading.value = false;
    }
}

function replaceComment(comment: CommentDTO): void {
    selected.value = comment;
    if (result.value) {
        result.value = {
            ...result.value,
            items: result.value.items.map((item) => (item.id === comment.id ? comment : item))
        };
    }
}

async function approve(): Promise<void> {
    if (!selected.value) return;
    actionLoading.value = true;
    actionError.value = null;
    try {
        replaceComment(await approveComment(selected.value.id));
    } catch (caught) {
        actionError.value = caught;
    } finally {
        actionLoading.value = false;
    }
}

function openReject(): void {
    reason.value = '';
    actionError.value = null;
    rejectVisible.value = true;
}

function openDelete(): void {
    reason.value = '';
    actionError.value = null;
    deleteVisible.value = true;
}

async function confirmReject(): Promise<void> {
    if (!selected.value || !reason.value.trim()) return;
    actionLoading.value = true;
    actionError.value = null;
    try {
        replaceComment(await rejectComment(selected.value.id, { reason: reason.value.trim() }));
        rejectVisible.value = false;
    } catch (caught) {
        actionError.value = caught;
    } finally {
        actionLoading.value = false;
    }
}

async function confirmDelete(): Promise<void> {
    if (!selected.value) return;
    actionLoading.value = true;
    actionError.value = null;
    try {
        replaceComment(
            await deleteComment(selected.value.id, {
                reason: reason.value.trim() || undefined
            })
        );
        deleteVisible.value = false;
    } catch (caught) {
        actionError.value = caught;
    } finally {
        actionLoading.value = false;
    }
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

function formatDate(value: string | null | undefined): string {
    return value
        ? new Intl.DateTimeFormat(locale.value, {
              dateStyle: 'medium',
              timeStyle: 'short'
          }).format(new Date(value))
        : '-';
}

function excerpt(body: string | null): string {
    if (!body) return t('workbenches.comments.deletedBody');
    return body.length > 100 ? `${body.slice(0, 100)}…` : body;
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.content.comments')" :description="t('workbenches.comments.description')" :loading="loading" @refresh="load()">
        <SurfaceCard>
            <FilterBar :label="t('workbenches.search')" @submit="load(true)">
                <Select v-model="filters.status" :options="statuses" show-clear :placeholder="t('workbenches.status')" class="min-w-44" />
                <InputText v-model="filters.targetType" :placeholder="t('workbenches.comments.targetType')" />
                <InputText v-model="filters.targetId" :placeholder="t('workbenches.comments.targetId')" />
                <InputText v-model="filters.authorId" :placeholder="t('workbenches.comments.authorId')" />
            </FilterBar>
        </SurfaceCard>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="result?.total === 0" state="empty" :title="t('workbenches.comments.empty')" />
        <SurfaceCard v-else-if="result">
            <PagedTable :value="result.items" :total-records="result.total" :page="result.page" :size="result.size" :loading="loading" @update:page="onPage" @update:size="onSize">
                <Column field="status" :header="t('workbenches.status')"
                    ><template #body="{ data }"><StatusTag :value="data.status" /></template
                ></Column>
                <Column :header="t('workbenches.comments.target')">
                    <template #body="{ data }">
                        <div>
                            {{ data.target?.title || data.target?.slug || `${data.target_type}:${data.target_id}` }}
                        </div>
                        <small v-if="data.target?.title || data.target?.slug" class="text-muted-color">{{ data.target_id }}</small>
                    </template>
                </Column>
                <Column field="author_id" :header="t('workbenches.comments.authorId')">
                    <template #body="{ data }">
                        <div>
                            {{ data.author?.display_name || data.author?.username || data.author_id }}
                        </div>
                        <small v-if="data.author?.display_name || data.author?.username" class="text-muted-color">{{ data.author_id }}</small>
                    </template>
                </Column>
                <Column :header="t('workbenches.comments.body')"
                    ><template #body="{ data }">{{ excerpt(data.body) }}</template></Column
                >
                <Column field="submitted_at" :header="t('workbenches.comments.submittedAt')"
                    ><template #body="{ data }">{{ formatDate(data.submitted_at) }}</template></Column
                >
                <Column
                    ><template #body="{ data }"><Button :label="t('workbenches.view')" text @click="openComment(data)" /></template
                ></Column>
            </PagedTable>
        </SurfaceCard>

        <EntityDrawerShell v-model="drawerVisible" :title="t('workbenches.comments.detail')" :description="selected?.id || ''">
            <PageState v-if="detailLoading" state="loading" />
            <ApiErrorMessage v-if="actionError" :error="actionError" />
            <div v-if="selected && !detailLoading" class="flex flex-col gap-5">
                <SurfaceCard>
                    <dl class="grid grid-cols-[9rem_1fr] gap-3 text-sm">
                        <dt class="text-muted-color">{{ t('workbenches.status') }}</dt>
                        <dd><StatusTag :value="selected.status" /></dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.comments.target') }}
                        </dt>
                        <dd>
                            <div>
                                {{ selected.target?.title || selected.target?.slug || `${selected.target_type}:${selected.target_id}` }}
                            </div>
                            <small v-if="selected.target?.title || selected.target?.slug" class="text-muted-color">{{ selected.target_id }}</small>
                        </dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.comments.authorId') }}
                        </dt>
                        <dd>
                            <div>
                                {{ selected.author?.display_name || selected.author?.username || `${selected.author_type}:${selected.author_id}` }}
                            </div>
                            <small v-if="selected.author?.display_name || selected.author?.username" class="text-muted-color">{{ selected.author_id }}</small>
                        </dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.comments.parent') }}
                        </dt>
                        <dd>{{ selected.parent_id || '-' }}</dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.comments.submittedAt') }}
                        </dt>
                        <dd>{{ formatDate(selected.submitted_at) }}</dd>
                        <dt class="text-muted-color">{{ t('workbenches.reason') }}</dt>
                        <dd>{{ selected.moderation_reason || '-' }}</dd>
                    </dl>
                </SurfaceCard>
                <SurfaceCard :title="t('workbenches.comments.body')"
                    ><p class="whitespace-pre-wrap break-words">
                        {{ selected.body || t('workbenches.comments.deletedBody') }}
                    </p></SurfaceCard
                >
                <div class="flex flex-wrap gap-2">
                    <Button v-if="canModerate && selected.status !== 'published' && selected.status !== 'deleted'" :label="t('workbenches.comments.approve')" :loading="actionLoading" @click="approve" />
                    <Button v-if="canModerate && selected.status !== 'rejected' && selected.status !== 'deleted'" :label="t('workbenches.comments.reject')" severity="warn" :disabled="actionLoading" @click="openReject" />
                    <Button v-if="canDelete && selected.status !== 'deleted'" :label="t('workbenches.comments.delete')" severity="danger" :disabled="actionLoading" @click="openDelete" />
                </div>
            </div>
        </EntityDrawerShell>

        <SensitiveActionDialog
            v-model="rejectVisible"
            :title="t('workbenches.comments.reject')"
            :message="t('workbenches.comments.rejectMessage')"
            :confirm-label="t('workbenches.comments.reject')"
            :loading="actionLoading"
            :disabled="!reason.trim()"
            @confirm="confirmReject"
        >
            <ApiErrorMessage v-if="actionError" :error="actionError" />
            <Textarea v-model="reason" rows="4" class="mt-4 w-full" :placeholder="t('workbenches.reason')" />
        </SensitiveActionDialog>

        <SensitiveActionDialog v-model="deleteVisible" :title="t('workbenches.comments.delete')" :message="t('workbenches.comments.deleteMessage')" :confirm-label="t('workbenches.comments.delete')" :loading="actionLoading" @confirm="confirmDelete">
            <ApiErrorMessage v-if="actionError" :error="actionError" />
            <Textarea v-model="reason" rows="4" class="mt-4 w-full" :placeholder="t('workbenches.comments.optionalReason')" />
        </SensitiveActionDialog>
    </PageShell>
</template>
