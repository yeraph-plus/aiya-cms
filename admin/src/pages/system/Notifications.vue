<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import {
    cancelNotificationDelivery,
    fetchNotificationDeliveries,
    fetchNotificationDelivery,
    retryNotificationDelivery,
    type NotificationDeliveryDetailDTO,
    type NotificationDeliveryPageDTO,
    type NotificationDeliveryRecordDTO
} from '@/api/notifications';
import { hasCapability } from '@/auth/session';
import PagedTable from '@/components/data/PagedTable.vue';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import PageState from '@/components/feedback/PageState.vue';
import EntityDrawerShell from '@/components/shell/EntityDrawerShell.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SensitiveActionDialog from '@/components/shell/SensitiveActionDialog.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t, locale } = useI18n();
const statuses = ['pending', 'sending', 'delivered', 'unknown', 'failed', 'dead', 'cancelled'];
const filters = reactive({
    status: null as string | null,
    channel: '',
    providerKey: '',
    specKey: '',
    recipientId: ''
});
const result = ref<NotificationDeliveryPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const detail = ref<NotificationDeliveryDetailDTO | null>(null);
const drawerVisible = ref(false);
const detailLoading = ref(false);
const actionLoading = ref(false);
const actionError = ref<unknown>(null);
const cancelVisible = ref(false);
const retryVisible = ref(false);
const canCancel = computed(() => hasCapability('notification.cancel'));
const canRetry = computed(() => hasCapability('notification.retry'));

