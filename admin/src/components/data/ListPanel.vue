<script setup lang="ts">
withDefaults(defineProps<{ title?: string; description?: string }>(), {
    title: '',
    description: ''
});
</script>

<template>
    <section class="rounded-xl border border-surface-200/70 bg-surface-0/60 p-4 dark:border-surface-700/70 dark:bg-surface-900/40">
        <header v-if="title || description" class="mb-4">
            <h2 v-if="title" class="m-0 text-lg font-semibold">{{ title }}</h2>
            <p v-if="description" class="text-muted-color mb-0 mt-1 text-sm">
                {{ description }}
            </p>
        </header>
        <slot />
    </section>
</template>
