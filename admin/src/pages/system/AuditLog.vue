<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';
import { fetchAuditEntries, type AuditEntryDTO, type AuditPageDTO, type AuditQuery } from '@/api/audit';
import PageState from '@/components/feedback/PageState.vue';
import PageToolbar from '@/components/data/PageToolbar.vue';
import PagedTable from '@/components/data/PagedTable.vue';

const filters = reactive<{
    action: string;
    actor_type: string;
    actor_id: string;
    outcome: string | null;
    occurred_after: Date | null;
    occurred_before: Date | null;
}>({
    action: '',
    actor_type: '',
    actor_id: '',
    outcome: null,
    occurred_after: null,
    occurred_before: null
});

const route = useRoute();
const router = useRouter();
const result = ref<AuditPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const selectedEntry = ref<AuditEntryDTO | null>(null);
const detailVisible = computed({
    get: () => selectedEntry.value !== null,
    set: (visible: boolean) => {
        if (!visible) selectedEntry.value = null;
    }
});

function dateQuery(value: Date | null): string | undefined {
    return value ? value.toISOString() : undefined;
}

function routeString(key: string): string | undefined {
    const value = route.query[key];
    return typeof value === 'string' ? value : undefined;
}

function routeDate(key: string): Date | null {
    const value = routeString(key);
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? null : date;
}

function restoreFromRoute(): void {
    filters.action = routeString('action') ?? '';
    filters.actor_type = routeString('actor_type') ?? '';
    filters.actor_id = routeString('actor_id') ?? '';
    const outcome = routeString('outcome');
    filters.outcome = outcome === 'success' || outcome === 'failure' ? outcome : null;
    filters.occurred_after = routeDate('occurred_after');
    filters.occurred_before = routeDate('occurred_before');

    const routePage = Number.parseInt(routeString('page') ?? '', 10);
    const routeSize = Number.parseInt(routeString('size') ?? '', 10);
    if (Number.isFinite(routePage) && routePage > 0) page.value = routePage;
    if (Number.isFinite(routeSize) && routeSize > 0 && routeSize <= 100) size.value = routeSize;
}

async function syncRoute(): Promise<void> {
    const nextQuery: LocationQueryRaw = { page: String(page.value), size: String(size.value) };
    const values: Array<[keyof typeof filters, string | undefined]> = [
        ['action', filters.action.trim() || undefined],
        ['actor_type', filters.actor_type.trim() || undefined],
        ['actor_id', filters.actor_id.trim() || undefined],
        ['outcome', filters.outcome || undefined],
        ['occurred_after', dateQuery(filters.occurred_after)],
        ['occurred_before', dateQuery(filters.occurred_before)]
    ];
    for (const [key, value] of values) {
        if (value) nextQuery[key] = value;
    }
    await router.replace({ query: nextQuery });
}

function query(): AuditQuery {
    return {
        page: page.value,
        size: size.value,
        action: filters.action.trim() || undefined,
        actor_type: filters.actor_type.trim() || undefined,
        actor_id: filters.actor_id.trim() || undefined,
        outcome: filters.outcome || undefined,
        occurred_after: dateQuery(filters.occurred_after),
        occurred_before: dateQuery(filters.occurred_before)
    };
}

