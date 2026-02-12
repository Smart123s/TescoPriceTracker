// ============================================
// POPUP LOGIC — Firefox Extension Template
// ============================================
// Handles the enable/disable toggle and syncs
// state with browser.storage so the background
// and content scripts can react accordingly.
// ============================================

// Standardize browser namespace (Chrome vs Firefox)
// Firefox uses 'browser', while Chrome uses 'chrome'.
if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

const toggleSwitch = document.getElementById("toggle-switch");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");

// ── Helpers ──────────────────────────────────

/** Update the UI to reflect the current enabled state. */
function updateUI(isEnabled) {
  toggleSwitch.checked = isEnabled;
  statusDot.classList.toggle("enabled", isEnabled);
  statusDot.classList.toggle("disabled", !isEnabled);
  statusText.textContent = isEnabled ? "Enabled" : "Disabled";
}

// ── Init ─────────────────────────────────────

// Load the saved state when popup opens.
browser.storage.local.get("extensionEnabled").then((result) => {
  // Default to enabled if no saved state exists.
  const isEnabled = result.extensionEnabled ?? true;
  updateUI(isEnabled);
});

// ── Events ───────────────────────────────────

toggleSwitch.addEventListener("change", async () => {
  const isEnabled = toggleSwitch.checked;

  // Persist the new state.
  await browser.storage.local.set({ extensionEnabled: isEnabled });

  // Update popup UI immediately.
  updateUI(isEnabled);

  // Notify the background script so it can act on open tabs.
  browser.runtime.sendMessage({
    type: "TOGGLE_EXTENSION",
    enabled: isEnabled,
  });
});
