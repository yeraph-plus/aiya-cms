<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { fetchExecutionEntries, type ExecutionEntryDTO, type ExecutionPageDTO } from '@/api/execution';
import PageState from '@/components/feedback/PageState.vue';
import PageToolbar from '@/components/data/PageToolbar.vue';
import PagedTable from '@/components/data/PagedTable.vue';

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
    return new Date(value).toLocaleString();
}

function errorValue(entry: ExecutionEntryDTO): string {
    return entry.error_category ?? '-';
}

onMounted(() => void load());
</script>

<template>
    <PageToolbar title="Execution Log" subtitle="查看 outbox、inbox receipt 和 task 的安全执行摘要。">
        <template #actions>
            <Button icon="pi pi-refresh" label="刷新" severity="secondary" :loading="loading" @click="load" />
        </template>

        <div class="card">
            <form class="grid grid-cols-12 gap-4 items-end" @submit.prevent="applyFilters">
                <div class="col-span-12 md:col-span-4 xl:col-span-3 flex flex-col gap-2">
                    <label for="execution-kind" class="font-medium">Kind</label>
                    <Select id="execution-kind" v-model="filters.kind" :options="['outbox', 'inbox', 'task']" show-clear placeholder="全部" fluid />
                </div>
                <div class="col-span-12 md:col-span-4 xl:col-span-4 flex flex-col gap-2">
                    <label for="execution-key" class="font-medium">Key</label>
                    <InputText id="execution-key" v-model="filters.key" placeholder="content.publish.scan.v1.tick" />
                </div>
                <div class="col-span-12 md:col-span-4 xl:col-span-3 flex flex-col gap-2">
                    <label for="execution-status" class="font-medium">Status</label>
                    <InputText id="execution-status" v-model="filters.status" placeholder="completed / dead" />
                </div>
                <div class="col-span-12 xl:col-span-2">
                    <Button type="submit" label="应用筛选" icon="pi pi-search" class="w-full" />
                </div>
            </form>
        </div>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" description="执行记录加载失败，请稍后重试。" />
        <PageState v-else-if="result && result.total === 0" state="empty" title="暂无执行记录" description="当前筛选条件没有匹配的记录。" />
        <PagedTable v-else-if="result" :value="result.items" :loading="loading" :total-records="result.total" :page="result.page" :size="result.size" @update:page="onPage" @update:size="onSize">
            <Column field="occurred_at" header="时间" style="min-width: 12rem">
                <template #body="{ data }">{{ formatDate(data.occurred_at) }}</template>
            </Column>
            <Column field="kind" header="Kind" style="min-width: 8rem" />
            <Column field="key" header="Key" style="min-width: 24rem" />
            <Column field="status" header="Status" style="min-width: 10rem" />
            <Column field="attempts" header="Attempts" style="min-width: 8rem" />
            <Column field="error_category" header="Error" style="min-width: 10rem">
                <template #body="{ data }">{{ errorValue(data) }}</template>
            </Column>
        </PagedTable>
    </PageToolbar>
</template>
