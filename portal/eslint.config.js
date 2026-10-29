import js from '@eslint/js'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'test-results', 'e2e/out', 'src/api/schema.d.ts'] },
  js.configs.recommended,
  tseslint.configs.recommendedTypeChecked,
  reactHooks.configs.flat['recommended-latest'],
  jsxA11y.flatConfigs.recommended,
  {
    languageOptions: {
      globals: { ...globals.browser },
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/stream/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        { patterns: [{ regex: '^(\\.\\.?/)+stream/', message: 'The stream is private to the run monitoring engine.' }] },
      ],
    },
  },
  {
    files: ['src/screens/run/runModel{,.test}.ts', 'src/screens/run/liveRun{,.test}.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              regex: '^(\\.\\.?/)+stream/(?!(feed|parse|brand)$)',
              message: 'The run page reads the stream only through feed, parse and brand.',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['eslint.config.js'],
    ...tseslint.configs.disableTypeChecked,
  },
)
