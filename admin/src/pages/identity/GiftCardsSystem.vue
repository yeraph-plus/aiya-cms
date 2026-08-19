<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { fetchGiftCardBatches, generateGiftCardBatch, closeGiftCardBatch, type GiftCardBatchDTO, type BatchPageDTO, type GenerateGiftCardBatchInput } from '@/api/gift-cards';
import PageState from '@/components/feedback/PageState.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';
import PagedTable from '@/components/data/PagedTable.vue';
import FilterBar from '@/components/data/FilterBar.vue';
import { hasCapability } from '@/auth/session';

const { t, locale } = useI18n();
const result = ref<BatchPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const generatedSecrets = ref<string[] | null>(null);
const canGenerate = hasCapability('gift_cards.batch_generate');
const filters = reactive({ status: null as string | null });
const form = reactive<GenerateGiftCardBatchInput>({
    quantity: 1,
    product_key: '',
    fulfillment_schema_version: '1',
    fulfillment_key: '',
    fulfillment_payload: {},
    expires_at: null,
    idempotency_key: `admin-${Date.now()}`,
    platform_key: 'card_platform',
    batch_key: null
});

function formatDate(value: string | null | undefined): string {
    return value ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-';
}

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchGiftCardBatches({ page: page.value, size: size.value, status: filters.status || undefined });
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

async function generate(): Promise<void> {
    try {
        form.fulfillment_payload = formPayload();
        const response = await generateGiftCardBatch(form);
        generatedSecrets.value = response.secrets ?? null;
        form.idempotency_key = `admin-${Date.now()}`;
        await load();
    } catch (caught) {
        error.value = caught;
    }
}

function formPayload(): Record<string, unknown> {
    return { ...form.fulfillment_payload };
}

async function closeBatch(batch: GiftCardBatchDTO): Promise<void> {
    try {
        await closeGiftCardBatch(batch.id, t('workbenches.giftCards.closeReason'));
        await load();
    } catch (caught) {
        error.value = caught;
    }
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.users.giftCards')" :description="t('workbenches.giftCards.description')" :loading="loading" @refresh="load">
        <SurfaceCard v-if="canGenerate" class="mb-4">
            <template #title>{{ t('workbenches.giftCards.generate') }}</template>
            <div class="grid grid-cols-12 gap-4">
                <div class="col-span-12 md:col-span-3 flex flex-col gap-2">
                    <label for="gift-quantity">{{ t('workbenches.giftCards.quantity') }}</label
                    ><InputNumber id="gift-quantity" v-model="form.quantity" :min="1" :max="10000" />
                </div>
                <div class="col-span-12 md:col-span-3 flex flex-col gap-2">
                    <label for="gift-product">{{ t('workbenches.giftCards.product') }}</label
                    ><InputText id="gift-product" v-model="form.product_key" />
                </div>
                <div class="col-span-12 md:col-span-3 flex flex-col gap-2">
                    <label for="gift-key">{{ t('workbenches.giftCards.fulfillmentKey') }}</label
                    ><InputText id="gift-key" v-model="form.fulfillment_key" />
                </div>
                <div class="col-span-12 md:col-span-3 flex flex-col gap-2">
                    <label for="gift-version">{{ t('workbenches.giftCards.schemaVersion') }}</label
                    ><InputText id="gift-version" v-model="form.fulfillment_schema_version" />
                </div>
                <div class="col-span-12 flex justify-end"><Button icon="pi pi-ticket" :label="t('workbenches.giftCards.generate')" @click="generate" /></div>
            </div>
        </SurfaceCard>

        <SurfaceCard v-if="generatedSecrets" class="mb-4 border-amber-500">
            <template #title>{{ t('workbenches.giftCards.secretsOnce') }}</template>
            <p class="mb-2 text-muted-color">{{ t('workbenches.giftCards.secretsHint') }}</p>
            <Textarea :model-value="generatedSecrets.join('\n')" rows="8" readonly fluid />
        </SurfaceCard>

        <SurfaceCard>
            <FilterBar :label="t('common.applyFilters')" @submit="applyFilters">
                <Select v-model="filters.status" :options="['active', 'closed', 'revoked']" show-clear :placeholder="t('common.all')" fluid />
            </FilterBar>
        </SurfaceCard>
        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="result && result.total === 0" state="empty" :title="t('workbenches.giftCards.empty')" :description="t('workbenches.giftCards.emptyDescription')" />
        <PagedTable v-else-if="result" :value="result.items" :loading="loading" :total-records="result.total" :page="result.page" :size="result.size" @update:page="onPage" @update:size="onSize">
            <Column field="batch_key" :header="t('workbenches.giftCards.batch')" style="min-width: 14rem" />
            <Column field="product_key" :header="t('workbenches.giftCards.product')" style="min-width: 12rem" />
            <Column field="quantity" :header="t('workbenches.giftCards.quantity')" />
            <Column field="available_count" :header="t('workbenches.giftCards.available')" />
            <Column field="redeemed_count" :header="t('workbenches.giftCards.redeemed')" />
            <Column field="status" :header="t('workbenches.status')"
                ><template #body="{ data }"><StatusTag :value="data.status" /></template
            ></Column>
            <Column field="created_at" :header="t('workbenches.giftCards.created')"
                ><template #body="{ data }">{{ formatDate(data.created_at) }}</template></Column
            >
            <Column :header="t('common.actions')"
                ><template #body="{ data }"><Button v-if="data.status === 'active'" text icon="pi pi-lock" :label="t('workbenches.giftCards.close')" @click="closeBatch(data)" /></template
            ></Column>
        </PagedTable>
    </PageShell>
</template>
