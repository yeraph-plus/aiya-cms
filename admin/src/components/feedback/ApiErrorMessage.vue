<script setup lang="ts">
import { computed } from 'vue';
import { errorMessage, requestIdOf } from '@/api/errors';

const props = defineProps<{
    error: unknown;
}>();

const message = computed(() => errorMessage(props.error));
const requestId = computed(() => requestIdOf(props.error));
</script>

<template>
    <div class="flex flex-col gap-1">
        <Message severity="error" :closable="false">{{ message }}</Message>
        <span v-if="requestId" class="text-xs text-muted-color">Request ID: {{ requestId }}</span>
    </div>
</template>
