import js from '@eslint/js';
import astro from 'eslint-plugin-astro';
import pluginVue from 'eslint-plugin-vue';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
    {
        ignores: ['dist/**', 'node_modules/**', '.astro/**', 'src/lib/api/generated/schema.d.ts']
    },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    ...astro.configs.recommended,
    ...pluginVue.configs['flat/essential'],
    {
        files: ['**/*.vue'],
        languageOptions: {
            globals: globals.browser,
            parserOptions: {
                parser: tseslint.parser
            }
        },
        rules: {
            'vue/multi-word-component-names': 'off',
            'no-restricted-imports': [
                'error',
                {
                    patterns: [
                        {
                            group: ['@/lib/api/server/**', '@/lib/auth/server/**', '@/lib/config/server'],
                            message:
                                'Vue islands must call same-origin BFF endpoints and cannot import server-only modules.'
                        }
                    ]
                }
            ]
        }
    },
    {
        files: ['**/*.{ts,mts,cts,tsx,mjs}'],
        languageOptions: {
            globals: {
                ...globals.browser,
                ...globals.node
            }
        }
    }
);
