<script setup lang="ts">
import { onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import FloatingConfigurator from '@/components/FloatingConfigurator.vue';
import { APP_NAME } from '@/env';
import { completeAuthentication } from '@/auth/session';
import { isSafeRedirectPath, takePendingRedirect } from '@/auth/storage';

const route = useRoute();
const router = useRouter();

function resolveRedirect(target: string | null): string {
    if (isSafeRedirectPath(target)) {
        return target;
    }
    return takePendingRedirect() ?? '/content';
}

onMounted(async () => {
    try {
        await completeAuthentication();
        await router.replace(resolveRedirect(route.query.redirect as string | null));
    } catch {
        await router.replace({ name: 'error', query: { message: 'Sign-in could not be completed. Please try again.' } });
    }
});
</script>

<template>
    <FloatingConfigurator />
    <div class="bg-surface-50 dark:bg-surface-950 flex items-center justify-center min-h-screen min-w-[100vw] overflow-hidden">
        <div class="flex flex-col items-center justify-center">
            <div class="w-full bg-surface-0 dark:bg-surface-900 py-20 px-8 sm:px-20 flex flex-col items-center" style="border-radius: 53px">
                <ProgressSpinner class="mb-6" />
                <h1 class="text-surface-900 dark:text-surface-0 font-bold text-3xl mb-2">Completing Sign In</h1>
                <span class="text-muted-color">Finishing the sign-in for {{ APP_NAME }}. You will be redirected automatically.</span>
            </div>
        </div>
    </div>
</template>
