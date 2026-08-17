<script setup lang="ts">
withDefaults(
    defineProps<{
        title?: string;
        description?: string;
        compact?: boolean;
    }>(),
    {
        title: '',
        description: '',
        compact: false
    }
);
</script>

<template>
    <section class="card" :class="{ '!p-4': compact }">
        <header v-if="title || description || $slots.actions" class="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
                <h2 v-if="title" class="m-0 text-lg font-semibold">{{ title }}</h2>
                <p v-if="description" class="text-muted-color mb-0 mt-1 text-sm">
                    {{ description }}
                </p>
            </div>
            <div v-if="$slots.actions" class="flex flex-wrap gap-2">
                <slot name="actions" />
            </div>
        </header>
        <slot />
        <footer v-if="$slots.footer" class="mt-4 border-t border-surface-200 pt-4 dark:border-surface-700">
            <slot name="footer" />
        </footer>
    </section>
</template>
