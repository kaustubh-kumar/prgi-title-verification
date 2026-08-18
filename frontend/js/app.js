/**
 * UI logic for PRGI Verify.
 *
 * No similarity/probability/rule inference happens anywhere in this file -
 * every number and label rendered here is read directly from the object
 * returned by verifyTitle() (frontend/js/api.js), which currently proxies
 * to the mock service and will later call the real backend without this
 * file changing. The only frontend-side computation permitted is display
 * sorting (by an existing similarity field) and animating bars toward an
 * already-supplied percentage.
 */

import { verifyTitle, IS_MOCK } from "./api.js";

const mockIndicator = document.getElementById("mock-indicator");
mockIndicator.hidden = !IS_MOCK;

const form = document.getElementById("verify-form");
const titleInput = document.getElementById("title-input");
const verifyButton = document.getElementById("verify-button");
const inputError = document.getElementById("input-error");

const loadingState = document.getElementById("loading-state");
const errorState = document.getElementById("error-state");
const errorMessage = document.getElementById("error-message");
const resultRoot = document.getElementById("result");

const submittedTitleDisplay = document.getElementById("submitted-title-display");
const decisionIcon = document.getElementById("decision-icon");
const decisionBadge = document.getElementById("decision-badge");
const probabilityValue = document.getElementById("probability-value");
const confidenceNote = document.getElementById("confidence-note");

const evidenceSubheading = document.getElementById("evidence-subheading");
const evidenceBars = document.getElementById("evidence-bars");

const similarTitlesList = document.getElementById("similar-titles-list");
const similarTitlesEmpty = document.getElementById("similar-titles-empty");
const violationsList = document.getElementById("violations-list");
const violationsEmpty = document.getElementById("violations-empty");
const explanationText = document.getElementById("explanation-text");

const DECISION_LABELS = {
  LIKELY_ACCEPT: "Likely Accept",
  LIKELY_REJECT: "Likely Reject",
  REVIEW: "Review",
};

const DECISION_CLASSES = {
  LIKELY_ACCEPT: "decision-panel--accept",
  LIKELY_REJECT: "decision-panel--reject",
  REVIEW: "decision-panel--review",
};

// Non-color signal for decision state (accessibility requirement: do not
// rely on color alone). Text labels already do this too; the glyph is a
// second, redundant cue.
const DECISION_ICONS = {
  LIKELY_ACCEPT: "✓", // check mark
  LIKELY_REJECT: "✕", // cross
  REVIEW: "!",
};

// Human-readable labels for known violation types. Relabels the `type`
// string the backend already returned - never adds a violation that
// wasn't in the response. Unknown types fall back to a readable version
// of the raw string rather than being dropped.
const VIOLATION_LABELS = {
  exact_title_match: "Exact title match",
  exact_normalized_match: "Exact title match",
  periodicity_modification: "Periodicity modification",
  generic_component: "Generic component",
  generic_component_added: "Generic component",
  combination_detected: "Combination of existing titles",
  disallowed_word: "Disallowed word",
  phonetic_match: "Phonetic similarity match",
};

function violationLabel(type) {
  if (VIOLATION_LABELS[type]) return VIOLATION_LABELS[type];
  return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function setState(state) {
  loadingState.hidden = state !== "loading";
  errorState.hidden = state !== "error";
  verifyButton.disabled = state === "loading";

  if (state === "result") {
    resultRoot.hidden = false;
    // Force a reflow before adding the entrance class so the transition
    // actually plays (otherwise the browser may coalesce the hidden->visible
    // and class-add into a single frame with no visible transition).
    void resultRoot.offsetWidth;
    resultRoot.classList.add("result--visible");
  } else {
    resultRoot.hidden = true;
    resultRoot.classList.remove("result--visible");
  }
}

function renderResult(title, data) {
  submittedTitleDisplay.textContent = title;

  const decisionLabel = DECISION_LABELS[data.decision] || data.decision;
  decisionBadge.textContent = decisionLabel;
  decisionIcon.textContent = DECISION_ICONS[data.decision] || "";

  const decisionPanel = document.getElementById("decision-panel");
  decisionPanel.className = "panel decision-panel " + (DECISION_CLASSES[data.decision] || "");

  // verification_probability is read verbatim from the backend response -
  // formatted for display only, never computed here.
  probabilityValue.textContent = `${formatPercent(data.verification_probability)}%`;

  confidenceNote.textContent =
    typeof data.confidence === "number"
      ? `Model confidence: ${formatPercent(data.confidence * 100)}%`
      : "";

  renderEvidence(data.evidence || null);
  renderSimilarTitles(data.similar_titles || []);
  renderViolations(data.violations || []);

  // Explanation is rendered verbatim - no paraphrasing or editing.
  explanationText.textContent = data.explanation || "";
}

function renderEvidence(evidence) {
  evidenceBars.innerHTML = "";

  if (!evidence || !evidence.strongest_candidate) {
    evidenceSubheading.textContent = "No candidate strong enough to report evidence for.";
    return;
  }

  evidenceSubheading.textContent = `Strongest candidate: ${evidence.strongest_candidate.title} (${evidence.strongest_candidate.registration_number})`;

  // Token similarity is deliberately not shown here - it's still present
  // untouched on `evidence.token_similarity` (backend/evidence bundle keep
  // both signals; this file just doesn't render this one, to reduce visual
  // redundancy with Text similarity for a non-technical audience). There is
  // no separate detailed/technical view in this UI yet, so it isn't
  // exposed anywhere else either - add it there if/when one exists.
  appendBarRow(evidenceBars, "Text similarity", evidence.lexical_similarity, "Text (character) similarity");
  appendBarRow(evidenceBars, "Phonetic", evidence.phonetic_similarity, "Phonetic similarity");
  appendFactRow(evidenceBars, "Exact match", evidence.exact_match ? "YES" : "NO");
  appendFactRow(
    evidenceBars,
    "Rule evidence",
    `${evidence.rule_evidence_count} found`
  );
}

function appendBarRow(container, label, value, ariaLabel) {
  const dt = document.createElement("dt");
  dt.textContent = label;

  const dd = document.createElement("dd");
  dd.appendChild(buildBar(value, ariaLabel));

  container.appendChild(dt);
  container.appendChild(dd);
}

function appendFactRow(container, label, value) {
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.className = "fact-value";
  dd.textContent = value;
  container.appendChild(dt);
  container.appendChild(dd);
}

/**
 * Builds an accessible, animated horizontal bar for a backend-supplied
 * percentage. The bar starts at 0 and animates to `value` on the next
 * frame (skipped entirely under prefers-reduced-motion, per requirement 6).
 * ARIA attributes always reflect the true final value immediately,
 * regardless of the visual animation state.
 */
function buildBar(value, ariaLabel) {
  const track = document.createElement("div");
  track.className = "bar-track";
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-valuemin", "0");
  track.setAttribute("aria-valuemax", "100");
  track.setAttribute("aria-valuenow", String(Math.round(value)));
  track.setAttribute("aria-label", `${ariaLabel}: ${formatPercent(value)} percent`);

  const fill = document.createElement("div");
  fill.className = "bar-fill";
  fill.style.width = "0%";
  track.appendChild(fill);

  const numeric = document.createElement("span");
  numeric.className = "bar-value";
  numeric.textContent = `${formatPercent(value)}%`;

  const wrapper = document.createElement("div");
  wrapper.className = "bar-row";
  wrapper.appendChild(track);
  wrapper.appendChild(numeric);

  const targetWidth = `${Math.max(0, Math.min(100, value))}%`;
  if (prefersReducedMotion()) {
    fill.style.width = targetWidth;
  } else {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        fill.style.width = targetWidth;
      });
    });
  }

  return wrapper;
}

