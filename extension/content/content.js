// ============================================
// CONTENT SCRIPT — Tesco Price Tracker
// ============================================
// Injects a price-history chart + statistics
// below the product hero section on Tesco HU
// product pages. Detects page language from the
// URL and localizes all labels accordingly.
// ============================================

// Standardize browser namespace (Chrome vs Firefox)
// Firefox uses 'browser', while Chrome uses 'chrome'.
if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

const CONTAINER_ID = "tpt-price-tracker-container";

// ── Localization ─────────────────────────────

const TRANSLATIONS = {
  en: {
    title: "Price History (Last 30 Days)",
    currentPrice: "Current Price",
    lowestPrice: "Lowest Price",
    highestPrice: "Highest Price",
    averagePrice: "Average Price",
    trend: "30-Day Trend",
    priceRange: "Price Range",
    chartLabel: "Price (Ft)",
    footer: "Tesco Price Tracker", // Neutral
    min: "Min",
    max: "Max",
    clubcardPrice: "Clubcard Price",
    noData: "No price history available",
    loading: "Loading price history...",
  },
  hu: {
    title: "Árelőzmények (Utolsó 30 nap)",
    currentPrice: "Jelenlegi ár",
    lowestPrice: "Legalacsonyabb ár",
    highestPrice: "Legmagasabb ár",
    averagePrice: "Átlagos ár",
    trend: "30 napos trend",
    priceRange: "Ártartomány",
    chartLabel: "Ár (Ft)",
    footer: "Tesco Ár Figyelő", // Neutral
    min: "Min",
    max: "Max",
    clubcardPrice: "Clubcard ár",
    noData: "Nincs elérhető árelőzmény",
    loading: "Áradatok betöltése...",
  },
};

/**
 * Detect language from the URL path.
 * URL pattern: /groceries/en-HU/... or /groceries/hu-HU/...
 */
function detectLanguage() {
  const match = window.location.pathname.match(/\/groceries\/(\w{2})-\w{2}\//);
  if (match) {
    const lang = match[1].toLowerCase();
    if (TRANSLATIONS[lang]) return lang;
  }
  // Also check <html lang="...">
  const htmlLang = document.documentElement.lang?.toLowerCase().split("-")[0];
  if (htmlLang && TRANSLATIONS[htmlLang]) return htmlLang;
  return "en"; // default
}

function getStrings() {
  return TRANSLATIONS[detectLanguage()];
}

// ── Locale Helper ────────────────────────────

function getLocale() {
  return detectLanguage() === "hu" ? "hu-HU" : "en-GB";
}

// ── Read Actual Page Price ───────────────────

/**
 * Try to scrape the current product price from the page DOM.
 * Returns the price as a number (Ft) or null if not found.
 */
function readPagePrice() {
  // Look for common price selectors on Tesco HU product pages
  const selectors = [
    '[data-auto="price-value"]',
    '.price-per-sellable-unit .value',
    '.price-control-wrapper .value',
    '.offer-text .value',
  ];

  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) {
      const num = parseInt(el.textContent.replace(/[^\d]/g, ""), 10);
      if (!isNaN(num) && num > 0) return num;
    }
  }

  // Fallback: scan visible text for a pattern like "899 Ft"
  const allText = document.body.innerText;
  const match = allText.match(/(\d[\d\s]*)\s*Ft/i);
  if (match) {
    const num = parseInt(match[1].replace(/\s/g, ""), 10);
    if (!isNaN(num) && num > 0) return num;
  }

  return null;
}

// ── Data Fetching ────────────────────────────

// Helper to calculate days difference
function diffDays(d1, d2) {
  const oneDay = 24 * 60 * 60 * 1000;
  return Math.round(Math.abs((d1 - d2) / oneDay));
}

// Format date for display
function formatDate(dateObj, locale) {
  return dateObj.toLocaleDateString(locale, { month: "short", day: "numeric" });
}

// Parse ISO string safely
function parseDate(str) {
  if (!str) return new Date();
  // Truncate fractional part to avoid issues with 6-digit microseconds (Python default)
  const safeStr = str.split('.')[0];
  const d = new Date(safeStr);
  // Reset time to midnight to ensure daily alignment
  d.setHours(0, 0, 0, 0);
  return d;
}

/**
 * Fetch real history from the local Python backend via background script
 */
function getTpncFromUrl() {
  const match = window.location.pathname.match(/\/products\/(\d+)/);
  return match ? match[1] : null;
}

