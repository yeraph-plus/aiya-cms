<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { cancelPaymentOrder, fetchPaymentOrders, reconcilePaymentOrder, refundPaymentOrder, type OrderDTO, type OrderPageDTO } from '@/api/payments';
import { hasCapability } from '@/auth/session';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import PageState from '@/components/feedback/PageState.vue';
import FormDialogShell from '@/components/shell/FormDialogShell.vue';

const props = defineProps<{ subjectId: string }>();
const { t } = useI18n();
const result = ref<OrderPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const selected = ref<OrderDTO | null>(null);
const refundVisible = ref(false);
const amount = ref<number | null>(null);
const reason = ref('');
const saving = ref(false);
const canCancel = computed(() => hasCapability('payments.cancel'));
const canReconcile = computed(() => hasCapability('payments.reconcile'));
const canRefund = computed(() => hasCapability('payments.refund'));

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchPaymentOrders({ subject_type: 'identity', subject_id: props.subjectId, page: 1, size: 50 });
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function replaceOrder(order: OrderDTO): void {
    if (result.value) result.value = { ...result.value, items: result.value.items.map((item) => (item.id === order.id ? order : item)) };
}

async function run(order: OrderDTO, action: 'cancel' | 'reconcile'): Promise<void> {
    saving.value = true;
    error.value = null;
    try {
        replaceOrder(action === 'cancel' ? await cancelPaymentOrder(order.id) : await reconcilePaymentOrder(order.id));
    } catch (caught) {
        error.value = caught;
    } finally {
        saving.value = false;
    }
}

function openRefund(order: OrderDTO): void {
    selected.value = order;
    amount.value = null;
    reason.value = '';
    error.value = null;
    refundVisible.value = true;
}

async function submitRefund(): Promise<void> {
    if (!selected.value || !amount.value || !reason.value.trim()) return;
    saving.value = true;
    error.value = null;
    try {
        await refundPaymentOrder(selected.value.id, { amount: amount.value, reason: reason.value.trim(), idempotency_key: typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `refund-${Date.now()}` });
        await load();
        refundVisible.value = false;
    } catch (caught) {
        error.value = caught;
    } finally {
        saving.value = false;
    }
}

watch(() => props.subjectId, () => void load(), { immediate: true });
</script>

<template>
    <ApiErrorMessage v-if="error && !refundVisible" :error="error" />
    <PageState v-if="loading && !result" state="loading" />
    <PageState v-else-if="result?.total === 0" state="empty" :title="t('workbenches.payments.empty')" />
    <DataTable v-else :value="result?.items ?? []" size="small" responsive-layout="scroll">
        <Column field="order_reference" :header="t('workbenches.payments.reference')" />
        <Column field="amount" :header="t('workbenches.payments.amount')"><template #body="{ data }">{{ data.amount }} {{ data.currency }}</template></Column>
        <Column field="state" :header="t('workbenches.payments.state')"><template #body="{ data }"><Tag :value="data.state" /></template></Column>
        <Column><template #body="{ data }"><div class="flex flex-wrap gap-1"><Button v-if="canCancel && ['created', 'pending'].includes(data.state)" :label="t('workbenches.payments.cancel')" text severity="warn" :loading="saving" @click="run(data, 'cancel')" /><Button v-if="canReconcile" :label="t('workbenches.payments.reconcile')" text :loading="saving" @click="run(data, 'reconcile')" /><Button v-if="canRefund && data.captured_amount > data.refunded_amount" :label="t('workbenches.payments.refund')" text severity="danger" @click="openRefund(data)" /></div></template></Column>
    </DataTable>

    <FormDialogShell v-model="refundVisible" :title="t('workbenches.payments.refund')">
        <ApiErrorMessage v-if="error" :error="error" />
        <div class="flex flex-col gap-4"><InputNumber v-model="amount" :min="1" :use-grouping="false" /><Textarea v-model="reason" rows="4" :placeholder="t('workbenches.reason')" /></div>
        <template #footer><Button :label="t('workbenches.payments.refund')" severity="danger" :loading="saving" :disabled="!amount || !reason.trim()" @click="submitRefund" /></template>
    </FormDialogShell>
</template>
