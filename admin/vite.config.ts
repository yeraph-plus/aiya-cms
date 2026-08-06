import path from 'node:path'
import VueI18nPlugin from '@intlify/unplugin-vue-i18n/vite'
import Vue from '@vitejs/plugin-vue'
import Unocss from 'unocss/vite'
import AutoImport from 'unplugin-auto-import/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'
import Components from 'unplugin-vue-components/vite'
import { defineConfig } from 'vitest/config'
import Pages from 'vite-plugin-pages'
import Layouts from 'vite-plugin-vue-layouts-next'

export default defineConfig({
  test: {
    environment: 'happy-dom',
    setupFiles: ['vitest.setup.ts'],
    include: ['src/**/*.spec.ts'],
  },
  server: {
    port: 7000,
    host: true,
    proxy: {
      '/api': {
        target: process.env.AIYA_API_URL ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    hmr: {
      host: 'localhost',
    },
  },
  assetsInclude: ['**/*.yml', '**/*.yaml'],
  resolve: {
    alias: {
      '~/': `${path.resolve(import.meta.dirname, 'src')}/`,
      '@/': `${path.resolve(import.meta.dirname, 'src')}/`,
    },
  },
  build: {
    chunkSizeWarningLimit: 1600,
  },
  plugins: [
    // https://github.com/intlify/vite-plugin-vue-i18n
    VueI18nPlugin({
      runtimeOnly: false,
      fullInstall: true,
      include: [
        path.resolve(import.meta.dirname, 'src/locales/**/*.yml'),
        path.resolve(import.meta.dirname, 'src/locales/**/*.yaml'),
      ]
    }),
    Vue({
      include: [/\.vue$/],
    }),

    Pages({
      extensions: ['vue'],
      importMode: 'async',
    }),

    // https://github.com/JohnCampionJr/vite-plugin-vue-layouts
    Layouts({
      layoutsDirs: 'src/layouts',
      pagesDirs: 'src/pages',
      defaultLayout: 'default',
    }),

    // https://github.com/antfu/unplugin-auto-import
    AutoImport({
      imports: [
        'vue',
        'vue/macros',
        'vue-i18n',
        'vue-router',
        '@vueuse/core',
        {
          'naive-ui': [
            'useDialog',
            'useMessage',
            'useNotification',
            'useLoadingBar',
            'usePopover',
          ],
        },
      ],
      dts: 'src/auto-imports.d.ts',
      dirs: ['src/composables', 'src/store'],
      vueTemplate: true,
    }),

    Components({
      extensions: ['vue'],
      resolvers: [NaiveUiResolver()],
      include: [/\.vue$/, /\.vue\?vue/],
      dts: 'src/components.d.ts',
    }),

    // https://github.com/antfu/unocss
    // see uno.config.ts for config
    Unocss(),
    // https://github.com/webfansplz/vite-plugin-vue-devtools
    // VueDevTools(),
  ],
  define: { 'process.env': {} },
})
