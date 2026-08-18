/**
 * SINGLE INTEGRATION POINT for backend communication.
 *
 * Every UI component calls verifyTitle() from this file and nothing else -
 * app.js never imports mockApi.js or realApi.js directly. Which one
 * actually runs is decided once, here, from frontend/js/config.js's
 * USE_MOCK flag (itself overridable via a ?mock=0/1 URL param - see that
 * file) - the mock stays available as an explicit development switch,
 * production deployments just need USE_MOCK/DEFAULT_USE_MOCK set to false.
 */

import { USE_MOCK } from "./config.js";
import { mockVerifyTitle } from "./mockApi.js";
import { realVerifyTitle } from "./realApi.js";

/**
 * Whether verifyTitle() is currently backed by the mock service. app.js
 * reads this to show/hide the "Demo data · backend not connected"
 * indicator.
 */
export const IS_MOCK = USE_MOCK;

/**
 * @param {string} title - the proposed publication title, as typed by the user.
 * @returns {Promise<object>} the verification result (see
 *   src/api/response.py and frontend/js/mockApi.js for the exact shape -
 *   the two are kept in sync deliberately).
 * @throws if the backend call fails.
 */
export async function verifyTitle(title) {
  return IS_MOCK ? mockVerifyTitle(title) : realVerifyTitle(title);
}
