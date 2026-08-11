<script setup lang="ts">
import { computed } from 'vue';
import { errorMessage, requestIdOf } from '@/api/errors';

type PageStateKind = 'loading' | 'error' | 'empty' | 'ready';

const props = defineProps<{
    state: PageStateKind;
    title?: string;
    description?: string;
    error?: unknown;
}>();

const displayTitle = computed(() => {
    if (props.state === 'error' && props.error != null) return errorMessage(props.error);
    return props.title;
});

const requestId = computed(() => requestIdOf(props.error));
</script>

<template>
    <div v-if="state === 'loading'" class="flex flex-col gap-4">
        <Skeleton v-for="n in 3" :key="n" class="h-16 w-full" />
    </div>
    <div v-else-if="state === 'error'" class="flex flex-col items-center gap-3 py-10">
        <i class="pi pi-exclamation-triangle text-3xl text-red-500"></i>
        <Message severity="error" :closable="false" class="w-full">{{ displayTitle }}</Message>
        <span v-if="requestId" class="text-xs text-muted-color">Request ID: {{ requestId }}</span>
        <span v-if="description" class="text-muted-color text-sm">{{ description }}</span>
    </div>
    <div v-else-if="state === 'empty'" class="flex flex-col items-center gap-3 py-10">
        <i class="pi pi-inbox text-3xl text-muted-color"></i>
        <span class="font-medium text-surface-900 dark:text-surface-0">{{ title }}</span>
        <span v-if="description" class="text-muted-color text-sm">{{ description }}</span>
    </div>
    <slot v-else />
</template>