async function load(syncUrl = false): Promise<void> {
    if (syncUrl) await syncRoute();
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchAuditEntries(query());
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

function onPage(value: number): void {
    page.value = value;
    void load(true);
}

function onSize(value: number): void {
    size.value = value;
    page.value = 1;
    void load(true);
}

function refresh(): void {
    void load();
}

function formatDate(value: string): string {
    return new Date(value).toLocaleString();
}

function detailsText(entry: AuditEntryDTO): string {
    return JSON.stringify(entry.details ?? {}, null, 2) ?? '{}';
}

onMounted(() => {
    restoreFromRoute();
    void load();
});
</script>

<template>
    <PageToolbar title="Audit Log" subtitle="按服务端授权范围查询不可变管理审计记录。">
        <template #actions>
            <Button icon="pi pi-refresh" label="刷新" severity="secondary" :loading="loading" @click="refresh" />
        </template>

        <div class="card">
            <form class="grid grid-cols-12 gap-4 items-end" @submit.prevent="applyFilters">
                <div class="col-span-12 md:col-span-6 xl:col-span-3 flex flex-col gap-2">
                    <label for="audit-action" class="font-medium">Action</label>
                    <InputText id="audit-action" v-model="filters.action" placeholder="settings.update" />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-2 flex flex-col gap-2">
                    <label for="audit-actor-type" class="font-medium">Actor type</label>
                    <InputText id="audit-actor-type" v-model="filters.actor_type" placeholder="user" />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-3 flex flex-col gap-2">
                    <label for="audit-actor-id" class="font-medium">Actor ID</label>
                    <InputText id="audit-actor-id" v-model="filters.actor_id" />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-2 flex flex-col gap-2">
                    <label for="audit-outcome" class="font-medium">Outcome</label>
                    <Select id="audit-outcome" v-model="filters.outcome" :options="['success', 'failure']" show-clear placeholder="全部" fluid />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-2">
                    <Button type="submit" label="应用筛选" icon="pi pi-search" class="w-full" />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-3 flex flex-col gap-2">
                    <label for="audit-after" class="font-medium">Occurred after</label>
                    <DatePicker id="audit-after" v-model="filters.occurred_after" show-time hour-format="24" show-button-bar fluid />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-3 flex flex-col gap-2">
                    <label for="audit-before" class="font-medium">Occurred before</label>
                    <DatePicker id="audit-before" v-model="filters.occurred_before" show-time hour-format="24" show-button-bar fluid />
                </div>
            </form>
        </div>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" description="审计记录加载失败，请稍后重试。" />
        <PageState v-else-if="result && result.total === 0" state="empty" title="暂无审计记录" description="当前筛选条件没有匹配的记录。" />
        <PagedTable v-else-if="result" :value="result.items" :loading="loading" :total-records="result.total" :page="result.page" :size="result.size" @update:page="onPage" @update:size="onSize">
            <Column field="occurred_at" header="时间" style="min-width: 12rem">
                <template #body="{ data }">{{ formatDate(data.occurred_at) }}</template>
            </Column>
            <Column field="action" header="Action" style="min-width: 16rem" />
            <Column field="actor_id" header="Actor" style="min-width: 14rem">
                <template #body="{ data }">{{ data.actor_type || '-' }} / {{ data.actor_id || '-' }}</template>
            </Column>
            <Column field="target_id" header="Target" style="min-width: 14rem">
                <template #body="{ data }">{{ data.target_type || '-' }} / {{ data.target_id || '-' }}</template>
            </Column>
            <Column field="outcome" header="Outcome" style="min-width: 8rem">
                <template #body="{ data }"><Tag :value="data.outcome" :severity="data.outcome === 'success' ? 'success' : 'danger'" /></template>
            </Column>
            <Column header="Details" style="width: 8rem">
                <template #body="{ data }"><Button label="查看" text @click="selectedEntry = data" /></template>
            </Column>
        </PagedTable>

        <Drawer v-model:visible="detailVisible" header="Audit details" position="right" class="!w-full md:!w-[38rem]">
            <template v-if="selectedEntry">
                <div class="flex flex-col gap-4">
                    <div class="grid grid-cols-2 gap-3 text-sm">
                        <span class="text-muted-color">ID</span><span class="break-all">{{ selectedEntry.id }}</span> <span class="text-muted-color">Request ID</span><span class="break-all">{{ selectedEntry.request_id || '-' }}</span>
                        <span class="text-muted-color">Occurred at</span><span>{{ formatDate(selectedEntry.occurred_at) }}</span>
                    </div>
                    <Divider />
                    <pre class="p-3 rounded-border bg-surface-100 dark:bg-surface-800 text-sm whitespace-pre-wrap break-all">{{ detailsText(selectedEntry) }}</pre>
                </div>
            </template>
        </Drawer>
    </PageToolbar>
</template>
