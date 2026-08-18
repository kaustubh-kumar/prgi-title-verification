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
 * Deployed on Vercel, frontend and API are served from the SAME origin
 * (see vercel.json - /api/* and /health route to the Python function,
 * everything else serves frontend/ statically), so the deployed app uses
 * a relative path ("") rather than any hardcoded host - never hardcode a
 * backend URL anywhere else (see frontend/js/api.js, frontend/js/realApi.js).
 * Local development (frontend on :8765, backend on :8000) is a different
 * origin, so that case still needs an explicit host - detected via
 * window.location, not a separate build step.
 */

const LOCAL_DEV_API_BASE_URL = "http://localhost:8000";

function resolveApiBaseUrl() {
  const { hostname } = window.location;
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return LOCAL_DEV_API_BASE_URL;
  }
  // Deployed: same origin as the frontend itself.
  return "";
}

export const API_BASE_URL = resolveApiBaseUrl();

// Real backend is the default now that it's live end-to-end (DB + Gemini
// both confirmed working) - flip back to true only if reverting to
// mock-only development.
const DEFAULT_USE_MOCK = false;

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
