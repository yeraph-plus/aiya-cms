<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { cancelSubscription, fetchSubscriptions, terminateSubscription, type SubscriptionDTO, type SubscriptionPageDTO } from '@/api/membership';
import { hasCapability } from '@/auth/session';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import PageState from '@/components/feedback/PageState.vue';
import FormDialogShell from '@/components/shell/FormDialogShell.vue';

const props = defineProps<{ subjectId: string }>();
const { t, locale } = useI18n();
const result = ref<SubscriptionPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const selected = ref<SubscriptionDTO | null>(null);
const action = ref<'cancel' | 'terminate'>('cancel');
const reason = ref('');
const dialogVisible = ref(false);
const saving = ref(false);
const canManage = computed(() => hasCapability('membership.manage'));

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchSubscriptions({ subject_type: 'identity', subject_id: props.subjectId, page: 1, size: 50 });
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function openAction(subscription: SubscriptionDTO, nextAction: 'cancel' | 'terminate'): void {
    selected.value = subscription;
    action.value = nextAction;
    reason.value = '';
    error.value = null;
    dialogVisible.value = true;
}

async function submit(): Promise<void> {
    if (!selected.value || !reason.value.trim()) return;
    saving.value = true;
    error.value = null;
    try {
        const body = { subscription_id: selected.value.id, reason: reason.value.trim() };
        const updated = action.value === 'cancel' ? await cancelSubscription(selected.value.id, body) : await terminateSubscription(selected.value.id, body);
        if (result.value) result.value = { ...result.value, items: result.value.items.map((item) => (item.id === updated.id ? updated : item)) };
        dialogVisible.value = false;
    } catch (caught) {
        error.value = caught;
    } finally {
        saving.value = false;
    }
}

function formatDate(value: string): string {
    return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(new Date(value));
}

watch(() => props.subjectId, () => void load(), { immediate: true });
</script>

<template>
    <PageState v-if="loading && !result" state="loading" />
    <PageState v-else-if="error && !dialogVisible" state="error" :error="error" />
    <PageState v-else-if="result?.total === 0" state="empty" :title="t('workbenches.membership.empty')" />
    <DataTable v-else :value="result?.items ?? []" size="small" responsive-layout="scroll">
        <Column field="level_key" :header="t('workbenches.membership.level')" />
        <Column field="status" :header="t('workbenches.status')"><template #body="{ data }"><Tag :value="data.status" /></template></Column>
        <Column field="cycle_end" :header="t('workbenches.membership.cycleEnd')"><template #body="{ data }">{{ formatDate(data.cycle_end) }}</template></Column>
        <Column v-if="canManage"><template #body="{ data }"><div class="flex gap-1"><Button v-if="data.status === 'active'" :label="t('workbenches.membership.cancel')" text severity="warn" @click="openAction(data, 'cancel')" /><Button v-if="data.status !== 'terminated'" :label="t('workbenches.membership.terminate')" text severity="danger" @click="openAction(data, 'terminate')" /></div></template></Column>
    </DataTable>

    <FormDialogShell v-model="dialogVisible" :title="t(`workbenches.membership.${action}`)">
        <ApiErrorMessage v-if="error" :error="error" />
        <Textarea v-model="reason" rows="4" class="w-full" :placeholder="t('workbenches.reason')" />
        <template #footer><Button :label="t(`workbenches.membership.${action}`)" severity="danger" :loading="saving" :disabled="!reason.trim()" @click="submit" /></template>
    </FormDialogShell>
</template>
