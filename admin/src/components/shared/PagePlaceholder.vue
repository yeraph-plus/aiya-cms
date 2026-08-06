<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <n-card :title="title" :bordered="false" class="rounded-lg">
    <n-result
      status="info"
      title="模块建设中"
      :description="description ?? '功能将在后续里程碑交付。'"
    />
  </n-card>
</template>
