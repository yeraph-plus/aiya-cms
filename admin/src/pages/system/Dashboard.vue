<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { fetchDashboard, type AdminDashboardDTO, type DashboardWindow } from '@/api/dashboard';
import { errorMessage } from '@/api/errors';
import PageState from '@/components/feedback/PageState.vue';
import PageToolbar from '@/components/data/PageToolbar.vue';

const windows: { label: string; value: DashboardWindow }[] = [
    { label: '24 hours', value: '24h' },
    { label: '7 days', value: '7d' },
    { label: '30 days', value: '30d' }
];
const windowValue = ref<DashboardWindow>('7d');
const dashboard = ref<AdminDashboardDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        dashboard.value = await fetchDashboard(windowValue.value);
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function selectWindow(value: DashboardWindow): void {
    windowValue.value = value;
    void load();
}

function formatValue(value: unknown): string {
    if (typeof value === 'number') return value.toLocaleString();
    if (typeof value === 'object' && value !== null) return JSON.stringify(value);
    return String(value ?? '-');
}

onMounted(() => void load());
</script>

<template>
    <PageToolbar title="Dashboard" subtitle="Capability-owned totals and fixed-window increments.">
        <template #actions>
            <div class="flex gap-2">
                <Button
                    v-for="option in windows"
                    :key="option.value"
                    :label="option.label"
                    :severity="windowValue === option.value ? 'primary' : 'secondary'"
                    size="small"
                    @click="selectWindow(option.value)"
                />
            </div>
        </template>
        <PageState v-if="loading" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" :description="errorMessage(error)" />
        <div v-else-if="dashboard" class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="(values, key) in dashboard.capabilities" :key="key" class="card">
                <h2 class="mb-3 text-lg font-semibold">{{ key }}</h2>
                <dl class="grid grid-cols-1 gap-2 text-sm">
                    <div v-for="(value, name) in values" :key="name" class="flex justify-between gap-3">
                        <dt class="text-surface-500">{{ name }}</dt>
                        <dd class="font-medium">{{ formatValue(value) }}</dd>
                    </div>
                </dl>
            </div>
        </div>
    </PageToolbar>
</template>
