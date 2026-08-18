/**
 * Mock data layer for the PRGI Title Verifier frontend.
 *
 * This is a STAND-IN for the real backend integration (FastAPI + Supabase +
 * the existing Python evidence/scoring/LLM pipeline, none of which are
 * wired up yet). Every number and piece of text below was captured from
 * REAL runs of the actual pipeline during development (src/llm/provider.py
 * against a real Gemini call, and src/llm/scoring.py's deterministic
 * output) - nothing here is invented from scratch, so the demo reflects
 * genuine backend behavior even though no backend is actually running.
 *
 * Response shape matches src/llm/schema.py's FINAL_RESULT_SCHEMA
 * (decision, verification_probability, confidence, violations,
 * explanation), with two deliberate additions - both represent data that
 * already exists deeper in the real pipeline (the evidence bundle from
 * src/evidence/builder.py and the per-candidate scores from
 * src/llm/scoring.py) but is not currently surfaced by the LLM's own
 * response schema. The real API layer (not built yet) will need to expose
 * both, which is the contract this frontend is being built against:
 *
 *   1. Each entry in similar_titles is enriched with the candidate
 *      metadata (language, periodicity, publication_state,
 *      publication_district) from the evidence bundle's
 *      candidates[].metadata, matched by registration_number.
 *
 *   2. A top-level `evidence` object exposes the STRONGEST candidate's
 *      deterministic signal breakdown - lexical_similarity (char_similarity),
 *      token_similarity, phonetic_similarity (all from that candidate's
 *      lexical_evidence/phonetic_evidence), exact_match
 *      (lexical_evidence.exact_normalized_match), and rule_evidence_count
 *      (how many rule_evidence entries fired for it, i.e. violations.length
 *      for this submission). This is what the "EVIDENCE" panel in the UI
 *      reads - none of it is calculated in the frontend.
 *
 * verification_probability is ALWAYS a value already computed by the
 * (mocked) deterministic backend - this file is the only place in the
 * frontend allowed to invent a number, and it does so only because it is
 * standing in for that backend, not because the frontend calculates it.
 */