function renderSimilarTitles(titles) {
  similarTitlesList.innerHTML = "";

  if (titles.length === 0) {
    similarTitlesEmpty.hidden = false;
    return;
  }
  similarTitlesEmpty.hidden = true;

  // Sort by backend-provided similarity, descending. Display sort only -
  // the similarity values themselves are untouched.
  const sorted = [...titles].sort((a, b) => b.similarity - a.similarity);
  const reduceMotion = prefersReducedMotion();

  sorted.forEach((candidate, index) => {
    const li = document.createElement("li");
    li.className = "similar-title-card";
    if (!reduceMotion) {
      li.style.animationDelay = `${Math.min(index, 8) * 60}ms`;
      li.classList.add("similar-title-card--stagger");
    }

    const meta = [candidate.publication_state, candidate.publication_district, candidate.language]
      .filter(Boolean)
      .join(" · ");

    const header = document.createElement("div");
    header.className = "similar-title-card__header";
    header.innerHTML = `
      <span class="similar-title-card__title">${escapeHtml(candidate.title)}</span>
    `;

    const reg = document.createElement("div");
    reg.className = "similar-title-card__reg";
    reg.textContent = candidate.registration_number;

    const metaRow = document.createElement("div");
    metaRow.className = "similar-title-card__meta";
    if (meta) metaRow.textContent = meta;

    if (candidate.periodicity) {
      const periodicityTag = document.createElement("span");
      periodicityTag.className = "periodicity-tag";
      periodicityTag.textContent = candidate.periodicity;
      metaRow.appendChild(document.createTextNode(meta ? " · " : ""));
      metaRow.appendChild(periodicityTag);
    }

    const barWrap = document.createElement("div");
    barWrap.className = "similar-title-card__bar";
    barWrap.appendChild(buildBar(candidate.similarity, `Match with ${candidate.title}`));

    li.appendChild(header);
    li.appendChild(reg);
    li.appendChild(metaRow);
    li.appendChild(barWrap);
    similarTitlesList.appendChild(li);
  });
}

function renderViolations(violations) {
  violationsList.innerHTML = "";

  if (violations.length === 0) {
    violationsEmpty.hidden = false;
    return;
  }
  violationsEmpty.hidden = true;

  for (const v of violations) {
    const li = document.createElement("li");
    li.className = "violation-card";
    const heading = document.createElement("p");
    heading.className = "violation-card__type";
    heading.textContent = violationLabel(v.type);
    const detail = document.createElement("p");
    detail.className = "violation-card__detail";
    detail.textContent = v.evidence;
    li.appendChild(heading);
    li.appendChild(detail);
    violationsList.appendChild(li);
  }
}

function formatPercent(value) {
  if (typeof value !== "number") return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const title = titleInput.value.trim();
  if (!title) {
    inputError.textContent = "Enter a proposed title before verifying.";
    inputError.hidden = false;
    return;
  }
  inputError.hidden = true;

  setState("loading");

  try {
    const data = await verifyTitle(title);
    renderResult(title, data);
    setState("result");
  } catch (err) {
    errorMessage.textContent = err.message || "Something went wrong. Please try again.";
    setState("error");
  }
});
