<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { SubjectDTO } from '@/api/identity';
import { hasCapability } from '@/auth/session';
import EntityDrawerShell from '@/components/shell/EntityDrawerShell.vue';
import PointsAdjustDrawer from './PointsAdjustDrawer.vue';
import UserDetailDrawer from './UserDetailDrawer.vue';
import UserMembershipPanel from './UserMembershipPanel.vue';
import UserPaymentsPanel from './UserPaymentsPanel.vue';

type WorkspaceTab = 'account' | 'points' | 'membership' | 'payments';

const props = withDefaults(
    defineProps<{
        userId: string | null;
        initialTab?: WorkspaceTab;
    }>(),
    { initialTab: 'account' }
);

const visible = defineModel<boolean>({ required: true });
const emit = defineEmits<{
    updated: [user: SubjectDTO];
    deleted: [userId: string];
}>();
const { t } = useI18n();
const activeTab = ref<WorkspaceTab>(props.initialTab);
const canAdjustPoints = computed(() => hasCapability('points.adjust') || hasCapability('points.read'));
const canReadMembership = computed(() => hasCapability('membership.read'));
const canReadPayments = computed(() => hasCapability('payments.read'));

watch(
    () => [props.userId, props.initialTab] as const,
    () => {
        const allowed = props.initialTab === 'points' ? canAdjustPoints.value : props.initialTab === 'membership' ? canReadMembership.value : props.initialTab === 'payments' ? canReadPayments.value : true;
        activeTab.value = allowed ? props.initialTab : 'account';
    }
);
</script>

<template>
    <EntityDrawerShell v-model="visible" :title="t('users.workspaceTitle')" :description="userId || ''">
        <div class="mb-5 flex gap-2 border-b border-surface-200 pb-3 dark:border-surface-700" role="tablist">
            <Button :label="t('users.account')" :severity="activeTab === 'account' ? 'primary' : 'secondary'" :text="activeTab !== 'account'" role="tab" :aria-selected="activeTab === 'account'" @click="activeTab = 'account'" />
            <Button v-if="canAdjustPoints" :label="t('nav.users.points')" :severity="activeTab === 'points' ? 'primary' : 'secondary'" :text="activeTab !== 'points'" role="tab" :aria-selected="activeTab === 'points'" @click="activeTab = 'points'" />
            <Button v-if="canReadMembership" :label="t('nav.users.membership')" :severity="activeTab === 'membership' ? 'primary' : 'secondary'" :text="activeTab !== 'membership'" role="tab" :aria-selected="activeTab === 'membership'" @click="activeTab = 'membership'" />
            <Button v-if="canReadPayments" :label="t('nav.users.payments')" :severity="activeTab === 'payments' ? 'primary' : 'secondary'" :text="activeTab !== 'payments'" role="tab" :aria-selected="activeTab === 'payments'" @click="activeTab = 'payments'" />
        </div>
        <UserDetailDrawer v-if="userId && activeTab === 'account'" :user-id="userId" @updated="emit('updated', $event)" @deleted="emit('deleted', $event)" />
        <PointsAdjustDrawer v-else-if="userId && activeTab === 'points'" :subject-id="userId" />
        <UserMembershipPanel v-else-if="userId && activeTab === 'membership'" :subject-id="userId" />
        <UserPaymentsPanel v-else-if="userId && activeTab === 'payments'" :subject-id="userId" />
    </EntityDrawerShell>
</template>
