/**
 * Web and mobile are meant to show the same underlying data from the API.
 * Legacy client-side mocks match old screenshots but diverge from the mobile app.
 *
 * - Default: mock OFF → web calls the same FastAPI routes as mobile.
 * - Set VITE_USE_MOCK=true in `.env` to force the in-browser demo dataset (no backend required).
 */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';
