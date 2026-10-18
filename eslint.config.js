import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['**/dist/**', '**/node_modules/**', '**/generated/**', 'ai/**', 'docs/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      globals: { ...globals.node },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', ignoreRestSiblings: true },
      ],
    },
  },
  {
    files: ['frontend/**/*.{ts,tsx}'],
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      // Untrusted source text must never be injected as HTML (threat model T-06, ADR-0013).
      'no-restricted-syntax': [
        'error',
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: 'Render untrusted content as text. dangerouslySetInnerHTML is banned.',
        },
      ],
    },
  },
  {
    rules: {
      // Parameterised queries only (threat model T-13): flag SQL built with template literals.
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "CallExpression[callee.property.name='query'] > TemplateLiteral[expressions.length>0]",
          message: 'Use parameterised queries ($1, $2…) instead of interpolating values into SQL.',
        },
      ],
    },
    files: ['backend/**/*.ts'],
  },
);
