// ============================================
// BACKGROUND SCRIPT — Firefox Extension Template
// ============================================
// Listens for toggle messages from the popup
// and tells every open tab to show or hide
// the injected content.
// ============================================

// Standardize browser namespace (Chrome vs Firefox)
// Firefox uses 'browser', while Chrome uses 'chrome'.
if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

// ── Message Listener ─────────────────────────

browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "TOGGLE_EXTENSION") {
    handleToggle(message.enabled);
    return;
  }
  
  if (message.type === "FETCH_HISTORY") {
    fetchHistory(message.tpnc)
      .then(data => sendResponse(data))
      .catch(error => sendResponse({ error: error.message }));
    return true; // Return true to keep the message channel open for async response
  }
});

async function handleToggle(enabled) {
  const tabs = await browser.tabs.query({});
  for (const tab of tabs) {
    if (!tab.url || tab.url.startsWith("about:") || tab.url.startsWith("moz-extension:")) {
      continue;
    }
    try {
      await browser.tabs.sendMessage(tab.id, {
        type: "SET_ENABLED",
        enabled,
      });
    } catch {
      // Content script may not be loaded on this tab yet
    }
  }
}

async function fetchHistory(tpnc) {
  try {
    const response = await fetch(`http://localhost:5000/api/history/${tpnc}`);
    if (!response.ok) {
        throw new Error(`Server returned ${response.status}`);
    }
    const data = await response.json();
    return data;
  } catch (error) {
    console.error("Fetch error:", error);
    throw error;
  }
}


// ── Installation / Update ────────────────────

browser.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    // Set default state on first install.
    await browser.storage.local.set({ extensionEnabled: true });
    console.log("[TescoPriceTracker] Installed — extension is enabled by default.");
  }
});