async function load(resetPage = false): Promise<void> {
    if (resetPage) page.value = 1;
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchNotificationDeliveries({
            page: page.value,
            size: size.value,
            status: filters.status || undefined,
            channel: filters.channel.trim() || undefined,
            provider_key: filters.providerKey.trim() || undefined,
            spec_key: filters.specKey.trim() || undefined,
            recipient_id: filters.recipientId.trim() || undefined
        });
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

async function openDelivery(delivery: NotificationDeliveryRecordDTO): Promise<void> {
    drawerVisible.value = true;
    detailLoading.value = true;
    actionError.value = null;
    try {
        detail.value = await fetchNotificationDelivery(delivery.id);
    } catch (caught) {
        actionError.value = caught;
    } finally {
        detailLoading.value = false;
    }
}

async function refreshDetail(): Promise<void> {
    if (!detail.value) return;
    detail.value = await fetchNotificationDelivery(detail.value.delivery.id);
    await load();
}

async function confirmAction(action: 'cancel' | 'retry'): Promise<void> {
    if (!detail.value) return;
    actionLoading.value = true;
    actionError.value = null;
    try {
        if (action === 'cancel') await cancelNotificationDelivery(detail.value.delivery.id);
        else await retryNotificationDelivery(detail.value.delivery.id);
        await refreshDetail();
        cancelVisible.value = false;
        retryVisible.value = false;
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
    return value
        ? new Intl.DateTimeFormat(locale.value, {
              dateStyle: 'medium',
              timeStyle: 'short'
          }).format(new Date(value))
        : '-';
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.system.notifications')" :description="t('workbenches.notifications.description')" :loading="loading" @refresh="load()">
        <Message severity="info" :closable="false">{{ t('workbenches.notifications.templateReserved') }}</Message>
        <SurfaceCard>
            <FilterBar :label="t('workbenches.search')" @submit="load(true)">
                <Select v-model="filters.status" :options="statuses" show-clear :placeholder="t('workbenches.status')" class="min-w-44" />
                <InputText v-model="filters.channel" :placeholder="t('workbenches.notifications.channel')" />
                <InputText v-model="filters.providerKey" :placeholder="t('workbenches.notifications.provider')" />
                <InputText v-model="filters.specKey" :placeholder="t('workbenches.notifications.specKey')" />
                <InputText v-model="filters.recipientId" :placeholder="t('workbenches.notifications.recipientId')" />
            </FilterBar>
        </SurfaceCard>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="result?.total === 0" state="empty" :title="t('workbenches.notifications.empty')" />
        <SurfaceCard v-else-if="result">
            <PagedTable :value="result.items" :total-records="result.total" :page="result.page" :size="result.size" :loading="loading" @update:page="onPage" @update:size="onSize">
                <Column field="status" :header="t('workbenches.status')"
                    ><template #body="{ data }"><StatusTag :value="data.status" /></template
                ></Column>
                <Column field="spec_key" :header="t('workbenches.notifications.specKey')" />
                <Column field="recipient_id" :header="t('workbenches.notifications.recipientId')" />
                <Column field="channel" :header="t('workbenches.notifications.channel')" />
                <Column field="provider_key" :header="t('workbenches.notifications.provider')" />
                <Column field="attempt" :header="t('workbenches.notifications.attempt')" />
                <Column field="created_at" :header="t('workbenches.notifications.createdAt')"
                    ><template #body="{ data }">{{ formatDate(data.created_at) }}</template></Column
                >
                <Column
                    ><template #body="{ data }"><Button :label="t('workbenches.view')" text @click="openDelivery(data)" /></template
                ></Column>
            </PagedTable>
        </SurfaceCard>

        <EntityDrawerShell v-model="drawerVisible" :title="t('workbenches.notifications.detail')" :description="detail?.delivery.id || ''" width-class="!w-full lg:!w-[56rem]">
            <PageState v-if="detailLoading" state="loading" />
            <ApiErrorMessage v-if="actionError" :error="actionError" />
            <div v-if="detail && !detailLoading" class="flex flex-col gap-5">
                <SurfaceCard>
                    <dl class="grid grid-cols-[10rem_1fr] gap-3 text-sm">
                        <dt class="text-muted-color">{{ t('workbenches.status') }}</dt>
                        <dd><StatusTag :value="detail.delivery.status" /></dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.notifications.specKey') }}
                        </dt>
                        <dd>
                            <code>{{ detail.delivery.spec_key }}</code>
                        </dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.notifications.recipientId') }}
                        </dt>
                        <dd>{{ detail.delivery.recipient_type }}:{{ detail.delivery.recipient_id }}</dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.notifications.maskedAddress') }}
                        </dt>
                        <dd>{{ detail.delivery.masked_address }}</dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.notifications.provider') }}
                        </dt>
                        <dd>{{ detail.delivery.provider_key }}</dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.notifications.error') }}
                        </dt>
                        <dd>
                            {{ detail.delivery.error_category || '-' }}
                            {{ detail.delivery.error_summary || '' }}
                        </dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.notifications.nextRetry') }}
                        </dt>
                        <dd>{{ formatDate(detail.delivery.next_retry_at) }}</dd>
                    </dl>
                    <template #footer>
                        <div class="flex flex-wrap gap-2">
                            <Button v-if="canCancel && detail.delivery.status === 'pending'" :label="t('workbenches.notifications.cancel')" severity="warn" @click="cancelVisible = true" />
                            <Button v-if="canRetry && ['pending', 'sending', 'unknown', 'failed', 'dead', 'cancelled'].includes(detail.delivery.status)" :label="t('workbenches.notifications.retry')" severity="danger" @click="retryVisible = true" />
                        </div>
                    </template>
                </SurfaceCard>
                <SurfaceCard :title="t('workbenches.notifications.attempts')">
                    <DataTable :value="detail.attempts" size="small">
                        <Column field="delivery_attempt" :header="t('workbenches.notifications.attempt')" />
                        <Column field="provider_key" :header="t('workbenches.notifications.provider')" />
                        <Column field="status" :header="t('workbenches.status')" />
                        <Column field="error_category" :header="t('workbenches.notifications.error')" />
                        <Column field="finished_at" :header="t('workbenches.notifications.finishedAt')"
                            ><template #body="{ data }">{{ formatDate(data.finished_at) }}</template></Column
                        >
                    </DataTable>
                </SurfaceCard>
            </div>
        </EntityDrawerShell>

        <SensitiveActionDialog
            v-model="cancelVisible"
            :title="t('workbenches.notifications.cancel')"
            :message="t('workbenches.notifications.cancelMessage')"
            :confirm-label="t('workbenches.notifications.cancel')"
            :loading="actionLoading"
            @confirm="confirmAction('cancel')"
        >
            <ApiErrorMessage v-if="actionError" :error="actionError" />
        </SensitiveActionDialog>
        <SensitiveActionDialog
            v-model="retryVisible"
            :title="t('workbenches.notifications.retry')"
            :message="t('workbenches.notifications.retryMessage')"
            :confirm-label="t('workbenches.notifications.retry')"
            :loading="actionLoading"
            @confirm="confirmAction('retry')"
        >
            <ApiErrorMessage v-if="actionError" :error="actionError" />
        </SensitiveActionDialog>
    </PageShell>
</template>