const MOCK_RESPONSES = {
  "AAJ SAMAJ": {
    decision: "LIKELY_REJECT",
    verification_probability: 0.0,
    confidence: 1.0,
    violations: [
      {
        type: "exact_title_match",
        evidence:
          "Submitted title 'AAJ SAMAJ' is an exact normalized match with 100% lexical similarity to registered title 'AAJ SAMAJ' (HARHIN/2022/83438).",
      },
    ],
    evidence: {
      strongest_candidate: { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83438" },
      lexical_similarity: 100.0,
      token_similarity: 100.0,
      phonetic_similarity: 100.0,
      exact_match: true,
      rule_evidence_count: 1,
    },
    similar_titles: [
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83438", similarity: 100.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Fatehabad" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83432", similarity: 100.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Sirsa" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83425", similarity: 100.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Hisar" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83423", similarity: 100.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Rohtak" },
      { title: "AAJ SAMAJ", registration_number: "CHHIN/26/A6906", similarity: 100.0, language: "Hindi", periodicity: "Daily", publication_state: "Chandigarh", publication_district: "Chandigarh" },
    ],
    explanation:
      "The submitted title 'AAJ SAMAJ' is identical to multiple existing registered titles in the PRGI database, including HARHIN/2022/83438 and HARHIN/2022/83432, with 100.0% character and token similarity. Direct duplicates are not distinct, leading to a recommendation of rejection.",
  },

  "AAJ SAMAJ DAILY": {
    decision: "LIKELY_REJECT",
    verification_probability: 4.0,
    confidence: 0.95,
    violations: [
      {
        type: "periodicity_modification",
        evidence:
          "The submitted title appends the periodicity word 'daily' to the existing registered title 'AAJ SAMAJ'.",
      },
    ],
    evidence: {
      strongest_candidate: { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83438" },
      lexical_similarity: 75.0,
      token_similarity: 75.0,
      phonetic_similarity: 80.0,
      exact_match: false,
      rule_evidence_count: 1,
    },
    similar_titles: [
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83438", similarity: 75.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Fatehabad" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83432", similarity: 75.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Sirsa" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83425", similarity: 75.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Hisar" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83423", similarity: 75.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Rohtak" },
      { title: "AAJ SAMAJ", registration_number: "CHHIN/26/A6906", similarity: 75.0, language: "Hindi", periodicity: "Daily", publication_state: "Chandigarh", publication_district: "Chandigarh" },
    ],
    explanation:
      "The submitted title 'AAJ SAMAJ DAILY' directly incorporates the registered title 'AAJ SAMAJ' (e.g., registration HARHIN/2022/83438) by appending the periodicity term 'daily'. Rule checks confirmed the addition of a periodicity term to an existing title, yielding a lexical character similarity of 75.0%. Due to this clear structural collision and periodicity-term modification, the title is recommended for rejection.",
  },

  // All numeric fields below (verification_probability, evidence.*, and
  // similarity) were computed by actually re-running the real, unmodified
  // pipeline (src/evidence/builder.build_evidence_bundle +
  // src/llm/scoring.score_submission) against "AAJ SAMAJ WEEKLY" - not
  // approximated. The explanation text is the one representative/synthetic
  // element here: no real Gemini call was made for this exact input, so
  // its wording is written to match the style and content of the real
  // "AAJ SAMAJ DAILY" explanation above, grounded in the same real
  // evidence, but is not a literal captured model response.
  "AAJ SAMAJ WEEKLY": {
    decision: "LIKELY_REJECT",
    verification_probability: 6.4,
    confidence: 0.95,
    violations: [
      {
        type: "periodicity_modification",
        evidence:
          "The submitted title appends the periodicity word 'weekly' to the existing registered title 'AAJ SAMAJ'.",
      },
    ],
    evidence: {
      strongest_candidate: { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83438" },
      lexical_similarity: 72.0,
      token_similarity: 72.0,
      phonetic_similarity: 80.0,
      exact_match: false,
      rule_evidence_count: 1,
    },
    similar_titles: [
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83438", similarity: 72.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Fatehabad" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83432", similarity: 72.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Sirsa" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83425", similarity: 72.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Hisar" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83423", similarity: 72.0, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Rohtak" },
      { title: "AAJ SAMAJ", registration_number: "CHHIN/26/A6906", similarity: 72.0, language: "Hindi", periodicity: "Daily", publication_state: "Chandigarh", publication_district: "Chandigarh" },
    ],
    explanation:
      "[Representative explanation, not a captured model response - see code comment above] The submitted title 'AAJ SAMAJ WEEKLY' directly incorporates the registered title 'AAJ SAMAJ' (e.g., registration HARHIN/2022/83438) by appending the periodicity term 'weekly'. Rule checks confirmed the addition of a periodicity term to an existing title, yielding a lexical character similarity of 72.0%. Due to this clear structural collision and periodicity-term modification, the title is recommended for rejection.",
  },

  "THE AAJ SAMAJ": {
    decision: "REVIEW",
    verification_probability: 13.54,
    confidence: 0.7,
    violations: [
      {
        type: "generic_component",
        evidence:
          "Submitted title adds the generic prefix 'the' to the existing registered title 'AAJ SAMAJ'. Generic components are evidence only and do not automatically cause rejection.",
      },
    ],
    evidence: {
      strongest_candidate: { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83438" },
      lexical_similarity: 81.82,
      token_similarity: 81.82,
      phonetic_similarity: 80.0,
      exact_match: false,
      rule_evidence_count: 1,
    },
    similar_titles: [
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83438", similarity: 81.82, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Fatehabad" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83432", similarity: 81.82, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Sirsa" },
      { title: "AAJ SAMAJ", registration_number: "HARHIN/2022/83425", similarity: 81.82, language: "Hindi", periodicity: "Daily", publication_state: "Haryana", publication_district: "Hisar" },
    ],
    explanation:
      "The submitted title 'THE AAJ SAMAJ' shares its core wording with the existing registered title 'AAJ SAMAJ' (e.g. HARHIN/2022/83438), differing only by the generic prefix 'the'. Generic-component additions are treated as evidence only, not an automatic rule violation, so this case is flagged for manual review rather than outright rejection.",
  },

  "ZQXVN PLANETARY OBSERVATORY BULLETIN 7042": {
    decision: "LIKELY_ACCEPT",
    verification_probability: 55.0,
    confidence: 0.95,
    violations: [],
    evidence: {
      strongest_candidate: { title: "MAHASHAY DEHAT BULLETIN", registration_number: "UPHIN/2002/08360" },
      lexical_similarity: 50.0,
      token_similarity: 50.0,
      phonetic_similarity: 25.0,
      exact_match: false,
      rule_evidence_count: 0,
    },
    similar_titles: [
      { title: "MAHASHAY DEHAT BULLETIN", registration_number: "UPHIN/2002/08360", similarity: 50.0, language: "Hindi", periodicity: "Weekly", publication_state: "Uttar Pradesh", publication_district: "Muzaffarnagar" },
      { title: "SARV SAMAJ BULLETIN", registration_number: "UPHIN/2004/14379", similarity: 46.67, language: "Hindi", periodicity: "Weekly", publication_state: "Uttar Pradesh", publication_district: "Bijnor" },
      { title: "RAFTAR BULLETIN", registration_number: "UPHIN/2010/36291", similarity: 46.43, language: "Hindi", periodicity: "Weekly", publication_state: "Uttar Pradesh", publication_district: "Muzaffarnagar" },
      { title: "RAFTAR BULLETIN", registration_number: "UPHIN/2015/61375", similarity: 46.43, language: "Hindi", periodicity: "Daily", publication_state: "Uttar Pradesh", publication_district: "Muzaffarnagar" },
      { title: "KOSHALA BULLETIN", registration_number: "ODIODI/2007/21681", similarity: 42.11, language: "Oriya", periodicity: "Weekly", publication_state: "Odisha", publication_district: "Sambalpur" },
    ],
    explanation:
      "The submitted title 'ZQXVN PLANETARY OBSERVATORY BULLETIN 7042' is sufficiently distinct from existing database titles. The highest character similarity observed is 50.0% with 'MAHASHAY DEHAT BULLETIN' (UPHIN/2002/08360), and overlap is limited to the common word 'bulletin'. Distinctive terms such as 'zqxvn', 'planetary', 'observatory', and '7042' ensure clear differentiation. No title combination, periodicity gaming, or disallowed words were detected (note: disallowed word check was evaluated against a prototype/placeholder list, not official PRGI guidelines).",
  },
};

