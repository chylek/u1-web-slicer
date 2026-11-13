import js from '@eslint/js';
import globals from 'globals';

export default [
  {ignores: ['static/vendor/**', 'node_modules/**']},
  js.configs.recommended,
  {
    files: ['static/**/*.js'],
    languageOptions: {ecmaVersion: 2023, sourceType: 'module', globals: {...globals.browser, ...globals.serviceworker}},
    rules: {'no-unused-vars': ['error', {argsIgnorePattern: '^_', caughtErrors: 'none'}], 'no-empty': ['error', {allowEmptyCatch: true}]},
  },
];