async function getRealData() {
  const tpnc = getTpncFromUrl();
  if (!tpnc) return null;

  try {
    const response = await browser.runtime.sendMessage({
      type: "FETCH_HISTORY",
      tpnc: tpnc
    });

    if (response && response.history && response.history.length > 0) {
      return response.history;
    }
  } catch (e) {
    console.error("Failed to fetch history:", e);
  }
  return null;
}

/**
 * Process raw API data into Chart.js friendly format with NO FALSE INTERPOLATION.
 * Fills missing days with nulls.
 */
function processRealData(history) {
  const locale = getLocale();
  
  // 1. Sort history by date ascending
  const sorted = history
    .map(h => ({ 
      date: parseDate(h.timestamp), 
      price: h.price_actual,
      clubcardPrice: h.clubcard_price
    }))
    .sort((a, b) => a.date - b.date);

  if (sorted.length === 0) return { labels: [], prices: [], clubcardPrices: [] };

  const labels = [];
  const prices = [];
  const clubcardPrices = [];

  const startDate = sorted[0].date;
  const endDate = new Date(); // Today
  endDate.setHours(0,0,0,0);

  // If the data is weirdly in the future, cap it? No, trust data.
  // But usually we fill up to today. 
  // If the last data point is older than today, we might want to extend the line...
  // BUT user said "if some date is mjssed then skipt that line".
  // So we only fill from start to end of *DATA*? 
  // No, usually "Price History" implies up to now. 
  // Let's assume the user wants to see the gaps.
  
  // Use the last data point as the end of the range, 
  // OR today if we want to show it's not updated recently.
  // Let's go from first data point to 'today' to show recency context.
  // If the product wasn't scraped for a week, that should appear as a gap at the end.
  
  const totalDays = diffDays(endDate, startDate);
  
  // Create a map for quick lookup: timestamp_ms -> price
  const priceMap = new Map();
  const clubcardMap = new Map();
  sorted.forEach(item => {
    priceMap.set(item.date.getTime(), item.price);
    clubcardMap.set(item.date.getTime(), item.clubcardPrice);
  });

  const cur = new Date(startDate);
  for (let i = 0; i <= totalDays; i++) {
    const time = cur.getTime();
    labels.push(formatDate(cur, locale));
    
    if (priceMap.has(time)) {
      prices.push(priceMap.get(time));
      clubcardPrices.push(clubcardMap.get(time) || null);
    } else {
      prices.push(null); // GAP
      clubcardPrices.push(null);
    }
    
    // Next day
    cur.setDate(cur.getDate() + 1);
  }

  return { labels, prices, clubcardPrices };
}

// ── Mock Data Generator (Fallback) ───────────

function generateMockData() {
  const now = new Date();
  const labels = [];
  const prices = [];
  const clubcardPrices = [];
  const locale = getLocale();

  // Use real page price as anchor when possible
  const pagePrice = readPagePrice();
  const basePrice = pagePrice || 1499;
  const variance = Math.round(basePrice * 0.25); // ±25 % swing

  // Seeded random walk: start slightly above base and wander
  let current = basePrice + Math.round((Math.random() - 0.5) * variance * 0.5);

  for (let i = 29; i >= 0; i--) {
    const date = new Date(now);
    date.setDate(date.getDate() - i);
    labels.push(
      date.toLocaleDateString(locale, { month: "short", day: "numeric" })
    );

    // Small daily jitter (random walk)
    const step = Math.round((Math.random() - 0.48) * variance * 0.18);
    current = Math.max(
      Math.round(basePrice * 0.75),
      Math.min(Math.round(basePrice * 1.25), current + step)
    );
    prices.push(current);
    clubcardPrices.push(null);
  }

  // Make the last value equal to the actual page price (if we have it)
  if (pagePrice) {
    prices[prices.length - 1] = pagePrice;
  }

  return { labels, prices, clubcardPrices };
}

// ── Statistics Calculator ────────────────────

function calculateStats(prices) {
  // Filter out nulls for calculation
  const validPrices = prices.filter(p => p !== null && p !== undefined);
  
  if (validPrices.length === 0) {
    return { min: 0, max: 0, avg: 0, current: 0, trend: 0, trendPercent: "0.0" };
  }

  const min = Math.min(...validPrices);
  const max = Math.max(...validPrices);
  const avg = Math.round(validPrices.reduce((a, b) => a + b, 0) / validPrices.length);
  
  // Current is the *most recent known price* (last known valid value)
  const current = validPrices[validPrices.length - 1];
  const first = validPrices[0];
  
  const trend = current - first;
  const trendPercent = first !== 0 ? ((trend / first) * 100).toFixed(1) : "0.0";

  return { min, max, avg, current, trend, trendPercent };
}

