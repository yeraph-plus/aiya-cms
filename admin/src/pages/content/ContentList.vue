<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';
import { fetchContent, type ContentDTO, type ContentListQuery, type ContentPageDTO } from '@/api/content';
import { hasCapability } from '@/auth/session';
import PageState from '@/components/feedback/PageState.vue';
import EntityDrawerShell from '@/components/shell/EntityDrawerShell.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';
import PagedTable from '@/components/data/PagedTable.vue';
import ContentEditor from './ContentEditor.vue';

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const statusOptions = ['draft', 'pending', 'rejected', 'scheduled', 'published', 'archived'];
const typeOptions = computed(() => [
    { label: t('workbenches.content.allTypes'), value: null },
    { label: t('workbenches.content.post'), value: 'post' },
    { label: t('workbenches.content.page'), value: 'page' }
]);
const filters = reactive({
    status: null as string | null,
    typeName: null as string | null
});
const result = ref<ContentPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const canWrite = computed(() => hasCapability('content.write'));
const selectedContentId = ref<string | null>(null);
const editorVisible = computed({
    get: () => selectedContentId.value !== null,
    set: (visible: boolean) => {
        if (!visible) selectedContentId.value = null;
    }
});

function routeString(key: string): string | undefined {
    const value = route.query[key];
    return typeof value === 'string' ? value : undefined;
}

function restoreFromRoute(): void {
    filters.status = routeString('status') ?? null;
    filters.typeName = routeString('type_name') ?? null;
    const routePage = Number.parseInt(routeString('page') ?? '', 10);
    const routeSize = Number.parseInt(routeString('size') ?? '', 10);
    if (Number.isFinite(routePage) && routePage > 0) page.value = routePage;
    if (Number.isFinite(routeSize) && routeSize > 0 && routeSize <= 100) size.value = routeSize;
}

async function syncRoute(): Promise<void> {
    const query: LocationQueryRaw = {
        page: String(page.value),
        size: String(size.value)
    };
    if (filters.status) query.status = filters.status;
    if (filters.typeName) query.type_name = filters.typeName;
    await router.replace({ query });
}

function query(): ContentListQuery {
    return {
        page: page.value,
        size: size.value,
        status: filters.status || undefined,
        type_name: filters.typeName || undefined
    };
}

async function load(syncUrl = false): Promise<void> {
    if (syncUrl) await syncRoute();
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchContent(query());
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function applyFilters(): void {
    page.value = 1;
    void load(true);
}

function refresh(): void {
    void load();
}

function onPage(value: number): void {
    page.value = value;
    void load(true);
}

function onSize(value: number): void {
    size.value = value;
    page.value = 1;
    void load(true);
}

function openNew(): void {
    void router.push({ name: 'content-write' });
}

function openEditor(contentId: string): void {
    selectedContentId.value = contentId;
}

function contentSaved(): void {
    void load();
}

function contentPurged(): void {
    selectedContentId.value = null;
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

function contentTypeLabel(item: ContentDTO): string {
    return item.type_name === 'post' ? 'Post' : item.type_name === 'page' ? 'Page' : item.type_name;
}

onMounted(() => {
    restoreFromRoute();
    void load();
});
</script>

<template>
    <PageShell :title="t('routes.content.articles')" :description="t('workbenches.content.description')" :loading="loading" @refresh="refresh">
        <template #actions>
            <Button v-if="canWrite" icon="pi pi-plus" :label="t('workbenches.content.new')" @click="openNew" />
        </template>

        <SurfaceCard>
            <FilterBar :label="t('common.applyFilters')" @submit="applyFilters">
                <div class="flex min-w-52 flex-col gap-2">
                    <label for="content-type" class="font-medium">{{ t('workbenches.content.type') }}</label>
                    <Select id="content-type" v-model="filters.typeName" :options="typeOptions" option-label="label" option-value="value" fluid />
                </div>
                <div class="flex min-w-52 flex-col gap-2">
                    <label for="content-status" class="font-medium">{{ t('workbenches.status') }}</label>
                    <Select id="content-status" v-model="filters.status" :options="statusOptions" show-clear :placeholder="t('common.all')" fluid />
                </div>
            </FilterBar>
        </SurfaceCard>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" description="The content list could not be loaded." />
        <PageState v-else-if="result && result.total === 0" state="empty" :title="t('workbenches.content.empty')" :description="t('workbenches.content.emptyDescription')" />
        <PagedTable v-else-if="result" :value="result.items" :loading="loading" :total-records="result.total" :page="result.page" :size="result.size" @update:page="onPage" @update:size="onSize">
            <Column field="title" :header="t('workbenches.content.title')" style="min-width: 18rem" />
            <Column :header="t('workbenches.content.type')" style="min-width: 8rem">
                <template #body="{ data }">{{ contentTypeLabel(data) }}</template>
            </Column>
            <Column field="slug" :header="t('workbenches.content.slug')" style="min-width: 14rem" />
            <Column field="status" :header="t('workbenches.status')" style="min-width: 9rem">
                <template #body="{ data }"><StatusTag :value="data.status" /></template>
            </Column>
            <Column field="is_pinned" :header="t('workbenches.content.pinned')" style="min-width: 7rem">
                <template #body="{ data }"><i class="pi" :class="data.is_pinned ? 'pi-star-fill text-yellow-500' : 'pi-minus text-muted-color'" /></template>
            </Column>
            <Column field="updated_at" :header="t('workbenches.content.updated')" style="min-width: 13rem">
                <template #body="{ data }">{{ formatDate(data.updated_at) }}</template>
            </Column>
            <Column :header="t('common.actions')" style="width: 8rem">
                <template #body="{ data }"><Button :label="t('common.edit')" text icon="pi pi-pencil" @click="openEditor(data.id)" /></template>
            </Column>
        </PagedTable>

        <EntityDrawerShell v-model="editorVisible" :title="t('workbenches.content.edit')" :description="selectedContentId || ''" width-class="!w-full xl:!w-[80rem]">
            <ContentEditor v-if="selectedContentId" :content-id="selectedContentId" embedded @saved="contentSaved" @purged="contentPurged" />
        </EntityDrawerShell>
    </PageShell>
</template>
