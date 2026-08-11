<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';
import { fetchAuditEntries, type AuditEntryDTO, type AuditPageDTO, type AuditQuery } from '@/api/audit';
import PageState from '@/components/feedback/PageState.vue';
import PageShell from '@/components/shell/PageShell.vue';
import EntityDrawerShell from '@/components/shell/EntityDrawerShell.vue';
import PagedTable from '@/components/data/PagedTable.vue';

const { t, locale } = useI18n();
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
    return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
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
    <PageShell :title="t('routes.system.audit')" :description="t('workbenches.audit.description')" :loading="loading" @refresh="refresh">

        <div class="card">
            <form class="grid grid-cols-12 gap-4 items-end" @submit.prevent="applyFilters">
                <div class="col-span-12 md:col-span-6 xl:col-span-3 flex flex-col gap-2">
                    <label for="audit-action" class="font-medium">{{ t('workbenches.audit.action') }}</label>
                    <InputText id="audit-action" v-model="filters.action" placeholder="settings.update" />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-2 flex flex-col gap-2">
                    <label for="audit-actor-type" class="font-medium">{{ t('workbenches.audit.actorType') }}</label>
                    <InputText id="audit-actor-type" v-model="filters.actor_type" placeholder="user" />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-3 flex flex-col gap-2">
                    <label for="audit-actor-id" class="font-medium">{{ t('workbenches.audit.actorId') }}</label>
                    <InputText id="audit-actor-id" v-model="filters.actor_id" />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-2 flex flex-col gap-2">
                    <label for="audit-outcome" class="font-medium">{{ t('workbenches.audit.outcome') }}</label>
                    <Select id="audit-outcome" v-model="filters.outcome" :options="['success', 'failure']" show-clear :placeholder="t('common.all')" fluid />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-2">
                    <Button type="submit" :label="t('common.applyFilters')" icon="pi pi-search" class="w-full" />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-3 flex flex-col gap-2">
                    <label for="audit-after" class="font-medium">{{ t('workbenches.audit.after') }}</label>
                    <DatePicker id="audit-after" v-model="filters.occurred_after" show-time hour-format="24" show-button-bar fluid />
                </div>
                <div class="col-span-12 md:col-span-6 xl:col-span-3 flex flex-col gap-2">
                    <label for="audit-before" class="font-medium">{{ t('workbenches.audit.before') }}</label>
                    <DatePicker id="audit-before" v-model="filters.occurred_before" show-time hour-format="24" show-button-bar fluid />
                </div>
            </form>
        </div>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="result && result.total === 0" state="empty" :title="t('workbenches.audit.empty')" :description="t('workbenches.audit.emptyDescription')" />
        <PagedTable v-else-if="result" :value="result.items" :loading="loading" :total-records="result.total" :page="result.page" :size="result.size" @update:page="onPage" @update:size="onSize">
            <Column field="occurred_at" :header="t('workbenches.audit.time')" style="min-width: 12rem">
                <template #body="{ data }">{{ formatDate(data.occurred_at) }}</template>
            </Column>
            <Column field="action" :header="t('workbenches.audit.action')" style="min-width: 16rem" />
            <Column field="actor_id" :header="t('workbenches.audit.actor')" style="min-width: 14rem">
                <template #body="{ data }">{{ data.actor_type || '-' }} / {{ data.actor_id || '-' }}</template>
            </Column>
            <Column field="target_id" :header="t('workbenches.audit.target')" style="min-width: 14rem">
                <template #body="{ data }">{{ data.target_type || '-' }} / {{ data.target_id || '-' }}</template>
            </Column>
            <Column field="outcome" :header="t('workbenches.audit.outcome')" style="min-width: 8rem">
                <template #body="{ data }"><Tag :value="data.outcome" :severity="data.outcome === 'success' ? 'success' : 'danger'" /></template>
            </Column>
            <Column :header="t('workbenches.audit.details')" style="width: 8rem">
                <template #body="{ data }"><Button :label="t('workbenches.view')" text @click="selectedEntry = data" /></template>
            </Column>
        </PagedTable>

        <EntityDrawerShell v-model="detailVisible" :title="t('workbenches.audit.detailTitle')" width-class="!w-full md:!w-[38rem]">
            <template v-if="selectedEntry">
                <div class="flex flex-col gap-4">
                    <div class="grid grid-cols-2 gap-3 text-sm">
                        <span class="text-muted-color">ID</span><span class="break-all">{{ selectedEntry.id }}</span> <span class="text-muted-color">{{ t('workbenches.audit.requestId') }}</span><span class="break-all">{{ selectedEntry.request_id || '-' }}</span>
                        <span class="text-muted-color">{{ t('workbenches.audit.occurredAt') }}</span><span>{{ formatDate(selectedEntry.occurred_at) }}</span>
                    </div>
                    <Divider />
                    <pre class="p-3 rounded-border bg-surface-100 dark:bg-surface-800 text-sm whitespace-pre-wrap break-all">{{ detailsText(selectedEntry) }}</pre>
                </div>
            </template>
        </EntityDrawerShell>
    </PageShell>
</template>
