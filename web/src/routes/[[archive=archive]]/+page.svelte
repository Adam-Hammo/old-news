<script lang="ts">
	import { page } from '$app/state';

	// The list and rail belong to the layout: on a wide screen an article sits over or
	// beside them rather than replacing them, so they cannot belong to this page.
</script>

<svelte:head
	><title>{page.params.archive ? 'The Archive — old news' : 'old news'}</title></svelte:head
>
