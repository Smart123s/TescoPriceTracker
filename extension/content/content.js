// ============================================
// CONTENT SCRIPT — Firefox Extension Template
// ============================================
// Injects a "Hello World" banner at the top
// of every webpage when the extension is enabled.
// Listens for enable/disable messages from the
// background script and also checks storage
// on initial load.
// ============================================

const BANNER_ID = "my-extension-hello-banner";

// ── Banner Management ────────────────────────

/** Create and inject the Hello World banner. */
function showBanner() {
  // Don't inject twice.
  if (document.getElementById(BANNER_ID)) return;

  const banner = document.createElement("div");
  banner.id = BANNER_ID;
  banner.textContent = "👋 Hello World — My Extension is active!";

  // Prepend to <body> so it appears at the very top.
  document.body.prepend(banner);
}

/** Remove the banner if it exists. */
function hideBanner() {
  const banner = document.getElementById(BANNER_ID);
  if (banner) banner.remove();
}

// ── Message Listener ─────────────────────────

browser.runtime.onMessage.addListener((message) => {
  if (message.type !== "SET_ENABLED") return;

  if (message.enabled) {
    showBanner();
  } else {
    hideBanner();
  }
});

// ── Init — check stored state on page load ───

browser.storage.local.get("extensionEnabled").then((result) => {
  if (result.extensionEnabled) {
    showBanner();
  }
});