// ── Find Injection Point ─────────────────────

/**
 * Find where to insert the chart on the page.
 * Tries multiple strategies to accommodate the SPA layout.
 * Returns { element, mode } where mode is "before" or "after", or null.
 */
function findInsertionPoint() {
  // Strategy 0 (New Priority): Under the Product Image section
  // As explicitly requested, we look for the product image container/section.
  const imageSection = document.querySelector('section[aria-label="product images"]') || 
                       document.querySelector('section[aria-label="termékképek"]') ||
                       document.querySelector('[data-auto="product-image"]') ||
                       document.querySelector('.product-image__container');
  
  if (imageSection) {
    // On the new Tesco Layout, the image and product info are often siblings.
    // We want to find the top-most common parent of the 'hero' area to insert after it.
    let hero = imageSection;
    // Walk up to find the container that likely holds both image and details
    for (let i = 0; i < 3; i++) {
        if (hero.parentElement && 
            (hero.parentElement.classList.contains('mfe-pdp-wrapper') || 
             hero.parentElement.tagName === 'MAIN' ||
             hero.parentElement.classList.contains('product-details-page'))) {
            break;
        }
        if (hero.parentElement) hero = hero.parentElement;
    }
    return { element: hero, mode: "after" };
  }

  // Strategy 1: Check for the specific accordion container seen in the site's markup.
  // This is typically the "About this product" section.
  const accordionSelector = [
    '[data-auto="pdp-overview-accordion"]',
    '[data-testid="accordion"]',
    '.UKSL9q_container', // From screenshot
    '[class*="pop-overview-accordion"]',
    '[class*="pdp-overview-accordion"]'
  ].join(',');
  
  const accordion = document.querySelector(accordionSelector);
  if (accordion) {
    // Walk up to the top-most level of this section if it's inside a wrapper
    let target = accordion;
    if (accordion.parentElement && accordion.parentElement.classList.contains('azuiwe2GnJXyab4')) {
      target = accordion.parentElement;
    }
    return { element: target, mode: "before" };
  }

  // Strategy 0: Exact match based on the description header ID.
  const descriptionHeader = document.getElementById("accordion-header-product-description");
  if (descriptionHeader) {
    const container = descriptionHeader.closest('[data-auto*="accordion"]') || 
                      descriptionHeader.closest('section') || 
                      descriptionHeader.closest('.UKSL9q_item')?.parentElement;
    if (container) {
      return { element: container, mode: "before" };
    }
  }

  // Strategy 1: Prefer explicit product block identified by class used on Tesco pages.
  // mnwM3actwF_P5wK / mnwM3actwF_PSwK etc.
  const specialBlock = document.querySelector('[class*="mnwM3actwF_P"]') || 
                       document.querySelector('[class*="mnwM3actwF_S"]');
  if (specialBlock) {
    return { element: specialBlock, mode: "before" };
  }

  // Strategy 2 (primary): Find "About this product" / "A termékről" text
  // anywhere in the DOM and insert right BEFORE its container.
  const allElements = document.querySelectorAll(
    "h2, h3, h4, button, span, div, [class*='heading'], [class*='title'], [class*='accordion'], [class*='Accordion']"
  );
  for (const el of allElements) {
    // Only check direct text, not deeply nested children
    const ownText = Array.from(el.childNodes)
      .filter((n) => n.nodeType === Node.TEXT_NODE || n.nodeType === Node.ELEMENT_NODE)
      .map((n) => n.textContent.trim())
      .join("")
      .toLowerCase();

    if (ownText === "about this product" || ownText === "a termékről" || 
        ownText.includes("product description") || ownText.includes("termékleírás")) {
      // Walk up to a meaningful block container
      let section = el;
      while (section.parentElement && section.parentElement !== document.body) {
        const parent = section.parentElement;
        const style = window.getComputedStyle(parent);
        // Stop when we reach a block that looks like a top-level section
        if (
          parent.offsetWidth > document.body.offsetWidth * 0.5 &&
          (style.display === "block" || style.display === "flex") &&
          parent.children.length <= 10
        ) {
          section = parent;
          break;
        }
        section = parent;
      }
      return { element: section, mode: "before" };
    }
  }

  // Strategy 3: TreeWalker text-node search (catches hidden/unusual markup)
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        const t = node.textContent.trim().toLowerCase();
        if (t === "about this product" || t === "a termékről") {
          return NodeFilter.FILTER_ACCEPT;
        }
        return NodeFilter.FILTER_REJECT;
      },
    }
  );
  const textNode = walker.nextNode();
  if (textNode) {
    // Walk up enough levels to get a meaningful section boundary
    let container = textNode.parentElement;
    for (let i = 0; i < 5 && container.parentElement && container.parentElement !== document.body; i++) {
      const parent = container.parentElement;
      if (parent.offsetWidth > document.body.offsetWidth * 0.5 && parent.children.length <= 10) {
        container = parent;
        break;
      }
      container = parent;
    }
    return { element: container, mode: "before" };
  }

  // Strategy 4: Find product price area and insert after the product hero wrapper
  const priceEl =
    document.querySelector('[data-auto="price-value"]') ||
    document.querySelector('[class*="price"]');

  if (priceEl) {
    // Walk up to a full-width wrapper
    let el = priceEl;
    for (let i = 0; i < 15 && el.parentElement && el.parentElement !== document.body; i++) {
      const parent = el.parentElement;
      if (parent.offsetWidth > document.body.offsetWidth * 0.65) {
        return { element: parent, mode: "after" };
      }
      el = parent;
    }
    return { element: el, mode: "after" };
  }

  // Strategy 5: Fallback — product image
  const productImg =
    document.querySelector('img[src*="digitalcontent"][alt]') ||
    document.querySelector('[data-auto="product-image"] img') ||
    document.querySelector(".product-image__container img");

  if (productImg) {
    let el = productImg.closest("div");
    for (let i = 0; i < 10 && el && el.parentElement && el.parentElement !== document.body; i++) {
      const parent = el.parentElement;
      if (parent.offsetWidth > document.body.offsetWidth * 0.65) {
        return { element: parent, mode: "after" };
      }
      el = parent;
    }
    if (el) return { element: el, mode: "after" };
  }

  return null;
}

