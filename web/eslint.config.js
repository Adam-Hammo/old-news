import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import ts from 'typescript-eslint';

// Inline, because Kit 3 refuses to have a svelte.config.js at all — its own settings go
// to the `sveltekit(...)` plugin. This is only what the linter needs to parse a component.
const svelteConfig = { preprocess: vitePreprocess() };

export default ts.config(
	js.configs.recommended,
	...ts.configs.recommended,
	...svelte.configs.recommended,
	{
		languageOptions: { globals: { ...globals.browser, ...globals.node } },
		rules: {
			// A binding that exists only to be read — which is how a rune subscribes to
			// something — is declared with a leading underscore. Same convention as
			// [tool.vulture] in pyproject.toml.
			'@typescript-eslint/no-unused-vars': [
				'error',
				{ argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
			],
		},
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts'],
		languageOptions: {
			parserOptions: {
				projectService: true,
				// typescript-eslint refuses a non-standard extension without being told.
				extraFileExtensions: ['.svelte'],
				parser: ts.parser,
				svelteConfig,
			},
		},
	},
	{ ignores: ['build/', '.svelte-kit/', 'node_modules/', 'src/lib/api/schema.d.ts'] },
);
