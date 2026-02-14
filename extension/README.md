# Tesco Price Tracker Extension

A browser extension that tracks and visualizes price history for products on the Tesco Hungary website (`bevasarlas.tesco.hu`).

## Features

- **Price History Charts**: Automatically injects a Chart.js-based price history graph directly onto Tesco product pages.
- **Detailed Statistics**: Shows lowest, highest, and average prices over the last 30 days.
- **Multi-language Support**: Automatically detects and switches between English and Hungarian based on the page URL.
- **Clubcard Price Support**: Tracks both regular and Clubcard-specific prices.
- **Global Toggle**: Easily enable or disable the tracker via the extension popup menu.

## Support Sites

The extension is designed to work on:
- `https://bevasarlas.tesco.hu/groceries/en-HU/products/*`
- `https://bevasarlas.tesco.hu/groceries/hu-HU/products/*`

## Installation

### For Development (Manual Load)

1. Open your browser's extensions page:
   - **Chrome**: `chrome://extensions`
   - **Firefox**: `about:debugging#/runtime/this-firefox` (or `about:addons`)
2. Enable **Developer Mode**.
3. Click **Load unpacked** (Chrome) or **Load Temporary Add-on** (Firefox).
4. Select the `extension/` folder in this project.

## How it Works

1. **Content Script**: When you visit a supported Tesco product page, `content/content.js` identifies the product unique identifier (TPNC).
2. **Data Fetching**: The extension requests historical price data from the backend or local storage.
3. **Visualization**: Using [Chart.js](https://www.chartjs.org/), it renders a line chart showing price fluctuations.
4. **Localization**: Labels are translated into English or Hungarian depending on the user's current Tesco site language.

## Project Structure

- `manifest.json`: WebExtension metadata and permissions.
- `background/`: Contains `background.js` for handling cross-tab messaging and background tasks.
- `content/`: 
  - `content.js`: The script that runs in the context of the Tesco website.
  - `chart.umd.min.js`: The bundled Chart.js library.
  - `content.css`: Styles for the injected chart container.
- `popup/`: The small UI container seen when clicking the extension icon.
- `icons/`: Essential icons for the extension.

## License

This project is licensed under the [LICENSE](../LICENSE) file in the root directory.