// ── Theme State ──────────────────────────────

let g_currentTheme = getSystemTheme();

function getSystemTheme() {
  return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
}

function toggleTheme() {
  const newTheme = g_currentTheme === 'dark' ? 'light' : 'dark';
  applyTheme(newTheme);
}

function setButtonIcon(btn, isDark) {
  btn.innerHTML = ''; // Clear existing
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.style.width = "20px";
  svg.style.height = "20px";

  if (isDark) {
    // Sun Icon
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", "12");
    circle.setAttribute("cy", "12");
    circle.setAttribute("r", "5");
    svg.appendChild(circle);
    
    const lines = [
      [12, 1, 12, 3], [12, 21, 12, 23], [4.22, 4.22, 5.64, 5.64],
      [18.36, 18.36, 19.78, 19.78], [1, 12, 3, 12], [21, 12, 23, 12],
      [4.22, 19.78, 5.64, 18.36], [18.36, 5.64, 19.78, 4.22]
    ];
    lines.forEach(([x1, y1, x2, y2]) => {
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", x1);
      line.setAttribute("y1", y1);
      line.setAttribute("x2", x2);
      line.setAttribute("y2", y2);
      svg.appendChild(line);
    });
  } else {
    // Moon Icon
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z");
    svg.appendChild(path);
  }
  btn.appendChild(svg);
}

function applyTheme(theme) {
  g_currentTheme = theme;
  const container = document.getElementById(CONTAINER_ID);
  if (!container) return;

  const toggleBtn = container.querySelector('.tpt-theme-toggle');
  
  if (theme === 'dark') {
    container.classList.add('tpt-theme-dark');
    if (toggleBtn) {
      setButtonIcon(toggleBtn, true);
      toggleBtn.title = 'Switch to Light Mode';
    }
  } else {
    container.classList.remove('tpt-theme-dark');
    if (toggleBtn) {
      setButtonIcon(toggleBtn, false);
      toggleBtn.title = 'Switch to Dark Mode';
    }
  }

  // Update chart colors if chart exists
  if (g_chartInstance) {
    updateChartTheme(g_chartInstance, theme);
  }
}

