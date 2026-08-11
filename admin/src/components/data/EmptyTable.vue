<script setup lang="ts">
import { useI18n } from 'vue-i18n';

const { t } = useI18n();
</script>

<template>
    <div class="flex flex-col items-center gap-2 py-10">
        <i class="pi pi-inbox text-3xl text-muted-color"></i>
        <span class="text-muted-color font-medium">
            <slot>{{ t('common.emptyRecords') }}</slot>
        </span>
    </div>
</template>
