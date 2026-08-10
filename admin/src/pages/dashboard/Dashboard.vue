<script setup lang="ts">
import { sessionState } from '@/auth/session';
</script>

<template>
    <div class="card">
        <div class="font-semibold text-2xl mb-2">Dashboard</div>
        <div class="text-muted-color mb-6">Welcome{{ sessionState.me?.display_name ? `, ${sessionState.me.display_name}` : '' }}. The overview will be driven by the backend AdminSummaryProvider aggregate once connected.</div>
        <div class="grid grid-cols-12 gap-8">
            <div class="col-span-12 lg:col-span-6 xl:col-span-3">
                <div class="card mb-0">
                    <span class="block text-muted-color font-medium mb-4">Status</span>
                    <div class="text-surface-900 dark:text-surface-0 font-medium text-xl">Shell ready</div>
                </div>
            </div>
        </div>
    </div>
</template>
