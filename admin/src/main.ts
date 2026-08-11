import { createApp } from 'vue';
import App from './App.vue';
import router from './router';

import Aura from '@primeuix/themes/aura';
import PrimeVue from 'primevue/config';
import ConfirmationService from 'primevue/confirmationservice';
import ToastService from 'primevue/toastservice';

import '@/assets/tailwind.css';
import '@/assets/styles.scss';

import { configureApi, createApiClient } from '@/api';
import { env } from '@/env';
import { getAccessToken } from '@/auth/session';
import { handleUnauthorized } from '@/auth/unauthorized';
import { i18n } from '@/i18n';

configureApi(
    createApiClient({
        baseUrl: env.apiBaseUrl,
        getAccessToken,
        onUnauthorized: handleUnauthorized
    })
);

const app = createApp(App);

app.use(router);
app.use(i18n);
app.use(PrimeVue, {
    license:
        'eyJpZCI6IjE0NjM1YThmLTU2MzQtNGM2Mi04MGRkLWQ3NDU1YmQ4MzU3ZiIsInByb2R1Y3QiOiJwcmltZXVpIiwidGllciI6ImNvbW11bml0eSIsInR5cGUiOiJkZXYiLCJpYXQiOjE3ODYzMDA2MTUsImV4cCI6MTgxNzgzNjYxNX0.ThzPGZRv0Ef8QVeWgiomsqfsCiG1SInMOgHWPrMdYLDUjghZEfglgZMLgm1on1-A3ogix9WciwomuH_LO5XwBw',
    theme: {
        preset: Aura,
        options: {
            darkModeSelector: '.app-dark'
        }
    }
});
app.use(ToastService);
app.use(ConfirmationService);

app.mount('#app');
