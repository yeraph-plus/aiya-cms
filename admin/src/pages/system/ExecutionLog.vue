<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { fetchExecutionEntries, type ExecutionEntryDTO, type ExecutionPageDTO } from '@/api/execution';
import PageState from '@/components/feedback/PageState.vue';
import FilterBar from '@/components/data/FilterBar.vue';
import ListPanel from '@/components/data/ListPanel.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';
import PagedTable from '@/components/data/PagedTable.vue';

const { t, locale } = useI18n();
const filters = reactive({ kind: '', key: '', status: '' });
const result = ref<ExecutionPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchExecutionEntries({
            page: page.value,
            size: size.value,
            kind: filters.kind === 'outbox' || filters.kind === 'inbox' || filters.kind === 'task' ? filters.kind : undefined,
            key: filters.key.trim() || undefined,
            status: filters.status.trim() || undefined
        });
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

function onPage(value: number): void {
    page.value = value;
    void load();
}

function onSize(value: number): void {
    size.value = value;
    page.value = 1;
    void load();
}

function formatDate(value: string): string {
    return new Intl.DateTimeFormat(locale.value, {
        dateStyle: 'medium',
        timeStyle: 'short'
    }).format(new Date(value));
}

function errorValue(entry: ExecutionEntryDTO): string {
    return entry.error_category ?? '-';
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.system.operations')" :description="t('workbenches.execution.description')" :loading="loading" @refresh="load">
        <SurfaceCard>
            <FilterBar :label="t('common.applyFilters')" layout-class="grid grid-cols-12 gap-4 items-end" @submit="applyFilters">
                <div class="col-span-12 md:col-span-4 xl:col-span-3 flex flex-col gap-2">
                    <label for="execution-kind" class="font-medium">{{ t('workbenches.execution.kind') }}</label>
                    <Select id="execution-kind" v-model="filters.kind" :options="['outbox', 'inbox', 'task']" show-clear :placeholder="t('common.all')" fluid />
                </div>
                <div class="col-span-12 md:col-span-4 xl:col-span-4 flex flex-col gap-2">
                    <label for="execution-key" class="font-medium">{{ t('workbenches.execution.key') }}</label>
                    <InputText id="execution-key" v-model="filters.key" placeholder="content.publish.scan.v1.tick" />
                </div>
                <div class="col-span-12 md:col-span-4 xl:col-span-3 flex flex-col gap-2">
                    <label for="execution-status" class="font-medium">{{ t('workbenches.status') }}</label>
                    <InputText id="execution-status" v-model="filters.status" :placeholder="t('workbenches.execution.statusPlaceholder')" />
                </div>
            </FilterBar>
        </SurfaceCard>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="result && result.total === 0" state="empty" :title="t('workbenches.execution.empty')" :description="t('workbenches.execution.emptyDescription')" />
        <ListPanel v-else-if="result">
            <PagedTable :value="result.items" :loading="loading" :total-records="result.total" :page="result.page" :size="result.size" @update:page="onPage" @update:size="onSize">
                <Column field="occurred_at" :header="t('workbenches.execution.time')" style="min-width: 12rem">
                    <template #body="{ data }">{{ formatDate(data.occurred_at) }}</template>
                </Column>
                <Column field="kind" :header="t('workbenches.execution.kind')" style="min-width: 8rem" />
                <Column field="key" :header="t('workbenches.execution.key')" style="min-width: 24rem" />
                <Column field="status" :header="t('workbenches.status')" style="min-width: 10rem" />
                <Column field="attempts" :header="t('workbenches.execution.attempts')" style="min-width: 8rem" />
                <Column field="error_category" :header="t('workbenches.execution.error')" style="min-width: 10rem">
                    <template #body="{ data }">{{ errorValue(data) }}</template>
                </Column>
            </PagedTable>
        </ListPanel>
    </PageShell>
</template>
