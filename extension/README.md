# 🧩 Firefox Extension Template (Manifest V3)

A clean, minimal Firefox extension template with an **enable/disable popup toggle** and **content injection**. Built with **Manifest V3** — the newest extension standard supported by Firefox.

---

## 📁 Project Structure

```
firefox-extension/
├── manifest.json            # Extension manifest (MV3)
├── background/
│   └── background.js        # Background script — state & messaging
├── content/
│   ├── content.js           # Content script — injects banner into pages
│   └── content.css          # Styles for the injected banner
├── popup/
│   ├── popup.html           # Popup panel UI
│   ├── popup.css            # Popup styles (dark theme)
│   └── popup.js             # Popup logic — toggle switch
├── icons/
│   ├── icon-16.png          # Toolbar icon
│   ├── icon-32.png
│   ├── icon-48.png
│   └── icon-128.png         # Add-on manager icon
└── README.md
```

---

## 🚀 How to Load in Firefox

1. Open Firefox and navigate to `about:debugging#/runtime/this-firefox`
2. Click **"Load Temporary Add-on…"**
3. Select the `manifest.json` file inside the `firefox-extension/` folder
4. The extension icon will appear in your toolbar — click it to open the popup

---

## 🔧 How It Works

| Component        | Role                                                                 |
|------------------|----------------------------------------------------------------------|
| **Popup**        | Toggle switch to enable/disable the extension                        |
| **Background**   | Relays the toggle state to all open tabs via messaging               |
| **Content**      | Injects a "Hello World" banner at the top of every page when enabled |
| **Storage**      | `browser.storage.local` persists the enabled/disabled state          |

### Data Flow

```
Popup toggle  →  browser.storage.local  →  Background script
                                             ↓
                                        Sends message to all tabs
                                             ↓
                                        Content script shows/hides banner
```

---

## 🎨 Customization Guide

### Change the injected content
Edit `content/content.js` — modify the `showBanner()` function to inject whatever HTML you want.

### Change the banner style
Edit `content/content.css` — change colors, position, fonts, etc.

### Change the popup look
Edit `popup/popup.css` — the theme variables are in `:root` at the top of the file.

### Add new permissions
Edit `manifest.json` — add to the `permissions` or `host_permissions` arrays as needed.

### Replace icons
Drop your own PNGs into the `icons/` folder (keep the same filenames and sizes).

---

## 📋 Key Technologies

- **Manifest V3** — latest Firefox extension manifest version
- **`browser.*` API** — Firefox's native extension API (Promise-based)
- **`browser.storage.local`** — persistent key-value storage
- **`browser.runtime.sendMessage`** — inter-script messaging
- **ES Modules** — modern JavaScript module syntax
- **CSS Custom Properties** — theme variables for easy customization

---

## ⚠️ Notes

- This template targets **Firefox 128+** (set in `browser_specific_settings.gecko.strict_min_version`)
- Temporary add-ons are removed when Firefox closes — for permanent install, you need to sign via [addons.mozilla.org](https://addons.mozilla.org)
- The content script runs on **all URLs** — narrow the `matches` in `manifest.json` if needed

---

## 📄 License

MIT — use this template however you like.
