<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';
import { fetchUsers, type SubjectDTO, type SubjectPageDTO, type UserListQuery } from '@/api/identity';
import PageState from '@/components/feedback/PageState.vue';
import PageShell from '@/components/shell/PageShell.vue';
import PagedTable from '@/components/data/PagedTable.vue';
import FilterBar from '@/components/data/FilterBar.vue';
import ListPanel from '@/components/data/ListPanel.vue';
import UserWorkspaceDrawer from './UserWorkspaceDrawer.vue';
import { hasCapability } from '@/auth/session';

const { t, locale } = useI18n();
const statusOptions = ['active', 'banned', 'deleted'];
const route = useRoute();
const router = useRouter();
const filters = reactive({ status: null as string | null });
const result = ref<SubjectPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const size = ref(20);
const selectedUserId = ref<string | null>(null);
const workspaceVisible = computed({
    get: () => selectedUserId.value !== null,
    set: (visible: boolean) => {
        if (!visible) selectedUserId.value = null;
    }
});
const workspaceTab = ref<'account' | 'roles' | 'points'>('account');
const canAdjustPoints = computed(() => hasCapability('points.adjust'));

function routeString(key: string): string | undefined {
    const value = route.query[key];
    return typeof value === 'string' ? value : undefined;
}

function restoreFromRoute(): void {
    filters.status = routeString('status') ?? null;
    const routePage = Number.parseInt(routeString('page') ?? '', 10);
    const routeSize = Number.parseInt(routeString('size') ?? '', 10);
    if (Number.isFinite(routePage) && routePage > 0) page.value = routePage;
    if (Number.isFinite(routeSize) && routeSize > 0 && routeSize <= 100) size.value = routeSize;
}

async function syncRoute(): Promise<void> {
    const query: LocationQueryRaw = {
        page: String(page.value),
        size: String(size.value)
    };
    if (filters.status) query.status = filters.status;
    await router.replace({ query });
}

function query(): UserListQuery {
    return {
        page: page.value,
        size: size.value,
        status: filters.status || undefined
    };
}

async function load(syncUrl = false): Promise<void> {
    if (syncUrl) await syncRoute();
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchUsers(query());
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function applyFilters(): void {
    page.value = 1;
    void load(true);
}

function refresh(): void {
    void load();
}

function onPage(value: number): void {
    page.value = value;
    void load(true);
}

function onSize(value: number): void {
    size.value = value;
    page.value = 1;
    void load(true);
}

function formatDate(value: string | null | undefined): string {
    return value
        ? new Intl.DateTimeFormat(locale.value, {
              dateStyle: 'medium',
              timeStyle: 'short'
          }).format(new Date(value))
        : '-';
}

function openUser(userId: string): void {
    workspaceTab.value = 'account';
    selectedUserId.value = userId;
}

function openPoints(userId: string): void {
    workspaceTab.value = 'points';
    selectedUserId.value = userId;
}

function openRoles(userId: string): void {
    workspaceTab.value = 'roles';
    selectedUserId.value = userId;
}

function updateUser(updated: SubjectDTO): void {
    if (!result.value) return;
    result.value = {
        ...result.value,
        items: result.value.items.map((item) => (item.id === updated.id ? updated : item))
    };
}

function removeUser(userId: string): void {
    selectedUserId.value = null;
    void load();
    if (!result.value || result.value.items.every((item) => item.id !== userId)) return;
    result.value = {
        ...result.value,
        items: result.value.items.filter((item) => item.id !== userId),
        total: Math.max(0, result.value.total - 1)
    };
}

onMounted(() => {
    restoreFromRoute();
    void load();
});
</script>

<template>
    <PageShell :title="t('routes.users.list')" :description="t('users.description')" :loading="loading" @refresh="refresh">
        <ListPanel>
            <FilterBar :label="t('common.applyFilters')" @submit="applyFilters">
                <div class="flex min-w-56 flex-col gap-2">
                    <label for="user-status" class="font-medium">{{ t('workbenches.status') }}</label>
                    <Select id="user-status" v-model="filters.status" :options="statusOptions" show-clear :placeholder="t('common.all')" fluid />
                </div>
                <template #actions />
            </FilterBar>
        </ListPanel>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="result && result.total === 0" state="empty" :title="t('users.empty')" :description="t('users.emptyDescription')" />
        <PagedTable v-else-if="result" :value="result.items" :loading="loading" :total-records="result.total" :page="result.page" :size="result.size" @update:page="onPage" @update:size="onSize">
            <Column field="username" :header="t('users.username')" style="min-width: 12rem" />
            <Column field="display_name" :header="t('users.displayName')" style="min-width: 12rem">
                <template #body="{ data }">{{ data.display_name || '-' }}</template>
            </Column>
            <Column field="email" :header="t('users.email')" style="min-width: 16rem" />
            <Column field="status" :header="t('workbenches.status')" style="min-width: 8rem">
                <template #body="{ data }"><StatusTag :value="data.status" /></template>
            </Column>
            <Column field="email_verified" :header="t('users.emailVerified')" style="min-width: 10rem">
                <template #body="{ data }"><i class="pi" :class="data.email_verified ? 'pi-check-circle text-green-500' : 'pi-times-circle text-red-500'" /></template>
            </Column>
            <Column field="created_at" :header="t('users.created')" style="min-width: 12rem">
                <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
            </Column>
            <Column :header="t('common.actions')" style="width: 8rem">
                <template #body="{ data }">
                    <div class="flex flex-wrap gap-1">
                        <Button :label="t('users.view')" text @click="openUser(data.id)" />
                        <Button v-if="hasCapability('access.roles.assign')" :label="t('users.manageRoles')" text icon="pi pi-shield" @click="openRoles(data.id)" />
                        <Button v-if="canAdjustPoints" :label="t('users.managePoints')" text icon="pi pi-star" @click="openPoints(data.id)" />
                    </div>
                </template>
            </Column>
        </PagedTable>

        <UserWorkspaceDrawer v-model="workspaceVisible" :user-id="selectedUserId" :initial-tab="workspaceTab" @updated="updateUser" @deleted="removeUser" />
    </PageShell>
</template>
