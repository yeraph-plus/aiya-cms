<script setup lang="ts">
import { onMounted } from 'vue';
import { fetchSettingGroups, type SettingGroupDTO } from '@/api/settings';
import PageState from '@/components/feedback/PageState.vue';
import PageToolbar from '@/components/data/PageToolbar.vue';
import { useAsyncState } from '@/composables/useAsyncState';
import SettingGroupCard from './SettingGroupCard.vue';

const { data, loading, error, run } = useAsyncState<SettingGroupDTO[]>();

onMounted(() => {
    void run(() => fetchSettingGroups());
});

function replaceGroup(updated: SettingGroupDTO): void {
    if (!data.value) return;
    data.value = data.value.map((group) => (group.group_key === updated.group_key ? updated : group));
}
</script>

<template>
    <PageToolbar title="Settings" subtitle="由后端注册的设置组和字段元数据驱动。">
        <PageState v-if="loading && !data" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" description="设置组加载失败，请稍后重试。" />
        <PageState v-else-if="data && data.length === 0" state="empty" title="暂无设置组" description="当前 manifest 没有提供可管理的设置组。" />
        <div v-else class="flex flex-col gap-6">
            <SettingGroupCard v-for="group in data" :key="group.group_key" :group="group" @updated="replaceGroup" />
        </div>
    </PageToolbar>
</template>
