<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { assignRole, fetchRoles, fetchSubjectRoles, type RoleDTO } from '@/api/access';
import { useI18n } from 'vue-i18n';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';

const props = defineProps<{ subjectId: string }>();
const { t } = useI18n();
const roles = ref<RoleDTO[]>([]);
const loading = ref(false);
const error = ref<unknown>(null);
const assigned = ref<string[]>([]);

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        const [available, grants] = await Promise.all([fetchRoles(), fetchSubjectRoles('identity', props.subjectId)]);
        roles.value = available;
        assigned.value = grants.roles ?? [];
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

async function assign(role: RoleDTO): Promise<void> {
    if (assigned.value.includes(role.id)) return;
    try {
        const summary = await assignRole(role.id, {
            subject_type: 'identity',
            subject_id: props.subjectId
        });
        assigned.value = summary.roles ?? [];
    } catch (caught) {
        error.value = caught;
    }
}

onMounted(() => void load());
</script>

<template>
    <div class="flex flex-col gap-3">
        <ApiErrorMessage v-if="error" :error="error" />
        <div v-if="loading" class="text-muted-color text-sm">
            {{ t('common.loading') }}
        </div>
        <div v-for="role in roles" :key="role.id" class="flex items-center justify-between rounded-border border border-surface p-3">
            <div>
                <strong>{{ role.name }}</strong>
                <p class="text-muted-color mb-0 mt-1 text-sm">
                    {{ role.description || role.slug }}
                </p>
            </div>
            <Button v-if="!assigned.includes(role.id)" size="small" :label="t('users.assignRole')" @click="assign(role)" />
            <Tag v-else severity="success" :value="t('users.assigned')" />
        </div>
    </div>
</template>
