<script setup lang="ts">
import { ref, watch } from 'vue';
import { useToast } from 'primevue/usetoast';
import { adjustPoints, fetchAdminPointsLedger, type AdminPointsLedgerQuery, type LedgerEntryDTO, type PointsAdjustInput, type AdminPointsViewDTO } from '@/api/points';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import PageState from '@/components/feedback/PageState.vue';
import PagedTable from '@/components/data/PagedTable.vue';

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
        validationError.value = '请填写非零调整数量和调整原因。';
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
        toast.add({ severity: 'success', summary: '积分调整已提交', detail: `${entry.amount > 0 ? '增加' : '扣除'} ${Math.abs(entry.amount)} 积分。`, life: 4000 });
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
    return value ? new Date(value).toLocaleString() : '永久';
}

watch(
    () => props.subjectId,
    () => void loadLedger(true),
    { immediate: true }
);
</script>

<template>
    <div class="flex flex-col gap-6">
        <Message severity="info" :closable="false">正数调整进入 perpetual 桶；负数调整按 expires_at 从早到晚自动扣除积分桶。无需、也不能手动指定桶；余额不足时按后端规则进入 debt。</Message>

        <div class="card flex flex-col gap-4">
            <div class="flex flex-wrap items-end gap-3">
                <div class="flex min-w-56 flex-1 flex-col gap-2">
                    <label for="points-program" class="font-medium">积分计划（可选）</label>
                    <InputText id="points-program" v-model="programKey" placeholder="默认 credit" :disabled="submitting || ledgerLoading" />
                </div>
                <Button label="读取计划" icon="pi pi-refresh" severity="secondary" :loading="ledgerLoading" @click="loadLedger(true)" />
            </div>
            <small class="text-muted-color">留空时使用后端默认计划 credit。当前计划必须是后端已启用的 program。</small>
        </div>

        <PageState v-if="ledgerLoading && !pointsView" state="loading" />
        <PageState v-else-if="ledgerError" state="error" :error="ledgerError" description="积分账户信息读取失败，请检查 points.read 权限或计划 key。" />
        <template v-else-if="pointsView">
            <div class="grid grid-cols-2 gap-3">
                <div class="rounded-border border border-surface-200 dark:border-surface-700 p-3">
                    <span class="block text-sm text-muted-color">当前计划</span>
                    <strong>{{ pointsView.balance?.program_key || programKey.trim() || 'credit' }}</strong>
                </div>
                <div class="rounded-border border border-surface-200 dark:border-surface-700 p-3">
                    <span class="block text-sm text-muted-color">可用余额</span>
                    <strong>{{ pointsView.balance?.balance ?? 0 }}</strong>
                </div>
            </div>
            <Message v-if="!pointsView.balance" severity="info" :closable="false">该用户在当前计划尚未开户；首次积分调整会按后端规则自动开户。</Message>

            <div>
                <div class="mb-3 font-semibold">积分桶</div>
                <DataTable :value="pointsView.buckets ?? []" size="small" responsive-layout="scroll">
                    <Column field="bucket_type" header="类型" />
                    <Column field="expiration_identity" header="来源" />
                    <Column field="expires_at" header="到期时间">
                        <template #body="{ data }">{{ formatDate(data.expires_at) }}</template>
                    </Column>
                    <Column field="amount" header="剩余" />
                </DataTable>
            </div>

            <div>
                <div class="mb-3 font-semibold">积分流水</div>
                <PagedTable :value="pointsView.ledger.items" :loading="ledgerLoading" :total-records="pointsView.ledger.total" :page="pointsView.ledger.page" :size="pointsView.ledger.size" @update:page="onLedgerPage" @update:size="onLedgerSize">
                    <Column field="created_at" header="时间" style="min-width: 10rem">
                        <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
                    </Column>
                    <Column field="entry_type" header="类型" />
                    <Column field="amount" header="金额" />
                    <Column field="id" header="流水 ID" style="min-width: 13rem" />
                </PagedTable>
            </div>
        </template>

        <div class="border-t border-surface-200 dark:border-surface-700 pt-6 flex flex-col gap-4">
            <div class="font-semibold">调整账户</div>
            <div class="flex flex-col gap-2">
                <label for="points-amount" class="font-medium">调整数量</label>
                <InputNumber id="points-amount" v-model="amount" :use-grouping="false" show-buttons :disabled="submitting" />
                <small class="text-muted-color">正数增加，负数扣除，不能为 0。</small>
            </div>
            <div class="flex flex-col gap-2">
                <label for="points-reason" class="font-medium">调整原因</label>
                <Textarea id="points-reason" v-model="reason" rows="4" auto-resize maxlength="500" placeholder="填写可审计的调整原因" :disabled="submitting" />
            </div>
            <Message v-if="validationError" severity="warn" :closable="false">{{ validationError }}</Message>
            <ApiErrorMessage v-if="error" :error="error" />
            <Message v-if="result" severity="success" :closable="false">流水 {{ result.id }} 已创建，金额 {{ result.amount }}。</Message>
            <div class="flex justify-end">
                <Button label="提交积分调整" icon="pi pi-check" :loading="submitting" @click="submit" />
            </div>
        </div>
    </div>
</template>
