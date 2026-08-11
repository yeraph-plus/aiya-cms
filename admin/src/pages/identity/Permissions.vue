<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { assignRole, createRole, deleteRole, fetchCapabilities, fetchRoles, replaceRoleCapabilities, type RoleDTO } from '@/api/access';
import { hasCapability } from '@/auth/session';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import ConfirmAction from '@/components/feedback/ConfirmAction.vue';
import PageState from '@/components/feedback/PageState.vue';
import FormDialogShell from '@/components/shell/FormDialogShell.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t } = useI18n();
const roles = ref<RoleDTO[] | null>(null);
const capabilityKeys = ref<string[]>([]);
const loading = ref(false);
const saving = ref(false);
const error = ref<unknown>(null);
const actionError = ref<unknown>(null);
const createVisible = ref(false);
const capabilitiesVisible = ref(false);
const assignVisible = ref(false);
const selectedRole = ref<RoleDTO | null>(null);
const selectedCapabilities = ref<string[]>([]);
const subjectId = ref('');
const createForm = reactive({ name: '', slug: '', description: '' });
const canManage = computed(() => hasCapability('access.roles.manage'));
const canAssign = computed(() => hasCapability('access.roles.assign'));

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        const [nextRoles, capabilities] = await Promise.all([fetchRoles(), fetchCapabilities()]);
        roles.value = nextRoles;
        capabilityKeys.value = capabilities.keys ?? [];
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function openCapabilities(role: RoleDTO): void {
    selectedRole.value = role;
    selectedCapabilities.value = [...(role.capability_keys ?? [])];
    actionError.value = null;
    capabilitiesVisible.value = true;
}

function openAssign(role: RoleDTO): void {
    selectedRole.value = role;
    subjectId.value = '';
    actionError.value = null;
    assignVisible.value = true;
}

async function submitCreate(): Promise<void> {
    saving.value = true;
    actionError.value = null;
    try {
        const created = await createRole({ name: createForm.name.trim(), slug: createForm.slug.trim(), description: createForm.description.trim() || null });
        roles.value = [...(roles.value ?? []), created];
        Object.assign(createForm, { name: '', slug: '', description: '' });
        createVisible.value = false;
    } catch (caught) {
        actionError.value = caught;
    } finally {
        saving.value = false;
    }
}

async function saveCapabilities(): Promise<void> {
    if (!selectedRole.value) return;
    saving.value = true;
    actionError.value = null;
    try {
        const updated = await replaceRoleCapabilities(selectedRole.value.id, { capability_keys: selectedCapabilities.value });
        roles.value = (roles.value ?? []).map((role) => (role.id === updated.id ? updated : role));
        capabilitiesVisible.value = false;
    } catch (caught) {
        actionError.value = caught;
    } finally {
        saving.value = false;
    }
}

async function submitAssign(): Promise<void> {
    if (!selectedRole.value || !subjectId.value.trim()) return;
    saving.value = true;
    actionError.value = null;
    try {
        await assignRole(selectedRole.value.id, { subject_type: 'identity', subject_id: subjectId.value.trim() });
        assignVisible.value = false;
    } catch (caught) {
        actionError.value = caught;
    } finally {
        saving.value = false;
    }
}

async function removeRole(role: RoleDTO): Promise<void> {
    actionError.value = null;
    try {
        await deleteRole(role.id);
        roles.value = (roles.value ?? []).filter((item) => item.id !== role.id);
    } catch (caught) {
        actionError.value = caught;
    }
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.users.permissions')" :description="t('workbenches.permissions.description')" :loading="loading" @refresh="load">
        <template #actions>
            <Button v-if="canManage" icon="pi pi-plus" :label="t('workbenches.permissions.createRole')" @click="createVisible = true" />
        </template>
        <ApiErrorMessage v-if="actionError && !createVisible && !capabilitiesVisible && !assignVisible" :error="actionError" />
        <PageState v-if="loading && !roles" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="roles?.length === 0" state="empty" :title="t('workbenches.permissions.empty')" />
        <div v-else class="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <SurfaceCard v-for="role in roles" :key="role.id" :title="role.name" :description="role.description || role.slug">
                <template #actions><Tag v-if="role.system" value="system" severity="info" /></template>
                <div class="mb-4 flex flex-wrap gap-2">
                    <Tag v-for="key in role.capability_keys ?? []" :key="key" :value="key" severity="secondary" />
                    <span v-if="!(role.capability_keys ?? []).length" class="text-muted-color text-sm">{{ t('workbenches.permissions.noCapabilities') }}</span>
                </div>
                <div class="flex flex-wrap gap-2">
                    <Button v-if="canManage" :label="t('workbenches.permissions.capabilities')" icon="pi pi-key" severity="secondary" @click="openCapabilities(role)" />
                    <Button v-if="canAssign" :label="t('workbenches.permissions.assign')" icon="pi pi-user-plus" severity="secondary" @click="openAssign(role)" />
                    <ConfirmAction v-if="canManage && !role.system" :label="t('workbenches.permissions.deleteRole')" :header="t('workbenches.permissions.deleteRole')" :message="t('workbenches.permissions.deleteConfirm', { name: role.name })" @confirmed="removeRole(role)" />
                </div>
            </SurfaceCard>
        </div>

        <FormDialogShell v-model="createVisible" :title="t('workbenches.permissions.createRole')">
            <form class="flex flex-col gap-4" @submit.prevent="submitCreate">
                <ApiErrorMessage v-if="actionError" :error="actionError" />
                <InputText v-model="createForm.name" :placeholder="t('workbenches.permissions.roleName')" required />
                <InputText v-model="createForm.slug" :placeholder="t('workbenches.permissions.roleSlug')" required />
                <Textarea v-model="createForm.description" :placeholder="t('workbenches.description')" rows="3" />
                <Button type="submit" :label="t('workbenches.save')" :loading="saving" />
            </form>
        </FormDialogShell>

        <FormDialogShell v-model="capabilitiesVisible" :title="t('workbenches.permissions.capabilities')" width-class="w-full max-w-3xl">
            <ApiErrorMessage v-if="actionError" :error="actionError" />
            <MultiSelect v-model="selectedCapabilities" :options="capabilityKeys" filter display="chip" class="w-full" />
            <template #footer><Button :label="t('workbenches.save')" :loading="saving" @click="saveCapabilities" /></template>
        </FormDialogShell>

        <FormDialogShell v-model="assignVisible" :title="t('workbenches.permissions.assign')">
            <ApiErrorMessage v-if="actionError" :error="actionError" />
            <InputText v-model="subjectId" :placeholder="t('workbenches.subjectId')" class="w-full" />
            <template #footer><Button :label="t('workbenches.permissions.assign')" :loading="saving" :disabled="!subjectId.trim()" @click="submitAssign" /></template>
        </FormDialogShell>
    </PageShell>
</template>
