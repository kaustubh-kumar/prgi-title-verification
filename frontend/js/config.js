/**
 * Deployment configuration for the frontend.
 *
 * The task's real-backend-integration brief asks for an environment
 * variable such as VITE_API_BASE_URL - but this frontend is deliberately
 * plain HTML/CSS/JS with no build step (see the redesign turn: adding
 * Vite/npm would be a second toolchain the team doesn't otherwise need,
 * for a project that's been Python-only so far). A static page has no
 * runtime access to real environment variables, so this file is the
 * equivalent: the ONE place that controls which backend the app talks to.
 *
 * For local development, the default below (http://localhost:8000) just
 * works against `uvicorn src.api.main:app --port 8000`. For a deployment
 * (e.g. Vercel), replace API_BASE_URL with the deployed backend's URL -
 * either by editing this file as part of the deploy step, or by having
 * the hosting platform template/replace it. Either way, this is the only
 * file that needs to change - never hardcode a backend URL anywhere else
 * (see frontend/js/api.js, frontend/js/realApi.js).
 */

// Set to false to use the real backend by default even without a query
// override (see USE_MOCK below). Kept true for now since this is still
// primarily developed/demoed against the mock - flip this once the real
// backend is the default expectation.
const DEFAULT_USE_MOCK = true;

export const API_BASE_URL = "http://localhost:8000";

/**
 * Whether to use the mock service instead of the real API. Resolves in
 * this order so the mock stays available as an explicit development
 * switch without needing a code change:
 *   1. ?mock=1 or ?mock=0 in the page URL (explicit override, easiest for
 *      manual testing/demos).
 *   2. DEFAULT_USE_MOCK above.
 */
function resolveUseMock() {
  const params = new URLSearchParams(window.location.search);
  if (params.has("mock")) {
    return params.get("mock") !== "0";
  }
  return DEFAULT_USE_MOCK;
}

export const USE_MOCK = resolveUseMock();
