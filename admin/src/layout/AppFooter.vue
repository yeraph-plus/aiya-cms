<script setup lang="ts">
import { APP_NAME } from '@/env';
</script>

<template>
    <div class="layout-footer">
        {{ APP_NAME }} by
        <a href="https://primevue.org" target="_blank" rel="noopener noreferrer" class="text-primary font-bold hover:underline">PrimeVue</a>
    </div>
</template>
