<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';
import { fetchDashboard, type AdminDashboardDTO, type DashboardWindow } from '@/api/dashboard';
import { errorMessage } from '@/api/errors';
import { hasCapability } from '@/auth/session';
import PageState from '@/components/feedback/PageState.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t } = useI18n();
const router = useRouter();
const windows = computed<{ label: string; value: DashboardWindow }[]>(() => [
    { label: t('workbenches.dashboard.hours24'), value: '24h' },
    { label: t('workbenches.dashboard.days7'), value: '7d' },
    { label: t('workbenches.dashboard.days30'), value: '30d' }
]);
const windowValue = ref<DashboardWindow>('7d');
const dashboard = ref<AdminDashboardDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);

const sections = computed(() => dashboard.value?.sections ?? []);
const quickLinks = computed(() =>
    [
        {
            label: t('workbenches.dashboard.users'),
            to: '/users',
            capability: 'identity.users.read'
        },
        {
            label: t('workbenches.dashboard.content'),
            to: '/content/articles',
            capability: 'content.read'
        },
        {
            label: t('workbenches.dashboard.comments'),
            to: '/content/comments',
            capability: 'comments.read'
        },
        {
            label: t('workbenches.dashboard.community'),
            to: '/community/discussions',
            capability: 'community.read_admin'
        },
        {
            label: t('workbenches.dashboard.points'),
            to: '/users/points',
            capability: 'points.read'
        },
        {
            label: t('workbenches.dashboard.membership'),
            to: '/users/membership',
            capability: 'membership.read'
        }
    ].filter((item) => hasCapability(item.capability))
);

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
                <Button v-for="option in windows" :key="option.value" :label="option.label" :severity="windowValue === option.value ? 'primary' : 'secondary'" size="small" @click="selectWindow(option.value)" />
            </div>
        </template>
        <PageState v-if="loading" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" :description="errorMessage(error)" />
        <div v-else-if="dashboard" class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <SurfaceCard v-for="section in sections" :key="section.key" :title="section.key">
                <dl class="grid grid-cols-1 gap-2 text-sm">
                    <div v-for="metric in section.metrics" :key="metric.key" class="flex justify-between gap-3">
                        <dt class="text-surface-500">{{ metric.key }}</dt>
                        <dd class="font-medium">{{ formatValue(metric.value) }}</dd>
                    </div>
                </dl>
            </SurfaceCard>
            <SurfaceCard :title="t('workbenches.dashboard.quickLinks')" class="md:col-span-2 xl:col-span-3">
                <div class="flex flex-wrap gap-2">
                    <Button v-for="link in quickLinks" :key="link.to" :label="link.label" text icon="pi pi-arrow-right" icon-pos="right" @click="router.push(link.to)" />
                    <span v-if="quickLinks.length === 0" class="text-muted-color">{{ t('workbenches.dashboard.noQuickLinks') }}</span>
                </div>
            </SurfaceCard>
        </div>
    </PageShell>
</template>
