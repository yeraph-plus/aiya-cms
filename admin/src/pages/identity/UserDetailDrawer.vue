<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { banUser, deleteUser, fetchUser, unbanUser, type SubjectDTO } from '@/api/identity';
import { hasCapability } from '@/auth/session';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import ConfirmAction from '@/components/feedback/ConfirmAction.vue';
import PageState from '@/components/feedback/PageState.vue';

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
    return value ? new Date(value).toLocaleString() : '-';
}

watch(
    () => props.userId,
    () => void load(),
    { immediate: true }
);
</script>

<template>
    <PageState v-if="loading && !user" state="loading" />
    <PageState v-else-if="error" state="error" :error="error" description="用户详情加载失败，请稍后重试。" />
    <template v-else-if="user">
        <div class="flex flex-col gap-6">
            <Card>
                <template #title>{{ user.username }}</template>
                <template #subtitle>{{ user.id }}</template>
                <template #content>
                    <div class="grid grid-cols-12 gap-6">
                        <div class="col-span-12 flex flex-col gap-2">
                            <span class="text-sm text-muted-color">Display name</span>
                            <span>{{ user.display_name || '-' }}</span>
                        </div>
                        <div class="col-span-12 flex flex-col gap-2">
                            <span class="text-sm text-muted-color">Email</span>
                            <span class="break-all">{{ user.email }}</span>
                        </div>
                        <div class="col-span-12 flex flex-col gap-2">
                            <span class="text-sm text-muted-color">Status</span>
                            <Tag :value="user.status" :severity="statusSeverity(user.status)" class="w-fit" />
                        </div>
                        <div class="col-span-12 flex flex-col gap-2">
                            <span class="text-sm text-muted-color">Email verified</span>
                            <span>{{ user.email_verified ? '是' : '否' }}</span>
                        </div>
                        <div class="col-span-12 flex flex-col gap-2">
                            <span class="text-sm text-muted-color">Created</span>
                            <span>{{ formatDate(user.created_at) }}</span>
                        </div>
                    </div>
                </template>
            </Card>

            <Card>
                <template #title>Account actions</template>
                <template #content>
                    <div class="flex flex-col gap-4">
                        <div v-if="user.status === 'active'" class="flex flex-col gap-2">
                            <label :for="`ban-reason-${user.id}`" class="font-medium">Ban reason</label>
                            <Textarea :id="`ban-reason-${user.id}`" v-model="banReason" rows="3" auto-resize placeholder="说明封禁原因（可选）" :disabled="processing || !canBan" />
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <ConfirmAction v-if="user.status === 'active'" label="封禁用户" message="确定封禁该用户吗？封禁后将拒绝新的认证。" :disabled="processing || !canBan" @confirmed="ban" />
                            <ConfirmAction v-if="user.status === 'banned'" label="解除封禁" message="确定解除该用户的封禁吗？" severity="warn" :disabled="processing || !canUnban" @confirmed="unban" />
                            <ConfirmAction label="删除用户" message="确定删除该用户吗？该操作不可逆。" :disabled="processing || !canDelete || user.status === 'deleted'" @confirmed="remove" />
                        </div>
                        <Message v-if="!canBan && !canUnban && !canDelete" severity="info" :closable="false">当前账号没有用户管理写权限。</Message>
                    </div>
                </template>
            </Card>

            <ApiErrorMessage v-if="actionError" :error="actionError" />
        </div>
    </template>
</template>
