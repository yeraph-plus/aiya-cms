<script setup lang="ts">
import { ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useToast } from 'primevue/usetoast';
import { adjustPoints, fetchAdminPointsLedger, type AdminPointsLedgerQuery, type LedgerEntryDTO, type PointsAdjustInput, type AdminPointsViewDTO } from '@/api/points';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import PageState from '@/components/feedback/PageState.vue';
import PagedTable from '@/components/data/PagedTable.vue';

const { t, locale } = useI18n();
const props = defineProps<{ subjectId: string }>();

const emit = defineEmits<{
    completed: [entry: LedgerEntryDTO];
}>();

const toast = useToast();
const programKey = ref('');
const amount = ref<number | null>(null);
const reason = ref('');
const idempotencyKey = ref(newIdempotencyKey());
const submitting = ref(false);
const validationError = ref<string | null>(null);
const error = ref<unknown>(null);
const result = ref<LedgerEntryDTO | null>(null);
const pointsView = ref<AdminPointsViewDTO | null>(null);
const ledgerLoading = ref(false);
const ledgerError = ref<unknown>(null);
const ledgerPage = ref(1);
const ledgerSize = ref(10);

function newIdempotencyKey(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    return `points-adjust-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function ledgerQuery(): AdminPointsLedgerQuery {
    const query: AdminPointsLedgerQuery = {
        subject_id: props.subjectId,
        page: ledgerPage.value,
        size: ledgerSize.value
    };
    const normalizedProgramKey = programKey.value.trim();
    if (normalizedProgramKey) query.program_key = normalizedProgramKey;
    return query;
}

async function loadLedger(resetPage = false): Promise<void> {
    if (resetPage) ledgerPage.value = 1;
    ledgerLoading.value = true;
    ledgerError.value = null;
    try {
        pointsView.value = await fetchAdminPointsLedger(ledgerQuery());
    } catch (caught) {
        ledgerError.value = caught;
    } finally {
        ledgerLoading.value = false;
    }
}

async function submit(): Promise<void> {
    const normalizedReason = reason.value.trim();
    const normalizedProgramKey = programKey.value.trim();
    if (!normalizedReason || amount.value === null || amount.value === 0) {
        validationError.value = t('workbenches.points.validation');
        return;
    }

    validationError.value = null;
    error.value = null;
    submitting.value = true;
    try {
        const body: PointsAdjustInput = {
            subject_type: 'identity',
            subject_id: props.subjectId,
            amount: amount.value,
            reason: normalizedReason,
            idempotency_key: idempotencyKey.value,
            ...(normalizedProgramKey ? { program_key: normalizedProgramKey } : {})
        };
        const entry = await adjustPoints(body);
        result.value = entry;
        await loadLedger(true);
        toast.add({ severity: 'success', summary: t('workbenches.points.success'), detail: t('workbenches.points.successDetail', { action: t(entry.amount > 0 ? 'workbenches.points.increase' : 'workbenches.points.deduct'), amount: Math.abs(entry.amount) }), life: 4000 });
        emit('completed', entry);
        amount.value = null;
        reason.value = '';
        idempotencyKey.value = newIdempotencyKey();
    } catch (caught) {
        error.value = caught;
    } finally {
        submitting.value = false;
    }
}

function onLedgerPage(value: number): void {
    ledgerPage.value = value;
    void loadLedger();
}

function onLedgerSize(value: number): void {
    ledgerSize.value = value;
    ledgerPage.value = 1;
    void loadLedger();
}

function formatDate(value: string | null | undefined): string {
    return value ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : t('workbenches.never');
}

watch(
    () => props.subjectId,
    () => void loadLedger(true),
    { immediate: true }
);
</script>

<template>
    <div class="flex flex-col gap-6">
        <Message severity="info" :closable="false">{{ t('workbenches.points.adjustPolicy') }}</Message>

        <div class="card flex flex-col gap-4">
            <div class="flex flex-wrap items-end gap-3">
                <div class="flex min-w-56 flex-1 flex-col gap-2">
                    <label for="points-program" class="font-medium">{{ t('workbenches.points.programOptional') }}</label>
                    <InputText id="points-program" v-model="programKey" :placeholder="t('workbenches.points.defaultProgram')" :disabled="submitting || ledgerLoading" />
                </div>
                <Button :label="t('workbenches.points.loadProgram')" icon="pi pi-refresh" severity="secondary" :loading="ledgerLoading" @click="loadLedger(true)" />
            </div>
            <small class="text-muted-color">{{ t('workbenches.points.defaultProgramHint') }}</small>
        </div>

        <PageState v-if="ledgerLoading && !pointsView" state="loading" />
        <PageState v-else-if="ledgerError" state="error" :error="ledgerError" :description="t('workbenches.points.ledgerError')" />
        <template v-else-if="pointsView">
            <div class="grid grid-cols-2 gap-3">
                <div class="rounded-border border border-surface-200 dark:border-surface-700 p-3">
                    <span class="block text-sm text-muted-color">{{ t('workbenches.points.program') }}</span>
                    <strong>{{ pointsView.balance?.program_key || programKey.trim() || 'credit' }}</strong>
                </div>
                <div class="rounded-border border border-surface-200 dark:border-surface-700 p-3">
                    <span class="block text-sm text-muted-color">{{ t('workbenches.points.balance') }}</span>
                    <strong>{{ pointsView.balance?.balance ?? 0 }}</strong>
                </div>
            </div>
            <Message v-if="!pointsView.balance" severity="info" :closable="false">{{ t('workbenches.points.unopened') }}</Message>

            <div>
                <div class="mb-3 font-semibold">{{ t('workbenches.points.buckets') }}</div>
                <DataTable :value="pointsView.buckets ?? []" size="small" responsive-layout="scroll">
                    <Column field="bucket_type" :header="t('workbenches.points.type')" />
                    <Column field="expiration_identity" :header="t('workbenches.points.source')" />
                    <Column field="expires_at" :header="t('workbenches.points.expires')">
                        <template #body="{ data }">{{ formatDate(data.expires_at) }}</template>
                    </Column>
                    <Column field="amount" :header="t('workbenches.points.remaining')" />
                </DataTable>
            </div>

            <div>
                <div class="mb-3 font-semibold">{{ t('workbenches.points.ledger') }}</div>
                <PagedTable :value="pointsView.ledger.items" :loading="ledgerLoading" :total-records="pointsView.ledger.total" :page="pointsView.ledger.page" :size="pointsView.ledger.size" @update:page="onLedgerPage" @update:size="onLedgerSize">
                    <Column field="created_at" :header="t('workbenches.points.time')" style="min-width: 10rem">
                        <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
                    </Column>
                    <Column field="entry_type" :header="t('workbenches.points.type')" />
                    <Column field="amount" :header="t('workbenches.points.amount')" />
                    <Column field="id" :header="t('workbenches.points.entryId')" style="min-width: 13rem" />
                </PagedTable>
            </div>
        </template>

        <div class="border-t border-surface-200 dark:border-surface-700 pt-6 flex flex-col gap-4">
            <div class="font-semibold">{{ t('workbenches.points.adjustAccount') }}</div>
            <div class="flex flex-col gap-2">
                <label for="points-amount" class="font-medium">{{ t('workbenches.points.adjustAmount') }}</label>
                <InputNumber id="points-amount" v-model="amount" :use-grouping="false" show-buttons :disabled="submitting" />
                <small class="text-muted-color">{{ t('workbenches.points.adjustAmountHint') }}</small>
            </div>
            <div class="flex flex-col gap-2">
                <label for="points-reason" class="font-medium">{{ t('workbenches.points.adjustReason') }}</label>
                <Textarea id="points-reason" v-model="reason" rows="4" auto-resize maxlength="500" :placeholder="t('workbenches.points.adjustReasonPlaceholder')" :disabled="submitting" />
            </div>
            <Message v-if="validationError" severity="warn" :closable="false">{{ validationError }}</Message>
            <ApiErrorMessage v-if="error" :error="error" />
            <Message v-if="result" severity="success" :closable="false">{{ t('workbenches.points.createdEntry', { id: result.id, amount: result.amount }) }}</Message>
            <div class="flex justify-end">
                <Button :label="t('workbenches.points.submitAdjust')" icon="pi pi-check" :loading="submitting" @click="submit" />
            </div>
        </div>
    </div>
</template>
