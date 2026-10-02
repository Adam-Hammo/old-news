declare global {
	namespace App {
		interface PageState {
			/** Where this history entry was reached from. */
			behind?: string;
		}
	}
}

export {};
