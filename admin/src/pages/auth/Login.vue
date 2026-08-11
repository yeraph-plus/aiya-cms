<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';
import { createLoginFormArgs, submitLogin as submitOidcLogin, type LoginFormArgs } from '@/auth/oidc';
import { storePendingRedirect } from '@/auth/storage';
import AuthShell from '@/components/auth/AuthShell.vue';

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const username = ref('');
const password = ref('');
const loginForm = ref<LoginFormArgs | null>(null);
const error = ref('');
const submitting = ref(false);

const expired = route.query.reason === 'expired';

onMounted(async () => {
    storePendingRedirect(route.query.redirect as string | null);
    try {
        loginForm.value = await createLoginFormArgs();
    } catch (caught) {
        const detail = caught instanceof Error ? caught.message : String(caught);
        error.value = t('auth.oidcUnavailable', { detail });
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
        const detail = caught instanceof Error ? caught.message : t('auth.loginFailed');
        await router.replace({ name: 'error', query: { message: detail } });
    }
}
</script>

<template>
    <AuthShell :title="t('routes.auth.login')" :description="t('auth.signInHint')">
        <form class="flex flex-col gap-5" @submit.prevent="submitLogin">
            <Message v-if="expired" severity="warn" :closable="false">{{ t('auth.sessionExpired') }}</Message>
            <Message v-if="error" severity="error" :closable="false">{{ error }}</Message>
            <div>
                <label for="username" class="mb-2 block font-medium">{{ t('auth.username') }}</label>
                <InputText id="username" v-model="username" type="text" class="w-full" autocomplete="username" required />
            </div>
            <div>
                <div class="mb-2 flex items-center justify-between gap-4">
                    <label for="password" class="font-medium">{{ t('auth.password') }}</label>
                    <RouterLink class="text-primary text-sm font-medium" :to="{ name: 'password-reset' }">{{ t('auth.forgotPassword') }}</RouterLink>
                </div>
                <Password id="password" v-model="password" fluid :feedback="false" toggle-mask autocomplete="current-password" required />
            </div>
            <Button type="submit" :label="t('auth.signIn')" :loading="submitting" :disabled="!loginForm || !username || !password" />
        </form>
        <template #footer>
            <span>{{ t('auth.needAccount') }}</span>
            <RouterLink class="text-primary ml-1 font-medium" :to="{ name: 'register' }">{{ t('auth.register') }}</RouterLink>
        </template>
    </AuthShell>
</template>
