/**
 * Real backend client. Only called from frontend/js/api.js (the single
 * integration point) - never imported directly by app.js, mirroring how
 * mockApi.js is isolated.
 */

import { API_BASE_URL } from "./config.js";

/**
 * @param {string} title
 * @returns {Promise<object>} the API's response body (see
 *   src/api/response.py for the exact shape).
 * @throws Error with a user-presentable message on any failure.
 */
export async function realVerifyTitle(title) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
  } catch (networkError) {
    throw new Error(
      `Could not reach the verification backend at ${API_BASE_URL}. Is it running? (${networkError.message})`
    );
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // response wasn't JSON - fall back to the status-only message above.
    }
    throw new Error(`Verification request failed: ${detail}`);
  }

  return response.json();
}
