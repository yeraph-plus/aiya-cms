<script setup lang="ts">
import { onMounted } from 'vue';
import { useI18n } from 'vue-i18n';
import { fetchSettingGroups, type SettingGroupDTO } from '@/api/settings';
import PageState from '@/components/feedback/PageState.vue';
import PageShell from '@/components/shell/PageShell.vue';
import { useAsyncState } from '@/composables/useAsyncState';
import SettingGroupCard from './SettingGroupCard.vue';

const { t } = useI18n();
const { data, loading, error, run } = useAsyncState<SettingGroupDTO[]>();

onMounted(() => {
    void refresh();
});

function refresh(): void {
    void run(() => fetchSettingGroups());
}

function replaceGroup(updated: SettingGroupDTO): void {
    if (!data.value) return;
    data.value = data.value.map((group) => (group.group_key === updated.group_key ? updated : group));
}
</script>

<template>
    <PageShell :title="t('routes.settings')" :description="t('workbenches.settings.description')" :loading="loading" @refresh="refresh">
        <PageState v-if="loading && !data" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" :description="t('workbenches.settings.loadFailed')" />
        <PageState v-else-if="data && data.length === 0" state="empty" :title="t('workbenches.settings.empty')" :description="t('workbenches.settings.emptyDescription')" />
        <div v-else class="flex flex-col gap-6">
            <SettingGroupCard v-for="group in data" :key="group.group_key" :group="group" @updated="replaceGroup" />
        </div>
    </PageShell>
</template>