function updateChartTheme(chart, theme) {
  const isDark = (theme === 'dark');
  const axisColor = isDark ? '#9aa9bf' : '#64748b';
  const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.06)';
  const tooltipBg = isDark ? '#1e293b' : '#1e293b'; // Tooltip usually dark is fine, or adapt
  const tooltipText = '#f8fafc';
  
  // Update scales
  if (chart.options.scales.x) {
    chart.options.scales.x.ticks.color = axisColor;
  }
  if (chart.options.scales.y) {
    chart.options.scales.y.ticks.color = axisColor;
    chart.options.scales.y.grid.color = gridColor;
  }

  // Update no-data plugin text (if we could access it easily - simplistic approach for now)
  // Re-creating gradient might be tricky without full context, 
  // but we can update point borders etc.
  
  chart.update('none'); // Update without animation
}

function createStatCard(label, value, className = "") {
  const card = document.createElement("div");
  card.className = "tpt-stat-card";
  
  const labelDiv = document.createElement("div");
  labelDiv.className = "tpt-stat-label";
  labelDiv.textContent = label;
  
  const valueDiv = document.createElement("div");
  valueDiv.className = "tpt-stat-value" + (className ? " " + className : "");
  valueDiv.textContent = value;
  
  card.appendChild(labelDiv);
  card.appendChild(valueDiv);
  return card;
}

// ── Chart & UI Injection ─────────────────────

