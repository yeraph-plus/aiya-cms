<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { cancelPaymentOrder, fetchPaymentOrder, fetchPaymentOrders, reconcilePaymentOrder, refundPaymentOrder, type OrderDTO, type OrderDetailDTO, type OrderPageDTO } from '@/api/payments';
import { hasCapability } from '@/auth/session';
import PagedTable from '@/components/data/PagedTable.vue';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import PageState from '@/components/feedback/PageState.vue';
import EntityDrawerShell from '@/components/shell/EntityDrawerShell.vue';
import FormDialogShell from '@/components/shell/FormDialogShell.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t, locale } = useI18n();
const states = ['created', 'pending', 'captured', 'partially_refunded', 'refunded', 'cancelled', 'failed'];
const filters = reactive({ state: null as string | null, subjectId: '', providerKey: '' });
const result = ref<OrderPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const detail = ref<OrderDetailDTO | null>(null);
const detailVisible = ref(false);
const detailLoading = ref(false);
const actionError = ref<unknown>(null);
const actionLoading = ref(false);
const refundVisible = ref(false);
const refundAmount = ref<number | null>(null);
const refundReason = ref('');
const canCancel = computed(() => hasCapability('payments.cancel'));
const canReconcile = computed(() => hasCapability('payments.reconcile'));
const canRefund = computed(() => hasCapability('payments.refund'));

