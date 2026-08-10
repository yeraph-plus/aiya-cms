<script setup lang="ts">
withDefaults(
    defineProps<{
        title: string;
        subtitle?: string;
    }>(),
    {
        subtitle: ''
    }
);
</script>

<template>
    <div class="flex flex-col gap-4">
        <Toolbar class="py-3">
            <template #start>
                <div class="flex flex-col gap-1">
                    <span class="text-xl font-semibold text-surface-900 dark:text-surface-0">{{ title }}</span>
                    <span v-if="subtitle" class="text-sm text-muted-color">{{ subtitle }}</span>
                </div>
            </template>
            <template #end>
                <slot name="actions" />
            </template>
        </Toolbar>
        <slot />
    </div>
</template>
