import { defineParams } from '@sveltejs/kit/params';

export const params = defineParams({
	archive: (param) => (param === 'archive' ? param : undefined),
});