// Titles with a real fixture above, for the "did you mean one of these"
// hint in the unknown-title error message below.
const KNOWN_TEST_TITLES = Object.keys(MOCK_RESPONSES);

/**
 * IMPORTANT: this mock deliberately does NOT invent a generic "success"
 * response for titles it doesn't recognize. Doing that previously caused a
 * real bug - "AAJ SAMAJ WEEKLY" silently returned a fabricated 92%
 * LIKELY_ACCEPT with no evidence and no similar titles, which looked like
 * a real (if boring) backend result instead of what it actually was: an
 * untested input. An empty-but-plausible-looking response is worse than an
 * explicit error, because it's indistinguishable from a genuine "no
 * conflicts found" result.
 *
 * So: unknown titles reject with a clearly-labeled development error
 * instead. The UI's existing error state renders it - no new UI state was
 * needed. This function's job is exclusively to decide whether an input is
 * "known" or not; it is not itself a partial reimplementation of anything
 * backend-side.
 */
function unknownTitleError(title) {
  return new Error(
    `No mock fixture defined for "${title}". This is a development-only mock service - it only ` +
      `has real fixtures for a fixed set of test titles, it does not simulate arbitrary backend ` +
      `behavior. Try one of: ${KNOWN_TEST_TITLES.join(", ")}.`
  );
}

/**
 * Manual test hook for the error state: submitting a title containing this
 * (case-insensitive) makes the mock reject, so the UI's error path can be
 * exercised without a real backend to break.
 */
const ERROR_TEST_TRIGGER = "fail_test";

const MOCK_NETWORK_DELAY_MS = 700;

/**
 * Mock implementation of the title-verification call. Matches the async,
 * promise-based shape the real API client (frontend/js/api.js) will use,
 * so swapping the real fetch() call in later doesn't touch any caller.
 *
 * @param {string} title
 * @returns {Promise<object>} a FINAL_RESULT_SCHEMA-shaped object (see
 *   src/llm/schema.py), with similar_titles enriched as described above.
 */
export function mockVerifyTitle(title) {
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      if (title.toLowerCase().includes(ERROR_TEST_TRIGGER)) {
        reject(new Error("Mock backend error (triggered intentionally for testing - title contained 'fail_test')."));
        return;
      }
      const key = title.trim().toUpperCase();
      const canned = MOCK_RESPONSES[key];
      if (!canned) {
        reject(unknownTitleError(title));
        return;
      }
      resolve(canned);
    }, MOCK_NETWORK_DELAY_MS);
  });
}
