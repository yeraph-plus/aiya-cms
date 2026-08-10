import js from '@eslint/js';
import pluginVue from 'eslint-plugin-vue';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import prettierConfig from '@vue/eslint-config-prettier';

export default tseslint.config(
    {
        name: 'app/files-to-lint',
        files: ['**/*.{ts,mts,cts,tsx,vue}']
    },
    {
        name: 'app/files-to-ignore',
        ignores: ['**/dist/**', '**/node_modules/**', '**/public/**', '**/src/assets/**', '**/src/api/schema.d.ts', '**/src/components.d.ts']
    },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    ...pluginVue.configs['flat/essential'],
    {
        name: 'app/vue-language-options',
        files: ['**/*.vue'],
        languageOptions: {
            globals: globals.browser,
            parserOptions: {
                parser: tseslint.parser
            }
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
    {
        name: 'app/browser-config',
        files: ['**/*.{ts,mts,cts,tsx}'],
        languageOptions: {
            globals: globals.browser
        }
    },
    {
        name: 'app/node-config',
        files: ['vite.config.ts', 'eslint.config.ts', 'scripts/**/*.ts'],
        languageOptions: {
            globals: globals.node
        }
    },
    prettierConfig
);
