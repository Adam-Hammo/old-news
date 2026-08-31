import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { playwright } from '@vitest/browser-playwright';
import { defineConfig } from 'vitest/config';

// What `tailscale serve --set-path=/api` does in front of the deployment: the prefix is
// the routing, and Litestar is never told about it.
const api = process.env.OLD_NEWS_API ?? 'http://127.0.0.1:16051';

export default defineConfig({
	plugins: [sveltekit({ preprocess: vitePreprocess(), adapter: adapter() })],
	server: {
		port: 16053,
		proxy: {
			'/api': {
				target: api,
				changeOrigin: true,
				rewrite: (path) => path.replace(/^\/api/, ''),
			},
		},
	},
	test: {
		projects: [
			// A real browser rather than a DOM shim, for the same reason the Python suite
			// will not mock Postgres: the thing under test is what the layout actually does.
			{
				extends: './vite.config.ts',
				test: {
					name: 'browser',
					include: ['src/**/*.browser.test.ts'],
					setupFiles: ['./src/vitest-setup.ts'],
					browser: {
						enabled: true,
						headless: true,
						provider: playwright(),
						instances: [{ browser: 'chromium' }],
					},
				},
			},
			{
				extends: './vite.config.ts',
				test: {
					name: 'node',
					environment: 'node',
					include: ['src/**/*.test.ts'],
					exclude: ['src/**/*.browser.test.ts'],
				},
			},
		],
	},
});
