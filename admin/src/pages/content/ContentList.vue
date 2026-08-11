<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';
import { fetchContent, type ContentDTO, type ContentListQuery, type ContentPageDTO } from '@/api/content';
import { hasCapability } from '@/auth/session';
import PageState from '@/components/feedback/PageState.vue';
import PageToolbar from '@/components/data/PageToolbar.vue';
import PagedTable from '@/components/data/PagedTable.vue';

const route = useRoute();
const router = useRouter();
const statusOptions = ['draft', 'pending', 'rejected', 'scheduled', 'published', 'archived'];
const typeOptions = [
    { label: 'All types', value: null },
    { label: 'Post', value: 'post' },
    { label: 'Page', value: 'page' }
];
const filters = reactive({ status: null as string | null, typeName: null as string | null });
const result = ref<ContentPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const canWrite = computed(() => hasCapability('content.write'));

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
    const query: LocationQueryRaw = { page: String(page.value), size: String(size.value) };
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
    void router.push({ name: 'content-new' });
}

function openEditor(contentId: string): void {
    void router.push({ name: 'content-editor', params: { contentId } });
}

function statusSeverity(status: string): 'success' | 'warn' | 'danger' | 'secondary' | 'info' {
    if (status === 'published') return 'success';
    if (status === 'scheduled' || status === 'pending') return 'info';
    if (status === 'archived' || status === 'rejected') return 'warn';
    return 'secondary';
}

function formatDate(value: string | null | undefined): string {
    return value ? new Date(value).toLocaleString() : '-';
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
    <PageToolbar title="Articles" subtitle="Manage every registered content type from one list.">
        <template #actions>
            <Button v-if="canWrite" icon="pi pi-plus" label="New content" @click="openNew" />
            <Button icon="pi pi-refresh" label="Refresh" severity="secondary" :loading="loading" @click="refresh" />
        </template>

        <div class="card">
            <form class="flex flex-wrap items-end gap-4" @submit.prevent="applyFilters">
                <div class="flex min-w-52 flex-col gap-2">
                    <label for="content-type" class="font-medium">Content type</label>
                    <Select id="content-type" v-model="filters.typeName" :options="typeOptions" option-label="label" option-value="value" fluid />
                </div>
                <div class="flex min-w-52 flex-col gap-2">
                    <label for="content-status" class="font-medium">Status</label>
                    <Select id="content-status" v-model="filters.status" :options="statusOptions" show-clear placeholder="All statuses" fluid />
                </div>
                <Button type="submit" label="Apply filters" icon="pi pi-search" />
            </form>
        </div>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" description="The content list could not be loaded." />
        <PageState v-else-if="result && result.total === 0" state="empty" title="No content" description="No content matches the current filters." />
        <PagedTable v-else-if="result" :value="result.items" :loading="loading" :total-records="result.total" :page="result.page" :size="result.size" @update:page="onPage" @update:size="onSize">
            <Column field="title" header="Title" style="min-width: 18rem" />
            <Column header="Type" style="min-width: 8rem">
                <template #body="{ data }">{{ contentTypeLabel(data) }}</template>
            </Column>
            <Column field="slug" header="Slug" style="min-width: 14rem" />
            <Column field="status" header="Status" style="min-width: 9rem">
                <template #body="{ data }"><Tag :value="data.status" :severity="statusSeverity(data.status)" /></template>
            </Column>
            <Column field="is_pinned" header="Pinned" style="min-width: 7rem">
                <template #body="{ data }"><i class="pi" :class="data.is_pinned ? 'pi-star-fill text-yellow-500' : 'pi-minus text-muted-color'" /></template>
            </Column>
            <Column field="updated_at" header="Updated" style="min-width: 13rem">
                <template #body="{ data }">{{ formatDate(data.updated_at) }}</template>
            </Column>
            <Column header="Actions" style="width: 8rem">
                <template #body="{ data }"><Button label="Edit" text icon="pi pi-pencil" @click="openEditor(data.id)" /></template>
            </Column>
        </PagedTable>
    </PageToolbar>
</template>
