<script setup lang="ts">
import { useI18n } from 'vue-i18n';

withDefaults(
    defineProps<{
        title: string;
        description?: string;
        loading?: boolean;
        refreshable?: boolean;
    }>(),
    {
        description: '',
        loading: false,
        refreshable: true
    }
);

defineEmits<{
    refresh: [];
}>();

const { t } = useI18n();
</script>

<template>
    <div class="flex flex-col gap-4">
        <Toolbar class="page-shell__toolbar py-3">
            <template #start>
                <div class="flex flex-col gap-1">
                    <h1 class="text-surface-900 dark:text-surface-0 m-0 text-xl font-semibold">{{ title }}</h1>
                    <p v-if="description" class="text-muted-color m-0 text-sm">{{ description }}</p>
                </div>
            </template>
            <template #end>
                <div class="flex flex-wrap items-center justify-end gap-2">
                    <slot name="actions" />
                    <Button v-if="refreshable" data-test="refresh" icon="pi pi-refresh" :label="t('common.refresh')" severity="secondary" :loading="loading" @click="$emit('refresh')" />
                    <slot name="more-actions" />
                </div>
            </template>
        </Toolbar>
        <slot />
    </div>
</template>
