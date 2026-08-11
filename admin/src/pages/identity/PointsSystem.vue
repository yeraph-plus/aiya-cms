<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { fetchAdminPointsLedger, type AdminPointsViewDTO } from '@/api/points';
import { hasCapability } from '@/auth/session';
import PagedTable from '@/components/data/PagedTable.vue';
import PageState from '@/components/feedback/PageState.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';
import PointsAdjustDrawer from './PointsAdjustDrawer.vue';

const { t, locale } = useI18n();
const subjectId = ref('');
const programKey = ref('credit');
const result = ref<AdminPointsViewDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const searched = ref(false);
const canAdjust = computed(() => hasCapability('points.adjust'));

async function load(resetPage = false): Promise<void> {
    if (!subjectId.value.trim()) return;
    if (resetPage) page.value = 1;
    loading.value = true;
    error.value = null;
    searched.value = true;
    try {
        result.value = await fetchAdminPointsLedger({ subject_type: 'identity', subject_id: subjectId.value.trim(), program_key: programKey.value.trim() || 'credit', page: page.value, size: size.value });
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function onPage(value: number): void {
    page.value = value;
    void load();
}

function onSize(value: number): void {
    size.value = value;
    void load(true);
}

function formatDate(value: string | null | undefined): string {
    return value ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : t('workbenches.never');
}
</script>

<template>
    <PageShell :title="t('routes.users.points')" :description="t('workbenches.points.description')" :loading="loading" @refresh="load">
        <SurfaceCard :description="t('workbenches.points.programReserved')">
            <form class="flex flex-wrap items-end gap-3" @submit.prevent="load(true)">
                <div class="flex min-w-64 flex-1 flex-col gap-2">
                    <label for="points-subject" class="font-medium">{{ t('workbenches.subjectId') }}</label>
                    <InputText id="points-subject" v-model="subjectId" required />
                </div>
                <div class="flex min-w-48 flex-col gap-2">
                    <label for="points-program-global" class="font-medium">{{ t('workbenches.points.programKey') }}</label>
                    <InputText id="points-program-global" v-model="programKey" required />
                </div>
                <Button type="submit" icon="pi pi-search" :label="t('workbenches.search')" :loading="loading" />
            </form>
        </SurfaceCard>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="!searched" state="empty" :title="t('workbenches.points.enterSubject')" />
        <template v-else-if="result">
            <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
                <SurfaceCard :title="t('workbenches.points.balance')"><strong class="text-3xl">{{ result.balance?.balance ?? 0 }}</strong></SurfaceCard>
                <SurfaceCard :title="t('workbenches.points.program')"><strong>{{ result.balance?.program_key ?? programKey }}</strong></SurfaceCard>
                <SurfaceCard :title="t('workbenches.points.bucketCount')"><strong class="text-3xl">{{ (result.buckets ?? []).length }}</strong></SurfaceCard>
            </div>
            <SurfaceCard :title="t('workbenches.points.buckets')">
                <DataTable :value="result.buckets ?? []" size="small">
                    <Column field="bucket_type" :header="t('workbenches.points.type')" />
                    <Column field="amount" :header="t('workbenches.points.amount')" />
                    <Column field="expires_at" :header="t('workbenches.points.expires')"><template #body="{ data }">{{ formatDate(data.expires_at) }}</template></Column>
                </DataTable>
            </SurfaceCard>
            <SurfaceCard :title="t('workbenches.points.ledger')">
                <PagedTable :value="result.ledger.items" :total-records="result.ledger.total" :page="result.ledger.page" :size="result.ledger.size" :loading="loading" @update:page="onPage" @update:size="onSize">
                    <Column field="created_at" :header="t('workbenches.points.time')"><template #body="{ data }">{{ formatDate(data.created_at) }}</template></Column>
                    <Column field="entry_type" :header="t('workbenches.points.type')" />
                    <Column field="amount" :header="t('workbenches.points.amount')" />
                    <Column field="id" header="ID" />
                </PagedTable>
            </SurfaceCard>
            <SurfaceCard v-if="canAdjust" :title="t('workbenches.points.adjust')">
                <PointsAdjustDrawer :subject-id="subjectId.trim()" @completed="load(true)" />
            </SurfaceCard>
        </template>
    </PageShell>
</template>
