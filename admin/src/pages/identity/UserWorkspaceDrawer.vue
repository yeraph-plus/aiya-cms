<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { SubjectDTO } from '@/api/identity';
import { hasCapability } from '@/auth/session';
import EntityDrawerShell from '@/components/shell/EntityDrawerShell.vue';
import PointsAdjustDrawer from './PointsAdjustDrawer.vue';
import UserDetailDrawer from './UserDetailDrawer.vue';
import UserMembershipPanel from './UserMembershipPanel.vue';
import UserRolesPanel from './UserRolesPanel.vue';

type WorkspaceTab = 'account' | 'roles' | 'points' | 'membership';

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
const canManageRoles = computed(() => hasCapability('access.roles.read') && hasCapability('access.roles.assign'));
const canReadMembership = computed(() => hasCapability('membership.read'));

watch(
    () => [props.userId, props.initialTab] as const,
    () => {
        const allowed = props.initialTab === 'roles' ? canManageRoles.value : props.initialTab === 'points' ? canAdjustPoints.value : props.initialTab === 'membership' ? canReadMembership.value : true;
        activeTab.value = allowed ? props.initialTab : 'account';
    }
);
</script>

<template>
    <EntityDrawerShell v-model="visible" :title="t('users.workspaceTitle')" :description="userId || ''">
        <div class="mb-5 flex gap-2 border-b border-surface-200 pb-3 dark:border-surface-700" role="tablist">
            <Button :label="t('users.account')" :severity="activeTab === 'account' ? 'primary' : 'secondary'" :text="activeTab !== 'account'" role="tab" :aria-selected="activeTab === 'account'" @click="activeTab = 'account'" />
            <Button v-if="canManageRoles" :label="t('users.roles')" :severity="activeTab === 'roles' ? 'primary' : 'secondary'" :text="activeTab !== 'roles'" role="tab" :aria-selected="activeTab === 'roles'" @click="activeTab = 'roles'" />
            <Button v-if="canAdjustPoints" :label="t('nav.users.points')" :severity="activeTab === 'points' ? 'primary' : 'secondary'" :text="activeTab !== 'points'" role="tab" :aria-selected="activeTab === 'points'" @click="activeTab = 'points'" />
            <Button
                v-if="canReadMembership"
                :label="t('nav.users.membership')"
                :severity="activeTab === 'membership' ? 'primary' : 'secondary'"
                :text="activeTab !== 'membership'"
                role="tab"
                :aria-selected="activeTab === 'membership'"
                @click="activeTab = 'membership'"
            />
        </div>
        <UserDetailDrawer v-if="userId && activeTab === 'account'" :user-id="userId" @updated="emit('updated', $event)" @deleted="emit('deleted', $event)" />
        <UserRolesPanel v-else-if="userId && activeTab === 'roles'" :subject-id="userId" />
        <PointsAdjustDrawer v-else-if="userId && activeTab === 'points'" :subject-id="userId" />
        <UserMembershipPanel v-else-if="userId && activeTab === 'membership'" :subject-id="userId" />
    </EntityDrawerShell>
</template>