async function injectPriceTracker() {
  if (g_isInjecting) return; // Prevent concurrent injections
  
  const tpnc = getTpncFromUrl();
  if (!tpnc) return;

  g_isInjecting = true;
  try {
    const existingContainer = document.getElementById(CONTAINER_ID);
    if (existingContainer) {
      // If the container is for the SAME product and already has a chart, do nothing.
      if (existingContainer.dataset.tpnc === tpnc) {
        const existingCanvas = existingContainer.querySelector('canvas');
        if (existingCanvas && (existingCanvas._tptChart || g_chartInstance)) {
           // Check if it's still in a reasonable place? No, let observer handle that.
           return;
        }
      }
      // If it's a different product or broken, remove it.
      existingContainer.remove();
    }

    const t = getStrings();
    const insertion = findInsertionPoint();
    let finalInsertion = insertion;

    if (!finalInsertion) {
      console.warn("[TescoPriceTracker] Could not find insertion point — using fallback insertion.");
      const fallback = document.querySelector(
        'main, [role="main"], #content, .page-content, #root, #app, [data-auto="page-content"]'
      );
      if (fallback) {
        finalInsertion = { element: fallback, mode: "prepend" };
      } else {
        finalInsertion = { element: document.body, mode: "prepend" };
      }
    }

    // ── Build Container (Placeholder) ──
    const container = document.createElement("div");
    container.id = CONTAINER_ID;
    container.dataset.tpnc = tpnc; // Store current product ID

    // Title
    const title = document.createElement("div");
    title.className = "tpt-title";
    
    const titleLeft = document.createElement("div");
    titleLeft.style.cssText = "display:flex; align-items:center; gap:8px;";
    
    const titleIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    titleIcon.classList.add("tpt-icon");
    titleIcon.setAttribute("viewBox", "0 0 24 24");
    titleIcon.setAttribute("fill", "none");
    titleIcon.setAttribute("stroke", "currentColor");
    titleIcon.setAttribute("stroke-width", "2");
    
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", "22 12 18 12 15 21 9 3 6 12 2 12");
    titleIcon.appendChild(polyline);
    
    titleLeft.appendChild(titleIcon);
    titleLeft.appendChild(document.createTextNode(t.title));
    title.appendChild(titleLeft);

    const toggleBtn = document.createElement("button");
    toggleBtn.className = "tpt-theme-toggle";
    toggleBtn.type = "button";
    setButtonIcon(toggleBtn, g_currentTheme === 'dark');
    toggleBtn.title = g_currentTheme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
    toggleBtn.onclick = (e) => {
      e.stopPropagation();
      toggleTheme();
    };
    title.appendChild(toggleBtn);
    container.appendChild(title);

    // Chart Canvas Wrapper with Loading State
    const chartWrapper = document.createElement("div");
    chartWrapper.className = "tpt-chart-wrapper tpt-loading";
    
    const loadingEl = document.createElement("div");
    loadingEl.className = "tpt-loading-spinner";
    
    const spinner = document.createElement("div");
    spinner.className = "spinner";
    loadingEl.appendChild(spinner);
    
    const loadingText = document.createElement("span");
    loadingText.textContent = t.loading;
    loadingEl.appendChild(loadingText);
    
    chartWrapper.appendChild(loadingEl);

    const canvas = document.createElement("canvas");
    canvas.id = "tpt-price-chart";
    canvas.height = 280;
    chartWrapper.appendChild(canvas);
    container.appendChild(chartWrapper);

    // Stats Grid (Initial State)
    const statsGrid = document.createElement("div");
    statsGrid.className = "tpt-stats-grid";
    
    const locale = getLocale();
    const pagePrice = readPagePrice();
    const displayCurrent = pagePrice ? `${pagePrice.toLocaleString(locale)} Ft` : "—";

    statsGrid.appendChild(createStatCard(t.currentPrice, displayCurrent));
    statsGrid.appendChild(createStatCard(t.lowestPrice, "..."));
    statsGrid.appendChild(createStatCard(t.highestPrice, "..."));
    statsGrid.appendChild(createStatCard(t.averagePrice, "..."));
    statsGrid.appendChild(createStatCard(t.trend, "..."));
    statsGrid.appendChild(createStatCard(t.priceRange, "..."));
    
    container.appendChild(statsGrid);

    // Footer
    const footer = document.createElement("div");
    footer.className = "tpt-footer";
    footer.textContent = `${t.footer}`;
    container.appendChild(footer);

    // Insert into DOM immediately
    if (finalInsertion.mode === "before") {
      finalInsertion.element.parentNode.insertBefore(container, finalInsertion.element);
    } else if (finalInsertion.mode === "after") {
      finalInsertion.element.parentNode.insertBefore(container, finalInsertion.element.nextSibling);
    } else if (finalInsertion.mode === "prepend") {
      finalInsertion.element.insertBefore(container, finalInsertion.element.firstChild);
    } else {
      finalInsertion.element.appendChild(container);
    }

    applyTheme(g_currentTheme);

    // ── Fetch Real Data ──
    const realHistory = await getRealData();
    
    let labels = [];
    let prices = [];
    let clubcardPrices = [];
    let hasHistory = false;

    if (realHistory && realHistory.length > 0) {
      const processed = processRealData(realHistory);
      if (processed.labels && processed.labels.length > 0) {
        labels = processed.labels;
        prices = processed.prices;
        clubcardPrices = processed.clubcardPrices;
        hasHistory = true;
      }
    }

    // ── Update UI with Data ──
    // Double check we are still on the same product after the async fetch
    const currentTpnc = getTpncFromUrl();
    if (currentTpnc !== tpnc) {
      container.remove();
      return;
    }

    chartWrapper.classList.remove('tpt-loading');
    
    const stats = calculateStats(prices);
    if (pagePrice) stats.current = pagePrice;

    const trendColor = stats.trend <= 0 ? "#16a34a" : "#dc2626";
    const trendArrow = stats.trend <= 0 ? "↓" : "↑";
    const trendSign = stats.trend > 0 ? "+" : "";
    const fmtPrice = (val) => (hasHistory && val > 0) ? `${val.toLocaleString(locale)} Ft` : "—";
    const fmtTrend = (val, pct) => {
        if (!hasHistory || val === 0) return "—";
        return `${trendArrow} ${trendSign}${Math.abs(val).toLocaleString(locale)} Ft (${trendSign}${pct}%)`;
    };

    // Update stats cards
    const statValues = statsGrid.querySelectorAll('.tpt-stat-value');
    if (statValues.length === 6) {
      statValues[0].textContent = pagePrice ? `${pagePrice.toLocaleString(locale)} Ft` : "—";
      statValues[1].textContent = fmtPrice(stats.min);
      statValues[1].className = "tpt-stat-value tpt-stat-low";
      statValues[2].textContent = fmtPrice(stats.max);
      statValues[2].className = "tpt-stat-value tpt-stat-high";
      statValues[3].textContent = fmtPrice(stats.avg);
      statValues[4].textContent = fmtTrend(stats.trend, stats.trendPercent);
      if (hasHistory && stats.trend !== 0) {
        statValues[4].style.color = trendColor;
      }
      statValues[5].textContent = fmtPrice(stats.max - stats.min);
    }

    renderChart(canvas, labels, prices, clubcardPrices, stats, t);

  } finally {
    g_isInjecting = false;
  }
}