async function load(resetPage = false): Promise<void> {
    if (resetPage) page.value = 1;
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchPaymentOrders({
            page: page.value,
            size: size.value,
            state: filters.state || undefined,
            subject_id: filters.subjectId.trim() || undefined,
            provider_key: filters.providerKey.trim() || undefined
        });
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

async function openOrder(order: OrderDTO): Promise<void> {
    detailVisible.value = true;
    detailLoading.value = true;
    actionError.value = null;
    try {
        detail.value = await fetchPaymentOrder(order.id);
    } catch (caught) {
        actionError.value = caught;
    } finally {
        detailLoading.value = false;
    }
}

function replaceOrder(order: OrderDTO): void {
    if (result.value) result.value = { ...result.value, items: result.value.items.map((item) => (item.id === order.id ? order : item)) };
    if (detail.value?.order.id === order.id) detail.value = { ...detail.value, order };
}

async function runOrderAction(action: 'cancel' | 'reconcile'): Promise<void> {
    if (!detail.value) return;
    actionLoading.value = true;
    actionError.value = null;
    try {
        const updated = action === 'cancel' ? await cancelPaymentOrder(detail.value.order.id) : await reconcilePaymentOrder(detail.value.order.id);
        replaceOrder(updated);
    } catch (caught) {
        actionError.value = caught;
    } finally {
        actionLoading.value = false;
    }
}

function openRefund(): void {
    refundAmount.value = null;
    refundReason.value = '';
    actionError.value = null;
    refundVisible.value = true;
}

function newIdempotencyKey(): string {
    return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `refund-${Date.now()}`;
}

async function submitRefund(): Promise<void> {
    if (!detail.value || !refundAmount.value || !refundReason.value.trim()) return;
    actionLoading.value = true;
    actionError.value = null;
    try {
        await refundPaymentOrder(detail.value.order.id, { amount: refundAmount.value, reason: refundReason.value.trim(), idempotency_key: newIdempotencyKey() });
        detail.value = await fetchPaymentOrder(detail.value.order.id);
        replaceOrder(detail.value.order);
        refundVisible.value = false;
    } catch (caught) {
        actionError.value = caught;
    } finally {
        actionLoading.value = false;
    }
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

function formatDate(value: string | null | undefined): string {
    return value ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-';
}

function formatMoney(amount: number, currency: string): string {
    try {
        return new Intl.NumberFormat(locale.value, { style: 'currency', currency }).format(amount / 100);
    } catch {
        return `${amount} ${currency}`;
    }
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.users.payments')" :description="t('workbenches.payments.description')" :loading="loading" @refresh="load()">
        <SurfaceCard>
            <form class="flex flex-wrap items-end gap-3" @submit.prevent="load(true)">
                <Select v-model="filters.state" :options="states" show-clear :placeholder="t('workbenches.status')" class="min-w-48" />
                <InputText v-model="filters.subjectId" :placeholder="t('workbenches.subjectId')" />
                <InputText v-model="filters.providerKey" :placeholder="t('workbenches.payments.provider')" />
                <Button type="submit" icon="pi pi-search" :label="t('workbenches.search')" />
            </form>
        </SurfaceCard>
        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="result?.total === 0" state="empty" :title="t('workbenches.payments.empty')" />
        <SurfaceCard v-else-if="result">
            <PagedTable :value="result.items" :total-records="result.total" :page="result.page" :size="result.size" :loading="loading" @update:page="onPage" @update:size="onSize">
                <Column field="order_reference" :header="t('workbenches.payments.reference')" />
                <Column field="subject_id" :header="t('workbenches.subjectId')" />
                <Column :header="t('workbenches.payments.amount')"><template #body="{ data }">{{ formatMoney(data.amount, data.currency) }}</template></Column>
                <Column field="provider_key" :header="t('workbenches.payments.provider')" />
                <Column field="state" :header="t('workbenches.status')"><template #body="{ data }"><Tag :value="data.state" /></template></Column>
                <Column field="created_at" :header="t('workbenches.payments.created')"><template #body="{ data }">{{ formatDate(data.created_at) }}</template></Column>
                <Column><template #body="{ data }"><Button :label="t('workbenches.view')" text @click="openOrder(data)" /></template></Column>
            </PagedTable>
        </SurfaceCard>

        <EntityDrawerShell v-model="detailVisible" :title="t('workbenches.payments.order')" :description="detail?.order.order_reference || ''" width-class="!w-full lg:!w-[56rem]">
            <PageState v-if="detailLoading" state="loading" />
            <ApiErrorMessage v-else-if="actionError" :error="actionError" />
            <div v-else-if="detail" class="flex flex-col gap-5">
                <SurfaceCard :title="detail.order.description">
                    <dl class="grid grid-cols-2 gap-3 text-sm">
                        <dt class="text-muted-color">{{ t('workbenches.status') }}</dt><dd><Tag :value="detail.order.state" /></dd>
                        <dt class="text-muted-color">{{ t('workbenches.payments.amount') }}</dt><dd>{{ formatMoney(detail.order.amount, detail.order.currency) }}</dd>
                        <dt class="text-muted-color">{{ t('workbenches.payments.captured') }}</dt><dd>{{ formatMoney(detail.order.captured_amount, detail.order.currency) }}</dd>
                        <dt class="text-muted-color">{{ t('workbenches.payments.refunded') }}</dt><dd>{{ formatMoney(detail.order.refunded_amount, detail.order.currency) }}</dd>
                    </dl>
                    <template #footer>
                        <div class="flex flex-wrap gap-2">
                            <Button v-if="canCancel && ['created', 'pending'].includes(detail.order.state)" :label="t('workbenches.payments.cancel')" severity="warn" :loading="actionLoading" @click="runOrderAction('cancel')" />
                            <Button v-if="canReconcile" :label="t('workbenches.payments.reconcile')" severity="secondary" :loading="actionLoading" @click="runOrderAction('reconcile')" />
                            <Button v-if="canRefund && detail.order.captured_amount > detail.order.refunded_amount" :label="t('workbenches.payments.refund')" severity="danger" @click="openRefund" />
                        </div>
                    </template>
                </SurfaceCard>
                <SurfaceCard :title="t('workbenches.payments.attempts')"><DataTable :value="detail.attempts" size="small"><Column field="attempt" header="#" /><Column field="provider_ref" :header="t('workbenches.payments.providerReference')" /><Column field="state" :header="t('workbenches.payments.state')" /><Column field="error_category" :header="t('workbenches.payments.error')" /></DataTable></SurfaceCard>
                <SurfaceCard :title="t('workbenches.payments.refunds')"><DataTable :value="detail.refunds" size="small"><Column field="refund_ref" :header="t('workbenches.payments.reference')" /><Column field="amount" :header="t('workbenches.payments.amount')" /><Column field="state" :header="t('workbenches.payments.state')" /><Column field="reason" :header="t('workbenches.reason')" /></DataTable></SurfaceCard>
            </div>
        </EntityDrawerShell>

        <FormDialogShell v-model="refundVisible" :title="t('workbenches.payments.refund')">
            <ApiErrorMessage v-if="actionError" :error="actionError" />
            <div class="flex flex-col gap-4">
                <InputNumber v-model="refundAmount" :min="1" :use-grouping="false" :placeholder="t('workbenches.payments.minorUnits')" />
                <Textarea v-model="refundReason" rows="4" :placeholder="t('workbenches.reason')" />
            </div>
            <template #footer><Button :label="t('workbenches.payments.refund')" severity="danger" :loading="actionLoading" :disabled="!refundAmount || !refundReason.trim()" @click="submitRefund" /></template>
        </FormDialogShell>
    </PageShell>
</template>
