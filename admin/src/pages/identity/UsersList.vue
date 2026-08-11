<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';
import { fetchUsers, type SubjectDTO, type SubjectPageDTO, type UserListQuery } from '@/api/identity';
import PageState from '@/components/feedback/PageState.vue';
import PageToolbar from '@/components/data/PageToolbar.vue';
import PagedTable from '@/components/data/PagedTable.vue';
import UserDetailDrawer from './UserDetailDrawer.vue';
import PointsAdjustDrawer from './PointsAdjustDrawer.vue';
import { hasCapability } from '@/auth/session';

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
const drawerVisible = computed({
    get: () => selectedUserId.value !== null,
    set: (visible: boolean) => {
        if (!visible) selectedUserId.value = null;
    }
});
const pointsUserId = ref<string | null>(null);
const pointsDrawerVisible = computed({
    get: () => pointsUserId.value !== null,
    set: (visible: boolean) => {
        if (!visible) pointsUserId.value = null;
    }
});
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
    const query: LocationQueryRaw = { page: String(page.value), size: String(size.value) };
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

function statusSeverity(status: string): 'success' | 'warn' | 'danger' | 'secondary' {
    if (status === 'active') return 'success';
    if (status === 'banned') return 'warn';
    if (status === 'deleted') return 'danger';
    return 'secondary';
}

function formatDate(value: string | null | undefined): string {
    return value ? new Date(value).toLocaleString() : '-';
}

function openUser(userId: string): void {
    selectedUserId.value = userId;
}

function openPoints(userId: string): void {
    pointsUserId.value = userId;
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
    <PageToolbar title="Users" subtitle="管理用户主体和账号状态。">
        <template #actions>
            <Button icon="pi pi-refresh" label="刷新" severity="secondary" :loading="loading" @click="refresh" />
        </template>

        <div class="card">
            <form class="flex flex-wrap items-end gap-4" @submit.prevent="applyFilters">
                <div class="flex min-w-56 flex-col gap-2">
                    <label for="user-status" class="font-medium">Status</label>
                    <Select id="user-status" v-model="filters.status" :options="statusOptions" show-clear placeholder="全部状态" fluid />
                </div>
                <Button type="submit" label="应用筛选" icon="pi pi-search" />
            </form>
        </div>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" description="用户列表加载失败，请稍后重试。" />
        <PageState v-else-if="result && result.total === 0" state="empty" title="暂无用户" description="当前筛选条件没有匹配的用户。" />
        <PagedTable v-else-if="result" :value="result.items" :loading="loading" :total-records="result.total" :page="result.page" :size="result.size" @update:page="onPage" @update:size="onSize">
            <Column field="username" header="Username" style="min-width: 12rem" />
            <Column field="display_name" header="Display name" style="min-width: 12rem">
                <template #body="{ data }">{{ data.display_name || '-' }}</template>
            </Column>
            <Column field="email" header="Email" style="min-width: 16rem" />
            <Column field="status" header="Status" style="min-width: 8rem">
                <template #body="{ data }"><Tag :value="data.status" :severity="statusSeverity(data.status)" /></template>
            </Column>
            <Column field="email_verified" header="Email verified" style="min-width: 10rem">
                <template #body="{ data }"><i class="pi" :class="data.email_verified ? 'pi-check-circle text-green-500' : 'pi-times-circle text-red-500'" /></template>
            </Column>
            <Column field="created_at" header="Created" style="min-width: 12rem">
                <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
            </Column>
            <Column header="Actions" style="width: 8rem">
                <template #body="{ data }">
                    <div class="flex flex-wrap gap-1">
                        <Button label="查看" text @click="openUser(data.id)" />
                        <Button v-if="canAdjustPoints" label="积分管理" text icon="pi pi-star" @click="openPoints(data.id)" />
                    </div>
                </template>
            </Column>
        </PagedTable>

        <Drawer v-model:visible="drawerVisible" header="User detail" position="right" class="!w-full md:!w-[42rem]">
            <UserDetailDrawer v-if="selectedUserId" :user-id="selectedUserId" @updated="updateUser" @deleted="removeUser" />
        </Drawer>
        <Drawer v-model:visible="pointsDrawerVisible" header="积分管理" position="right" class="!w-full md:!w-[42rem]">
            <PointsAdjustDrawer v-if="pointsUserId" :subject-id="pointsUserId" />
        </Drawer>
    </PageToolbar>
</template>
