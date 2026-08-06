<route lang="yaml">
meta:
  layout: ErrorLayout
  title: serviceUnavailable
  authRequired: false
</route>

<script setup lang="ts">
const { t } = useI18n()
</script>

<template>
  <div class="flex h-100vh items-center justify-center">
    <div class="error-message z-10 text-center">
      <div class="text-8xl font-bold text-rose-500">503</div>
      <p class="mt-8 text-lg dark:text-white">{{ t('common.503Message') }}</p>
      <BackHomeButton />
    </div>
  </div>
</template>
