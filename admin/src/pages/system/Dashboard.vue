<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { fetchDashboard, type AdminDashboardDTO, type DashboardWindow } from '@/api/dashboard';
import { errorMessage } from '@/api/errors';
import PageState from '@/components/feedback/PageState.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t } = useI18n();
const windows = computed<{ label: string; value: DashboardWindow }[]>(() => [
    { label: t('workbenches.dashboard.hours24'), value: '24h' },
    { label: t('workbenches.dashboard.days7'), value: '7d' },
    { label: t('workbenches.dashboard.days30'), value: '30d' }
]);
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
    <PageShell :title="t('routes.dashboard')" :description="t('workbenches.dashboard.description')" :loading="loading" @refresh="load">
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
            <SurfaceCard v-for="(values, key) in dashboard.capabilities" :key="key" :title="String(key)">
                <dl class="grid grid-cols-1 gap-2 text-sm">
                    <div v-for="(value, name) in values" :key="name" class="flex justify-between gap-3">
                        <dt class="text-surface-500">{{ name }}</dt>
                        <dd class="font-medium">{{ formatValue(value) }}</dd>
                    </div>
                </dl>
            </SurfaceCard>
        </div>
    </PageShell>
</template>
