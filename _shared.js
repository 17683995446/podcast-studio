/**
 * Shared JavaScript utilities for Podcast Studio.
 *
 * This file is loaded by all HTML pages and provides:
 *   - escapeHtml()      — XSS prevention for dynamic content
 *   - fetchWithTimeout() — fetch with AbortController timeout
 *   - showError()       — unified error display
 *   - showLoading()     — unified loading state
 *   - renderNavbar()    — dynamic navbar injection (single source of truth)
 *
 * Usage in HTML:
 *   <script src="/_shared.js"></script>
 *   <script>
 *     const data = await fetchWithTimeout('/api/health');
 *     document.getElementById('content').innerHTML = escapeHtml(data.status);
 *   </script>
 */

/**
 * Escape HTML special characters to prevent XSS.
 * @param {string|null|undefined} str - The string to escape.
 * @returns {string} Escaped string safe for innerHTML.
 */
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Fetch JSON with timeout via AbortController.
 * @param {string} url - The URL to fetch.
 * @param {object} options - Fetch options (method, headers, body, etc.).
 * @param {number} timeout - Timeout in milliseconds (default 15000).
 * @returns {Promise<object>} Parsed JSON response.
 * @throws {Error} On network error or timeout.
 */
async function fetchWithTimeout(url, options = {}, timeout = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Show an error message in a container element.
 * @param {HTMLElement} container - The element to show the error in.
 * @param {string|Error} error - The error message or Error object.
 * @param {string} [retryFn] - Optional function name to call for retry.
 */
function showError(container, error, retryFn) {
  if (!container) return;
  const msg = error instanceof Error ? error.message : String(error);
  const safeMsg = escapeHtml(msg);
  let html = '<p style="color: var(--accent);">' + safeMsg + '</p>';
  if (retryFn) {
    html += '<button class="btn btn-secondary" onclick="' + escapeHtml(retryFn) + '()">重试</button>';
  }
  container.innerHTML = html;
}

/**
 * Show a loading state in a container element.
 * @param {HTMLElement} container - The element to show the loading state in.
 * @param {string} [message] - Loading message (default "加载中...").
 */
function showLoading(container, message) {
  if (!container) return;
  const msg = message || '加载中...';
  container.innerHTML = '<span class="spinner"></span> <span>' + escapeHtml(msg) + '</span>';
}

/**
 * Podcast Studio navigation links configuration.
 * Single source of truth — adding a new page only requires
 * adding an entry here.
 */
const NAV_LINKS = [
  { href: '/', label: '首页', key: 'home' },
  { href: '/studio.html', label: '工作室', key: 'studio' },
  { href: '/library.html', label: '播客库', key: 'library' },
  { href: '/player.html', label: '播放器', key: 'player' },
  { href: '/docs.html', label: '文档', key: 'docs' },
];

/**
 * Render the navbar into a placeholder element.
 * @param {string} activeKey - The key of the active nav link.
 */
function renderNavbar(activeKey) {
  const placeholder = document.getElementById('nav-placeholder');
  if (!placeholder) return;
  let html = '<nav class="navbar"><span class="brand">🎙 Podcast Studio</span><div class="nav-links">';
  for (const link of NAV_LINKS) {
    const cls = link.key === activeKey ? ' class="active"' : '';
    html += '<a href="' + link.href + '"' + cls + '>' + escapeHtml(link.label) + '</a>';
  }
  html += '</div></nav>';
  placeholder.innerHTML = html;
}

/**
 * Format an ISO timestamp into a user-friendly Chinese date string.
 * @param {string} isoStr - ISO 8601 timestamp (e.g. "2026-07-03T14:15:43").
 * @returns {string} Formatted date (e.g. "2026年7月3日 14:15").
 */
function formatDate(isoStr) {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.getFullYear() + '年' + (d.getMonth() + 1) + '月' + d.getDate() + '日 ' +
           String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  } catch(e) {
    return isoStr;
  }
}

/**
 * Render the footer.
 */
function renderFooter() {
  const placeholder = document.getElementById('footer-placeholder');
  if (!placeholder) return;
  placeholder.innerHTML = '<footer style="text-align:center;padding:20px;color:var(--muted);font-size:0.85rem;">Podcast Studio — 增强版播客生成流水线</footer>';
}

/**
 * Error code → localized Chinese message mapping.
 * Frontend uses this instead of matching English error strings.
 */
const ERROR_MESSAGES = {
  'PIPELINE_UNAVAILABLE': '语音合成管道源不可用，无法获取引擎列表',
  'NO_FILE_UPLOADED': '请选择要上传的文件',
  'EMPTY_FILENAME': '文件名为空',
  'UNSUPPORTED_FORMAT': '不支持的文件格式',
  'FILENAME_TOO_LONG': '文件名过长',
  'INVALID_JOB_ID': '无效的任务 ID',
  'JOB_NOT_FOUND': '任务不存在',
  'INVALID_SESSION_ID': '无效的会话 ID',
  'SESSION_NOT_FOUND': '会话不存在',
  'RSS_NOT_FOUND': 'RSS Feed 不存在',
  'INVALID_FILENAME': '无效的文件名',
  'FILE_NOT_FOUND': '文件不存在',
  'RATE_LIMITED': '请求过于频繁，请稍后再试',
};

/**
 * Get a localized error message from an API error response.
 * @param {object} data - The parsed JSON error response.
 * @returns {string} Localized error message.
 */
function getErrorMessage(data) {
  if (!data) return '未知错误';
  if (data.error_code && ERROR_MESSAGES[data.error_code]) {
    return ERROR_MESSAGES[data.error_code];
  }
  return data.error || '未知错误';
}

/**
 * Assert that a value is an array. Returns the array or an empty fallback.
 * @param {*} value - The value to check.
 * @param {string} [context] - Context string for console warning.
 * @returns {Array} The array if valid, else empty array.
 */
function assertArray(value, context) {
  if (Array.isArray(value)) return value;
  if (context) console.warn(`Expected array for ${context}, got:`, typeof value);
  return [];
}

/**
 * Assert that a value is an object (not null, not array). Returns the object or fallback.
 * @param {*} value - The value to check.
 * @param {object} [fallback={}] - Fallback value.
 * @param {string} [context] - Context string for console warning.
 * @returns {object} The object if valid, else fallback.
 */
function assertObject(value, fallback, context) {
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    return value;
  }
  if (context) console.warn(`Expected object for ${context}, got:`, typeof value);
  return fallback || {};
}
