<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { banUser, deleteUser, fetchUser, unbanUser, type SubjectDTO } from '@/api/identity';
import { hasCapability } from '@/auth/session';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import ConfirmAction from '@/components/feedback/ConfirmAction.vue';
import PageState from '@/components/feedback/PageState.vue';

const { t, locale } = useI18n();
const props = defineProps<{ userId: string }>();

const emit = defineEmits<{
    updated: [user: SubjectDTO];
    deleted: [userId: string];
}>();

const user = ref<SubjectDTO | null>(null);
const loading = ref(false);
const processing = ref(false);
const error = ref<unknown>(null);
const actionError = ref<unknown>(null);
const banReason = ref('');
const canBan = computed(() => hasCapability('identity.users.ban'));
const canUnban = computed(() => hasCapability('identity.users.unban'));
const canDelete = computed(() => hasCapability('identity.users.delete'));

function setUser(next: SubjectDTO, notify = false): void {
    user.value = next;
    actionError.value = null;
    if (notify) emit('updated', next);
}

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        setUser(await fetchUser(props.userId));
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

async function ban(): Promise<void> {
    if (!canBan.value || !user.value) return;
    processing.value = true;
    actionError.value = null;
    try {
        setUser(await banUser(user.value.id, { reason: banReason.value.trim() || null }), true);
        banReason.value = '';
    } catch (caught) {
        actionError.value = caught;
    } finally {
        processing.value = false;
    }
}

async function unban(): Promise<void> {
    if (!canUnban.value || !user.value) return;
    processing.value = true;
    actionError.value = null;
    try {
        setUser(await unbanUser(user.value.id), true);
    } catch (caught) {
        actionError.value = caught;
    } finally {
        processing.value = false;
    }
}

async function remove(): Promise<void> {
    if (!canDelete.value || !user.value) return;
    processing.value = true;
    actionError.value = null;
    try {
        await deleteUser(user.value.id);
        emit('deleted', user.value.id);
    } catch (caught) {
        actionError.value = caught;
        processing.value = false;
    }
}

function statusSeverity(status: string): 'success' | 'warn' | 'danger' | 'secondary' {
    if (status === 'active') return 'success';
    if (status === 'banned') return 'warn';
    if (status === 'deleted') return 'danger';
    return 'secondary';
}

function formatDate(value: string | null | undefined): string {
    return value ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-';
}

watch(
    () => props.userId,
    () => void load(),
    { immediate: true }
);
</script>

<template>
    <PageState v-if="loading && !user" state="loading" />
    <PageState v-else-if="error" state="error" :error="error" />
    <template v-else-if="user">
        <div class="flex flex-col gap-6">
            <Card>
                <template #title>{{ user.username }}</template>
                <template #subtitle>{{ user.id }}</template>
                <template #content>
                    <div class="grid grid-cols-12 gap-6">
                        <div class="col-span-12 flex flex-col gap-2">
                            <span class="text-sm text-muted-color">{{ t('users.displayName') }}</span>
                            <span>{{ user.display_name || '-' }}</span>
                        </div>
                        <div class="col-span-12 flex flex-col gap-2">
                            <span class="text-sm text-muted-color">{{ t('users.email') }}</span>
                            <span class="break-all">{{ user.email }}</span>
                        </div>
                        <div class="col-span-12 flex flex-col gap-2">
                            <span class="text-sm text-muted-color">{{ t('workbenches.status') }}</span>
                            <Tag :value="user.status" :severity="statusSeverity(user.status)" class="w-fit" />
                        </div>
                        <div class="col-span-12 flex flex-col gap-2">
                            <span class="text-sm text-muted-color">{{ t('users.emailVerified') }}</span>
                            <span>{{ user.email_verified ? t('common.yes') : t('common.no') }}</span>
                        </div>
                        <div class="col-span-12 flex flex-col gap-2">
                            <span class="text-sm text-muted-color">{{ t('users.created') }}</span>
                            <span>{{ formatDate(user.created_at) }}</span>
                        </div>
                    </div>
                </template>
            </Card>

            <Card>
                <template #title>{{ t('users.accountActions') }}</template>
                <template #content>
                    <div class="flex flex-col gap-4">
                        <div v-if="user.status === 'active'" class="flex flex-col gap-2">
                            <label :for="`ban-reason-${user.id}`" class="font-medium">{{ t('users.banReason') }}</label>
                            <Textarea :id="`ban-reason-${user.id}`" v-model="banReason" rows="3" auto-resize :placeholder="t('users.banReasonPlaceholder')" :disabled="processing || !canBan" />
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <ConfirmAction v-if="user.status === 'active'" :label="t('users.ban')" :message="t('users.banConfirm')" :disabled="processing || !canBan" @confirmed="ban" />
                            <ConfirmAction v-if="user.status === 'banned'" :label="t('users.unban')" :message="t('users.unbanConfirm')" severity="warn" :disabled="processing || !canUnban" @confirmed="unban" />
                            <ConfirmAction :label="t('users.delete')" :message="t('users.deleteConfirm')" :disabled="processing || !canDelete || user.status === 'deleted'" @confirmed="remove" />
                        </div>
                        <Message v-if="!canBan && !canUnban && !canDelete" severity="info" :closable="false">{{ t('users.readOnly') }}</Message>
                    </div>
                </template>
            </Card>

            <ApiErrorMessage v-if="actionError" :error="actionError" />
        </div>
    </template>
</template>
