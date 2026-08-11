<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { cancelSubscription, fetchMembershipLevels, fetchSubscriptionRenewals, fetchSubscriptions, terminateSubscription, type LevelDTO, type RenewalPageDTO, type SubscriptionDTO, type SubscriptionPageDTO } from '@/api/membership';
import { hasCapability } from '@/auth/session';
import PagedTable from '@/components/data/PagedTable.vue';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import PageState from '@/components/feedback/PageState.vue';
import EntityDrawerShell from '@/components/shell/EntityDrawerShell.vue';
import FormDialogShell from '@/components/shell/FormDialogShell.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t, locale } = useI18n();
const levels = ref<LevelDTO[]>([]);
const subscriptions = ref<SubscriptionPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const selected = ref<SubscriptionDTO | null>(null);
const renewals = ref<RenewalPageDTO | null>(null);
const renewalsVisible = ref(false);
const renewalsLoading = ref(false);
const actionVisible = ref(false);
const actionType = ref<'cancel' | 'terminate'>('cancel');
const reason = ref('');
const actionLoading = ref(false);
const actionError = ref<unknown>(null);
const canManage = computed(() => hasCapability('membership.manage'));

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        const [nextLevels, nextSubscriptions] = await Promise.all([fetchMembershipLevels(), fetchSubscriptions({ page: page.value, size: size.value })]);
        levels.value = nextLevels;
        subscriptions.value = nextSubscriptions;
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
    page.value = 1;
    void load();
}

async function openRenewals(subscription: SubscriptionDTO): Promise<void> {
    selected.value = subscription;
    renewals.value = null;
    renewalsVisible.value = true;
    renewalsLoading.value = true;
    try {
        renewals.value = await fetchSubscriptionRenewals(subscription.id, { page: 1, size: 50 });
    } catch (caught) {
        actionError.value = caught;
    } finally {
        renewalsLoading.value = false;
    }
}

function openAction(subscription: SubscriptionDTO, action: 'cancel' | 'terminate'): void {
    selected.value = subscription;
    actionType.value = action;
    reason.value = '';
    actionError.value = null;
    actionVisible.value = true;
}

async function submitAction(): Promise<void> {
    if (!selected.value || !reason.value.trim()) return;
    actionLoading.value = true;
    actionError.value = null;
    try {
        const body = { subscription_id: selected.value.id, reason: reason.value.trim() };
        const updated = actionType.value === 'cancel' ? await cancelSubscription(selected.value.id, body) : await terminateSubscription(selected.value.id, body);
        if (subscriptions.value) subscriptions.value = { ...subscriptions.value, items: subscriptions.value.items.map((item) => (item.id === updated.id ? updated : item)) };
        actionVisible.value = false;
    } catch (caught) {
        actionError.value = caught;
    } finally {
        actionLoading.value = false;
    }
}

function formatDate(value: string | null | undefined): string {
    return value ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-';
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.users.membership')" :description="t('workbenches.membership.description')" :loading="loading" @refresh="load">
        <Message severity="info" :closable="false">{{ t('workbenches.membership.levelReserved') }}</Message>
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <SurfaceCard v-for="level in levels" :key="level.level_key" :title="level.display_name" :description="level.level_key">
                <dl class="grid grid-cols-2 gap-2 text-sm">
                    <dt class="text-muted-color">{{ t('workbenches.membership.tier') }}</dt><dd>{{ level.tier_rank }}</dd>
                    <dt class="text-muted-color">{{ t('workbenches.membership.cycle') }}</dt><dd>{{ t('workbenches.membership.days', { count: level.cycle_days }) }}</dd>
                    <dt class="text-muted-color">{{ t('workbenches.membership.points') }}</dt><dd>{{ level.grant_points }}</dd>
                    <dt class="text-muted-color">{{ t('workbenches.status') }}</dt><dd><Tag :value="level.status" /></dd>
                </dl>
            </SurfaceCard>
        </div>
        <PageState v-if="loading && !subscriptions" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="subscriptions?.total === 0" state="empty" :title="t('workbenches.membership.empty')" />
        <SurfaceCard v-else-if="subscriptions" :title="t('workbenches.membership.subscriptions')">
            <PagedTable :value="subscriptions.items" :total-records="subscriptions.total" :page="subscriptions.page" :size="subscriptions.size" :loading="loading" @update:page="onPage" @update:size="onSize">
                <Column field="subject_id" :header="t('workbenches.subjectId')" />
                <Column field="level_key" :header="t('workbenches.membership.level')" />
                <Column field="status" :header="t('workbenches.status')"><template #body="{ data }"><Tag :value="data.status" /></template></Column>
                <Column field="cycle_end" :header="t('workbenches.membership.cycleEnd')"><template #body="{ data }">{{ formatDate(data.cycle_end) }}</template></Column>
                <Column field="renewal_count" :header="t('workbenches.membership.renewals')" />
                <Column :header="t('common.moreActions')">
                    <template #body="{ data }">
                        <div class="flex flex-wrap gap-1">
                            <Button :label="t('workbenches.membership.viewRenewals')" text @click="openRenewals(data)" />
                            <Button v-if="canManage && data.status === 'active'" :label="t('workbenches.membership.cancel')" text severity="warn" @click="openAction(data, 'cancel')" />
                            <Button v-if="canManage && data.status !== 'terminated'" :label="t('workbenches.membership.terminate')" text severity="danger" @click="openAction(data, 'terminate')" />
                        </div>
                    </template>
                </Column>
            </PagedTable>
        </SurfaceCard>

        <EntityDrawerShell v-model="renewalsVisible" :title="t('workbenches.membership.renewals')" :description="selected?.id || ''">
            <PageState v-if="renewalsLoading" state="loading" />
            <ApiErrorMessage v-else-if="actionError" :error="actionError" />
            <DataTable v-else :value="renewals?.items ?? []" size="small">
                <Column field="cycle_start" :header="t('workbenches.membership.start')"><template #body="{ data }">{{ formatDate(data.cycle_start) }}</template></Column>
                <Column field="cycle_end" :header="t('workbenches.membership.end')"><template #body="{ data }">{{ formatDate(data.cycle_end) }}</template></Column>
                <Column field="granted_points" :header="t('workbenches.membership.points')" />
                <Column field="outcome" :header="t('workbenches.membership.outcome')" />
            </DataTable>
        </EntityDrawerShell>

        <FormDialogShell v-model="actionVisible" :title="t(`workbenches.membership.${actionType}`)">
            <ApiErrorMessage v-if="actionError" :error="actionError" />
            <Textarea v-model="reason" rows="4" class="w-full" :placeholder="t('workbenches.reason')" />
            <template #footer><Button :label="t(`workbenches.membership.${actionType}`)" severity="danger" :loading="actionLoading" :disabled="!reason.trim()" @click="submitAction" /></template>
        </FormDialogShell>
    </PageShell>
</template>
