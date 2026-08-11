<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { register } from '@/api/auth';
import AuthShell from '@/components/auth/AuthShell.vue';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';

const { t } = useI18n();
const username = ref('');
const email = ref('');
const displayName = ref('');
const password = ref('');
const confirmPassword = ref('');
const submitting = ref(false);
const completed = ref(false);
const error = ref<unknown>(null);
const validationMessage = ref('');

const canSubmit = computed(() => Boolean(username.value.trim() && email.value.trim() && password.value.length >= 12 && confirmPassword.value.length >= 12));

async function submit() {
    validationMessage.value = '';
    if (password.value !== confirmPassword.value) {
        validationMessage.value = t('auth.passwordMismatch');
        return;
    }
    error.value = null;
    submitting.value = true;
    try {
        await register({ username: username.value.trim(), email: email.value.trim(), password: password.value, display_name: displayName.value.trim() || null });
        completed.value = true;
    } catch (caught) {
        error.value = caught;
    } finally {
        submitting.value = false;
    }
}
</script>

<template>
    <AuthShell :title="t('routes.auth.register')" :description="t('auth.registerHint')">
        <Message v-if="completed" severity="success" :closable="false">{{ t('auth.registrationComplete') }}</Message>
        <form v-else class="flex flex-col gap-5" @submit.prevent="submit">
            <ApiErrorMessage v-if="error" :error="error" />
            <Message v-if="validationMessage" severity="warn" :closable="false">{{ validationMessage }}</Message>
            <div>
                <label for="register-username" class="mb-2 block font-medium">{{ t('auth.username') }}</label>
                <InputText id="register-username" v-model="username" class="w-full" autocomplete="username" required />
            </div>
            <div>
                <label for="register-email" class="mb-2 block font-medium">{{ t('auth.email') }}</label>
                <InputText id="register-email" v-model="email" type="email" class="w-full" autocomplete="email" required />
            </div>
            <div>
                <label for="register-display-name" class="mb-2 block font-medium">{{ t('auth.displayName') }} <span class="text-muted-color text-sm">({{ t('auth.optional') }})</span></label>
                <InputText id="register-display-name" v-model="displayName" class="w-full" autocomplete="name" />
            </div>
            <div>
                <label for="register-password" class="mb-2 block font-medium">{{ t('auth.password') }}</label>
                <Password id="register-password" v-model="password" class="w-full" fluid :feedback="false" toggle-mask autocomplete="new-password" required />
                <small class="text-muted-color">{{ t('auth.passwordMinimum') }}</small>
            </div>
            <div>
                <label for="register-confirm-password" class="mb-2 block font-medium">{{ t('auth.confirmPassword') }}</label>
                <Password id="register-confirm-password" v-model="confirmPassword" class="w-full" fluid :feedback="false" toggle-mask autocomplete="new-password" required />
            </div>
            <Button type="submit" :label="t('auth.register')" :loading="submitting" :disabled="!canSubmit" />
        </form>
        <template #footer>
            <span>{{ t('auth.haveAccount') }}</span>
            <RouterLink class="text-primary ml-1 font-medium" :to="{ name: 'login' }">{{ t('auth.backToLogin') }}</RouterLink>
        </template>
    </AuthShell>
</template>
