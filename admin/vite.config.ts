/// <reference types="vitest/config" />
import { PrimeVueResolver } from '@primevue/auto-import-resolver';
import tailwindcss from '@tailwindcss/vite';
import vue from '@vitejs/plugin-vue';
import Components from 'unplugin-vue-components/vite';
import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';

// https://vitejs.dev/config/
export default defineConfig({
    envDir: '../',
    envPrefix: ['VITE_', 'AIYA_ISSUER', 'AIYA_PUBLIC_BASE_URL'],
    optimizeDeps: {
        noDiscovery: true
    },
    plugins: [
        vue(),
        tailwindcss(),
        Components({
            resolvers: [PrimeVueResolver()],
            dts: 'src/components.d.ts'
        })
    ],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url))
        }
    },
    css: {},
    server: {
        host: '127.0.0.1',
        port: 5173,
        strictPort: true,
        allowedHosts: ['local.host']
    },
    test: {
        environment: 'jsdom',
        include: ['src/tests/**/*.test.ts']
    }
});