function renderChart(canvas, labels, prices, clubcardPrices, stats, t) {
  const ctx = canvas.getContext("2d");

  // Destroy any previous Chart instance attached to this canvas to avoid flicker/leaks
  try {
    if (g_chartInstance && typeof g_chartInstance.destroy === 'function') {
      g_chartInstance.destroy();
    }
    // also attempt to clear Chart.getChart if Chart.js exposes it
    if (window.Chart && window.Chart.getChart) {
      const existing = window.Chart.getChart(canvas);
      if (existing) existing.destroy();
    }
  } catch (err) {
    console.warn('Error while destroying previous chart (harmless):', err);
  }

  // Theme colors
  const isDark = (g_currentTheme === 'dark');
  const axisColor = isDark ? '#9aa9bf' : '#64748b';
  const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.06)';

  // Create gradient fill
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
  gradient.addColorStop(0, "rgba(0, 83, 159, 0.35)");
  gradient.addColorStop(1, "rgba(0, 83, 159, 0.02)");

  const hasData = prices && prices.length > 0 && prices.some(p => p !== null);

  // Custom plugin to draw "No Data" text
  const noDataPlugin = {
    id: 'noDataText',
    afterDraw: (chart) => {
      if (!hasData) {
        const { ctx, width, height } = chart;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = '14px sans-serif';
        ctx.fillStyle = isDark ? '#94a3b8' : '#64748b'; // slightly simplified
        ctx.fillText(t.noData, width / 2, height / 2);
        ctx.restore();
      }
    }
  };

  // Create the Chart instance and store it globally so we can destroy it later
  g_chartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: t.chartLabel,
          data: prices,
          borderColor: "#00539f",
          backgroundColor: gradient,
          borderWidth: 2.5,
          pointBackgroundColor: "#00539f",
          pointBorderColor: "#ffffff",
          pointBorderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 6,
          fill: true,
          tension: 0.3,
          spanGaps: false // IMPORTANT: Do not connect points over missing days
        },
        {
          label: t.clubcardPrice,
          data: clubcardPrices,
          borderColor: "#eab308", // Yellow/Gold for Clubcard
          backgroundColor: "rgba(234, 179, 8, 0.0)",
          borderWidth: 2.5,
          borderDash: [5, 5],
          pointBackgroundColor: "#eab308",
          pointBorderColor: "#ffffff",
          pointBorderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 6,
          fill: false,
          tension: 0.3,
          spanGaps: false
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: "index",
      },
      plugins: {
        legend: {
          display: true, // Show legend now that we have 2 lines
          position: 'top',
          align: 'end',
          labels: {
            boxWidth: 12,
            usePointStyle: true,
            font: { size: 10 },
            color: axisColor
          }
        },
        tooltip: {
          backgroundColor: "#1e293b",
          titleColor: "#f8fafc",
          bodyColor: "#f8fafc",
          padding: 12,
          cornerRadius: 8,
          displayColors: true,
          callbacks: {
            label: function (context) {
              if (context.raw === null) return null;
              return `${context.dataset.label}: ${context.parsed.y.toLocaleString(getLocale())} Ft`;
            },
          },
        },
        annotation: undefined,
      },
      scales: {
        x: {
          grid: {
            display: false,
          },
          ticks: {
            color: axisColor,
            font: { size: 11 },
            maxRotation: 45,
            maxTicksLimit: 10,
          },
        },
        y: {
          grid: {
            color: gridColor,
          },
          ticks: {
            color: axisColor,
            font: { size: 11 },
            callback: function (value) {
              return value.toLocaleString(getLocale()) + " Ft";
            },
          },
          suggestedMin: hasData ? stats.min - 50 : 0,
          suggestedMax: hasData ? stats.max + 50 : 2000, // Reasonable default for empty chart axis
        },
      },
    },
    plugins: [
      noDataPlugin,
      {
        // Custom plugin: draw min/max reference lines
        id: "refLines",
        afterDraw(chart) {
          if (!hasData) return;
          
          const {
            ctx,
            chartArea: { left, right },
            scales: { y },
          } = chart;

          // Min line
          const minY = y.getPixelForValue(stats.min);
          ctx.save();
          ctx.beginPath();
          ctx.setLineDash([6, 4]);
          ctx.strokeStyle = "#16a34a";
          ctx.lineWidth = 1.5;
          ctx.moveTo(left, minY);
          ctx.lineTo(right, minY);
          ctx.stroke();

          // Min label
          ctx.fillStyle = "#16a34a";
          ctx.font = "bold 10px sans-serif";
          ctx.textAlign = "right";
          ctx.fillText(
            `${t.min}: ${stats.min.toLocaleString(getLocale())} Ft`,
            right - 4,
            minY - 5
          );

          // Max line
          const maxY = y.getPixelForValue(stats.max);
          ctx.beginPath();
          ctx.strokeStyle = "#dc2626";
          ctx.moveTo(left, maxY);
          ctx.lineTo(right, maxY);
          ctx.stroke();

          // Max label
          ctx.fillStyle = "#dc2626";
          ctx.fillText(
            `${t.max}: ${stats.max.toLocaleString(getLocale())} Ft`,
            right - 4,
            maxY - 5
          );

          ctx.restore();
        },
      },
    ],
  });

  // expose instance on the canvas for extra safety/debugging
  try { canvas._tptChart = g_chartInstance; } catch (e) { /* ignore */ }
}

