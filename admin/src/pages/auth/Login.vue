<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import FloatingConfigurator from '@/components/FloatingConfigurator.vue';
import { APP_NAME } from '@/env';
import { createLoginFormArgs, submitLogin as submitOidcLogin, type LoginFormArgs } from '@/auth/oidc';

const route = useRoute();
const router = useRouter();
const username = ref('');
const password = ref('');
const loginForm = ref<LoginFormArgs | null>(null);
const error = ref('');
const submitting = ref(false);

const expired = route.query.reason === 'expired';

onMounted(async () => {
    try {
        loginForm.value = await createLoginFormArgs();
    } catch (caught) {
        const detail = caught instanceof Error ? caught.message : String(caught);
        error.value = `OIDC 配置不可用，无法发起登录：${detail}。请检查 AIYA_ISSUER，并确认 dev server 已重启。`;
    }
});

async function submitLogin() {
    if (!loginForm.value || !username.value || !password.value) return;
    submitting.value = true;
    try {
        const callbackUrl = await submitOidcLogin(loginForm.value, username.value, password.value);
        window.location.assign(callbackUrl);
    } catch (caught) {
        submitting.value = false;
        const detail = caught instanceof Error ? caught.message : 'OIDC 登录失败，请稍后重试';
        await router.replace({ name: 'error', query: { message: detail } });
    }
}
</script>

<template>
    <FloatingConfigurator />
    <div class="bg-surface-50 dark:bg-surface-950 flex items-center justify-center min-h-screen min-w-[100vw] overflow-hidden">
        <div class="flex flex-col items-center justify-center">
            <div style="border-radius: 56px; padding: 0.3rem; background: linear-gradient(180deg, var(--primary-color) 10%, rgba(33, 150, 243, 0) 30%)">
                <div class="w-full bg-surface-0 dark:bg-surface-900 py-20 px-8 sm:px-20" style="border-radius: 53px">
                    <div class="text-center mb-8">
                        <span class="aiya-cms-mark aiya-cms-mark--large mb-8 shrink-0 mx-auto" aria-hidden="true"></span>
                        <div class="text-surface-900 dark:text-surface-0 text-3xl font-medium mb-4">Welcome to {{ APP_NAME }}!</div>
                        <span class="text-muted-color font-medium">Sign in to continue</span>
                    </div>

                    <form @submit.prevent="submitLogin">
                        <Message v-if="expired" severity="warn" :closable="false" class="mb-4">Session expired, please sign in again.</Message>
                        <Message v-if="error" severity="error" :closable="false" class="mb-4">{{ error }}</Message>

                        <label for="username" class="block text-surface-900 dark:text-surface-0 text-xl font-medium mb-2">Username</label>
                        <InputText id="username" type="text" v-model="username" placeholder="Username" class="w-full md:w-[30rem] mb-8" autocomplete="username" />

                        <label for="password" class="block text-surface-900 dark:text-surface-0 font-medium text-xl mb-2">Password</label>
                        <Password id="password" v-model="password" placeholder="Password" :toggleMask="true" class="mb-8" fluid :feedback="false" autocomplete="current-password" />

                        <Button type="submit" label="Sign In" class="w-full" :loading="submitting" :disabled="!loginForm || !username || !password" />
                    </form>
                </div>
            </div>
        </div>
    </div>
</template>
