import js from '@eslint/js';
import pluginVue from 'eslint-plugin-vue';
import globals from 'globals';
import prettierConfig from '@vue/eslint-config-prettier';

export default [
    {
        name: 'app/files-to-lint',
        files: ['**/*.{js,mjs,cjs,vue}']
    },
    {
        name: 'app/files-to-ignore',
        ignores: ['**/dist/**', '**/node_modules/**', '**/public/**', '**/src/assets/**']
    },
    js.configs.recommended,
    ...pluginVue.configs['flat/essential'],
    {
        name: 'app/language-options',
        files: ['**/*.{js,mjs,cjs}'],
        languageOptions: {
            globals: globals.browser
        }
    },
    {
        name: 'app/node-config',
        files: ['vite.config.mjs', 'eslint.config.mjs'],
        languageOptions: {
            globals: globals.node
        }
    },
    {
        name: 'app/vue-rules',
        files: ['**/*.vue'],
        languageOptions: {
            globals: globals.browser
        },
        rules: {
            'vue/multi-word-component-names': 'off',
            'vue/no-reserved-component-names': 'off',
            'vue/block-order': [
                'error',
                {
                    order: ['script', 'template', 'style']
                }
            ]
        }
    },
    prettierConfig
];
