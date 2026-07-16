import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import vitest from '@vitest/eslint-plugin'
import prettier from 'eslint-config-prettier/flat'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'coverage']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
  },
  {
    files: ['**/*.test.{ts,tsx}', 'src/test/**/*.{ts,tsx}'],
    extends: [vitest.configs.recommended],
    // Test helpers export a custom render + fixtures, not a Fast Refresh boundary
    rules: { 'react-refresh/only-export-components': 'off' },
  },
  // must stay last so it disables rules that conflict with Prettier
  prettier,
])
