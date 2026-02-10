// ============================================
// BACKGROUND SCRIPT — Firefox Extension Template
// ============================================
// Listens for toggle messages from the popup
// and tells every open tab to show or hide
// the injected content.
// ============================================

// ── Message Listener ─────────────────────────

browser.runtime.onMessage.addListener(async (message) => {
  if (message.type !== "TOGGLE_EXTENSION") return;

  const { enabled } = message;

  // Send the new state to every open tab's content script.
  const tabs = await browser.tabs.query({});
  for (const tab of tabs) {
    // Skip restricted pages (about:*, moz-extension:*, etc.)
    if (!tab.url || tab.url.startsWith("about:") || tab.url.startsWith("moz-extension:")) {
      continue;
    }

    try {
      await browser.tabs.sendMessage(tab.id, {
        type: "SET_ENABLED",
        enabled,
      });
    } catch {
      // Content script may not be loaded on this tab yet — that's fine.
    }
  }
});

// ── Installation / Update ────────────────────

browser.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    // Set default state on first install.
    await browser.storage.local.set({ extensionEnabled: false });
    console.log("[My Extension] Installed — extension is disabled by default.");
  }
});