// ── Remove Tracker ───────────────────────────

function removePriceTracker() {
  // Destroy chart instance if present to avoid orphaned canvases
  try {
    if (g_chartInstance && typeof g_chartInstance.destroy === 'function') {
      g_chartInstance.destroy();
      g_chartInstance = null;
    }
  } catch (err) {
    console.warn('Failed to destroy chart instance during removal:', err);
  }

  const container = document.getElementById(CONTAINER_ID);
  if (container) container.remove();
}

// ── Message Listener ─────────────────────────

let g_isEnabled = false;
let g_observer = null;
let g_isInjecting = false;
// Keep reference to the Chart.js instance so we can destroy/recreate it reliably
let g_chartInstance = null;

browser.runtime.onMessage.addListener((message) => {
  if (message.type === "SET_ENABLED") {
    g_isEnabled = message.enabled;
    if (g_isEnabled) {
      injectPriceTracker();
      startObserver();
    } else {
      removePriceTracker();
      stopObserver();
    }
  }
});

// ── DOM Observer for SPA / Dynamic Loading ───

let g_debounceTimer = null;

function startObserver() {
  if (g_observer) return;

  g_observer = new MutationObserver(() => {
    if (!g_isEnabled) return;

    const container = document.getElementById(CONTAINER_ID);

    // If container is missing → try to inject
    if (!container) {
      if (g_isInjecting) return; // Already working on it
      if (g_debounceTimer) clearTimeout(g_debounceTimer);
      g_debounceTimer = setTimeout(() => {
        injectPriceTracker();
      }, 200);
      return;
    }

    // If we are currently injecting (loading data), don't treat the partial container as stale
    if (g_isInjecting) return;

    // If container exists but the chart instance is missing, try to re-render or re-inject
    const canvas = container.querySelector('canvas');
    const chartWrapper = container.querySelector('.tpt-chart-wrapper');
    const isLoading = chartWrapper && chartWrapper.classList.contains('tpt-loading');

    if (isLoading) return; // Still waiting for data, not an error

    const canvasMissingChart = !canvas || !(canvas._tptChart || g_chartInstance);
    // Removed canvasCollapsed check as it causes false-positives during SPA layout shifts
    
    // Check if the TPNC matches the URL (robustness)
    const tpnc = getTpncFromUrl();
    const tpncChanged = tpnc && container.dataset.tpnc !== tpnc;

    if (canvasMissingChart || tpncChanged) {
      if (g_debounceTimer) clearTimeout(g_debounceTimer);
      g_debounceTimer = setTimeout(() => {
        if (g_isInjecting) return;
        
        container.remove();
        injectPriceTracker();
      }, 200);
    }
  });

  g_observer.observe(document.body, {
    childList: true,
    subtree: true,
  });
}

function stopObserver() {
  if (g_observer) {
    g_observer.disconnect();
    g_observer = null;
  }
}

// ── Init — check stored state on page load ───

browser.storage.local.get("extensionEnabled").then((result) => {
  g_isEnabled = result.extensionEnabled ?? true;

  if (g_isEnabled) {
    injectPriceTracker();
    startObserver();
  }
});

// ── URL Change Detection (SPA) ───

let lastTpnc = getTpncFromUrl();

// Use 'setInterval' as a lightweight polling fall-back for URL changes
setInterval(() => {
  const currentTpnc = getTpncFromUrl();
  if (currentTpnc !== lastTpnc) {
    lastTpnc = currentTpnc;
    
    // Only remove and re-inject if the product ID actually changed.
    // If we just navigated to a different section of the same product, keep it.
    const oldContainer = document.getElementById(CONTAINER_ID);
    if (oldContainer) {
       // If the ID changed, we must replace the tracker
       if (currentTpnc) {
          oldContainer.remove();
       }
    }

    if (g_isEnabled && currentTpnc) {
      // Give React/Angular a moment to render the new page content
      setTimeout(() => injectPriceTracker().catch(console.error), 500); 
    }
  }
}, 500);
