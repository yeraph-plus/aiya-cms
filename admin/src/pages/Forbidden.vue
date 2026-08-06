<route lang="yaml">
meta:
  layout: ErrorLayout
  title: forbidden
  authRequired: false
</route>

<script setup lang="ts">
const { t } = useI18n()
</script>

<template>
  <div class="flex h-100vh items-center justify-center">
    <div class="error-message z-10 text-center">
      <div class="text-8xl font-bold text-amber-500">403</div>
      <p class="mt-8 text-lg dark:text-white">{{ t('common.403Message') }}</p>
      <BackHomeButton />
    </div>
  </div>
</template>
