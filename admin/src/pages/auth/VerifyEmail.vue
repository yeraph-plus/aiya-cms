<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute } from 'vue-router';
import { verifyEmail } from '@/api/auth';
import AuthShell from '@/components/auth/AuthShell.vue';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';

const route = useRoute();
const { t } = useI18n();
const token = ref(typeof route.query.token === 'string' ? route.query.token : '');
const submitting = ref(false);
const completed = ref(false);
const error = ref<unknown>(null);

async function submit() {
    if (!token.value.trim()) return;
    error.value = null;
    submitting.value = true;
    try {
        await verifyEmail({ token: token.value.trim() });
        completed.value = true;
    } catch (caught) {
        error.value = caught;
    } finally {
        submitting.value = false;
    }
}

onMounted(() => {
    if (token.value) void submit();
});
</script>

<template>
    <AuthShell :title="t('routes.auth.verifyEmail')" :description="t('auth.verifyEmailHint')">
        <Message v-if="completed" severity="success" :closable="false">{{ t('auth.emailVerified') }}</Message>
        <form v-else class="flex flex-col gap-5" @submit.prevent="submit">
            <ApiErrorMessage v-if="error" :error="error" />
            <div>
                <label for="verify-email-token" class="mb-2 block font-medium">{{ t('auth.verificationToken') }}</label>
                <InputText id="verify-email-token" v-model="token" class="w-full" autocomplete="one-time-code" required />
            </div>
            <Button type="submit" :label="t('auth.verifyEmail')" :loading="submitting" :disabled="!token.trim()" />
        </form>
        <template #footer>
            <RouterLink class="text-primary font-medium" :to="{ name: 'login' }">{{ t('auth.backToLogin') }}</RouterLink>
        </template>
    </AuthShell>
</template>
