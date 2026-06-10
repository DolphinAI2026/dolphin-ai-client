const fs = require('fs');
const path = require('path');
const { resolve } = require('./lib/codeServerResolver');

const args = process.argv.slice(2);
let explicitPath = null;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--code-server-path' && args[i + 1]) {
    explicitPath = args[i + 1];
    i++;
  }
}

const codeServerInfo = resolve(explicitPath);
const productJsonPath = codeServerInfo.productJsonPath;
const workbenchPath = codeServerInfo.workbenchPath;
const workspacesRootCandidates = [
  path.resolve(__dirname, '..', 'workspaces'),
  path.join(process.env.HOME || '', '.apaas-builder-ai', 'workspaces'),
].filter(Boolean);

const brandName = '睿鲸AI Coding';
const brandSubtitle = '得帆低代码二次开发的 Vibe Coding 工具';
const welcomeCardTitle = '快速开始';
const welcomeHeroTitle = '睿鲸AI Coding 工作台';
const welcomeHeroParagraphOne = '面向得帆低代码二次开发场景的 AI Coding 工作台。';
const welcomeHeroParagraphTwo =
  '在当前工作区中让 AI 阅读代码、生成组件、修改页面，并串联调试与发布流程完成开发。';
const welcomeHeroCta = '立即开始';
const walkthroughTitle = '睿鲸AI Coding 快速上手';
const walkthroughDescription = '从当前工作区开始，让 AI 阅读、修改并生成代码。';
const fundamentalsTitle = '低代码开发说明';

function humanizeProjectName(projectName, projectType) {
  if (!projectName) {
    return '';
  }

  const suffixMap = {
    'form-component': '组件',
    'form-page': '页面',
    'mobile-page': '移动端页面',
    'form-view': '列表视图',
    'frontend-plugin': '前端插件',
    'page-layout': '布局',
    'app-layout': '布局',
  };

  const cleaned = projectName
    .replace(/^(form-component|form-page|mobile-page|form-view|frontend-plugin|page-layout|app-layout)-/, '')
    .replace(/[-_]+/g, ' ')
    .trim();

  if (!cleaned) {
    return projectName;
  }

  const titled = cleaned.replace(/\b([a-z])/g, (_, ch) => ch.toUpperCase());
  const suffix = suffixMap[projectType] || '';
  return suffix && !titled.endsWith(suffix) ? `${titled} ${suffix}` : titled;
}

function loadWorkspaceDisplayMap() {
  const displayMap = {};
  const workspacesRoot = workspacesRootCandidates.find((candidate) => fs.existsSync(candidate));
  if (!workspacesRoot) {
    return displayMap;
  }
  const dirs = fs.readdirSync(workspacesRoot, { withFileTypes: true }).filter((entry) => entry.isDirectory());

  for (const dir of dirs) {
    const metaPath = path.join(workspacesRoot, dir.name, '.workspace.json');
    if (!fs.existsSync(metaPath)) {
      continue;
    }

    try {
      const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
      const label =
        meta.display_name ||
        humanizeProjectName(meta.project_name, meta.project_type) ||
        meta.project_name ||
        meta.id ||
        dir.name;

      if (meta.id) {
        displayMap[meta.id] = label;
      }
      if (dir.name && !displayMap[dir.name]) {
        displayMap[dir.name] = label;
      }
    } catch (error) {
      console.warn(`Skip invalid workspace metadata: ${metaPath}`, error.message);
    }
  }

  return displayMap;
}

const workspaceDisplayMap = loadWorkspaceDisplayMap();

const brandingPatch = `
;(() => {
  if (globalThis.__RUIJING_BRANDING_PATCH__) return;
  globalThis.__RUIJING_BRANDING_PATCH__ = true;

  const brandName = ${JSON.stringify(brandName)};
  const brandSubtitle = ${JSON.stringify(brandSubtitle)};
  const rightTitle = ${JSON.stringify(welcomeCardTitle)};
  const heroTitle = ${JSON.stringify(welcomeHeroTitle)};
  const heroParagraphOne = ${JSON.stringify(welcomeHeroParagraphOne)};
  const heroParagraphTwo = ${JSON.stringify(welcomeHeroParagraphTwo)};
  const heroCta = ${JSON.stringify(welcomeHeroCta)};
  const guideTitle = ${JSON.stringify(walkthroughTitle)};
  const guideDescription = ${JSON.stringify(walkthroughDescription)};
  const fundamentalsTitle = ${JSON.stringify(fundamentalsTitle)};
  const workspaceMap = ${JSON.stringify(workspaceDisplayMap)};
  const welcomeCss = ${JSON.stringify(`
    .gettingStartedContainer.ruijing-welcome {
      width: 100% !important;
      max-width: none !important;
      padding: 0 !important;
      background:
        radial-gradient(circle at top left, rgba(88, 103, 242, 0.18), transparent 28%),
        radial-gradient(circle at 85% 18%, rgba(73, 196, 255, 0.10), transparent 24%),
        linear-gradient(180deg, rgba(18, 19, 23, 0.96), rgba(16, 17, 20, 0.98));
    }

    .gettingStartedContainer.ruijing-welcome .gettingStarted {
      padding: 28px 0 20px;
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedSlideCategories {
      overflow: visible !important;
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedCategoriesContainer {
      max-width: 1160px;
      margin: 0 auto;
      display: flex !important;
      flex-wrap: wrap;
      align-items: start;
      gap: 24px 28px;
      padding: 0 28px 8px;
    }

    .gettingStartedContainer.ruijing-welcome .header {
      flex: 1 1 100%;
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 0;
      padding: 12px 4px 4px;
    }

    .gettingStartedContainer.ruijing-welcome .header::before {
      content: 'aPaaS Builder · Vibe IDE';
      display: inline-flex;
      align-items: center;
      width: fit-content;
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 12px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: rgba(196, 205, 255, 0.88);
      background: rgba(82, 97, 224, 0.14);
      border: 1px solid rgba(111, 131, 255, 0.28);
    }

    .gettingStartedContainer.ruijing-welcome .header .product-name {
      margin: 0 !important;
      font-size: 44px !important;
      line-height: 1.02 !important;
      font-weight: 700 !important;
      letter-spacing: -0.04em;
      color: #f5f7fb !important;
    }

    .gettingStartedContainer.ruijing-welcome .header .subtitle {
      margin: 0 !important;
      max-width: 580px;
      font-size: 17px !important;
      line-height: 1.65 !important;
      color: rgba(204, 211, 224, 0.86) !important;
    }

    .gettingStartedContainer.ruijing-welcome .ruijing-workspace-pill {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      width: fit-content;
      margin-top: 8px;
      padding: 10px 14px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: rgba(226, 231, 239, 0.9);
      font-size: 13px;
    }

    .gettingStartedContainer.ruijing-welcome .ruijing-workspace-pill strong {
      color: #ffffff;
      font-weight: 600;
    }

    .gettingStartedContainer.ruijing-welcome .categories-column-left,
    .gettingStartedContainer.ruijing-welcome .categories-column-right {
      min-width: 0;
      display: flex !important;
      flex-direction: column;
      gap: 24px;
      align-self: stretch;
    }

    .gettingStartedContainer.ruijing-welcome .categories-column-left {
      flex: 1 1 460px;
    }

    .gettingStartedContainer.ruijing-welcome .categories-column-right {
      flex: 0 1 420px;
      min-width: 360px;
    }

    .gettingStartedContainer.ruijing-welcome .index-list.start-container {
      display: none !important;
    }

    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened {
      width: 100%;
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedCategory {
      position: relative;
      overflow: hidden;
      width: 100%;
      padding: 22px;
      border-radius: 24px;
      background:
        linear-gradient(135deg, rgba(95, 105, 255, 0.22), rgba(103, 77, 219, 0.08)),
        rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(112, 122, 255, 0.18);
      box-shadow: 0 18px 50px rgba(0, 0, 0, 0.28);
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedCategory::after {
      content: '';
      position: absolute;
      inset: auto -40px -60px auto;
      width: 180px;
      height: 180px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(148, 167, 255, 0.28), transparent 68%);
      pointer-events: none;
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedCategory > h2,
    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened > h2,
    .gettingStartedContainer.ruijing-welcome .index-list.getting-started > h2 {
      margin: 0 0 16px !important;
      font-size: 13px !important;
      font-weight: 600 !important;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: rgba(161, 172, 196, 0.82) !important;
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedCategory > a {
      display: block;
      text-decoration: none;
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedCategory > a > button {
      width: 100%;
      min-height: 330px;
      padding: 26px 26px 22px !important;
      border: none !important;
      border-radius: 20px !important;
      background:
        linear-gradient(140deg, rgba(111, 84, 247, 0.95), rgba(81, 114, 249, 0.88)) !important;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 10px;
      text-align: left;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.18);
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedCategory > a > button h3 {
      margin: 0 !important;
      font-size: 32px !important;
      line-height: 1.08 !important;
      letter-spacing: -0.03em;
      color: #ffffff !important;
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedCategory > a > button p {
      margin: 0 !important;
      max-width: 430px;
      font-size: 14px !important;
      line-height: 1.7 !important;
      color: rgba(243, 245, 255, 0.92) !important;
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedCategory > a > button p:last-of-type {
      margin-top: auto !important;
      padding-top: 14px;
      font-weight: 600;
      letter-spacing: 0.01em;
    }

    .gettingStartedContainer.ruijing-welcome .gettingStartedCategory > a > button img {
      margin: auto -10px -42px auto !important;
      width: 72%;
      opacity: 0.82;
      filter: saturate(0.88) brightness(1.05);
    }

    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened,
    .gettingStartedContainer.ruijing-welcome .index-list.getting-started {
      width: 100%;
      padding: 22px;
      border-radius: 22px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.07);
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
    }

    .gettingStartedContainer.ruijing-welcome .index-list.getting-started {
      margin-top: auto;
    }

    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened ul,
    .gettingStartedContainer.ruijing-welcome .index-list.getting-started ul {
      display: grid;
      gap: 12px;
      padding: 0;
      margin: 0;
    }

    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened li,
    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened a,
    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened button {
      list-style: none;
    }

    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened a,
    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened button {
      display: flex !important;
      flex-direction: column;
      align-items: flex-start;
      gap: 4px;
      width: 100%;
      min-height: 58px;
      padding: 14px 16px !important;
      border-radius: 16px;
      text-decoration: none !important;
      background: rgba(255, 255, 255, 0.025);
      border: 1px solid rgba(255, 255, 255, 0.04);
      color: #d7def0 !important;
      transition: background 120ms ease, border-color 120ms ease;
    }

    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened a:hover,
    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened button:hover {
      background: rgba(103, 119, 255, 0.08);
      border-color: rgba(103, 119, 255, 0.26);
    }

    .gettingStartedContainer.ruijing-welcome .ruijing-recent-title {
      display: block;
      font-size: 15px;
      font-weight: 600;
      line-height: 1.45;
      color: #f2f5ff;
    }

    .gettingStartedContainer.ruijing-welcome .ruijing-recent-path {
      display: block;
      width: 100%;
      font-size: 12px;
      line-height: 1.45;
      color: rgba(167, 178, 197, 0.78);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened .empty-recent {
      padding: 16px;
      border-radius: 16px;
      border: 1px dashed rgba(255, 255, 255, 0.12);
      background: rgba(255, 255, 255, 0.02);
      color: rgba(176, 184, 198, 0.82);
      line-height: 1.7;
    }

    .gettingStartedContainer.ruijing-welcome .index-list.recently-opened .empty-recent .button-link {
      color: #8db6ff !important;
    }

    .gettingStartedContainer.ruijing-welcome .getting-started-category {
      padding: 18px 18px 16px !important;
      border-radius: 18px !important;
      background: rgba(255, 255, 255, 0.025) !important;
      border: 1px solid rgba(255, 255, 255, 0.05) !important;
      text-align: left;
      box-shadow: none !important;
    }

    .gettingStartedContainer.ruijing-welcome .getting-started-category .main-content {
      gap: 8px;
      align-items: flex-start;
    }

    .gettingStartedContainer.ruijing-welcome .getting-started-category .icon-widget,
    .gettingStartedContainer.ruijing-welcome .featured-badge,
    .gettingStartedContainer.ruijing-welcome .category-progress,
    .gettingStartedContainer.ruijing-welcome .see-all-walkthroughs,
    .gettingStartedContainer.ruijing-welcome .hide-category-button {
      display: none !important;
    }

    .gettingStartedContainer.ruijing-welcome .getting-started-category .category-title {
      margin: 0 0 8px !important;
      font-size: 16px !important;
      font-weight: 600 !important;
      color: #edf2ff !important;
    }

    .gettingStartedContainer.ruijing-welcome .getting-started-category .description-content {
      color: rgba(176, 186, 205, 0.82) !important;
      line-height: 1.7;
      min-height: 0 !important;
    }

    .gettingStartedContainer.ruijing-welcome .footer {
      flex: 1 1 100%;
      margin: 4px 0 0;
      padding: 0 4px;
    }

    .gettingStartedContainer.ruijing-welcome .footer .showOnStartup {
      display: flex;
      align-items: center;
      gap: 10px;
      color: rgba(180, 188, 201, 0.82);
    }

    @media (max-width: 1080px) {
      .gettingStartedContainer.ruijing-welcome .gettingStartedCategoriesContainer {
        padding: 0 20px 12px;
      }

      .gettingStartedContainer.ruijing-welcome .header .product-name {
        font-size: 38px !important;
      }

      .gettingStartedContainer.ruijing-welcome .categories-column-left,
      .gettingStartedContainer.ruijing-welcome .categories-column-right {
        flex-basis: 100%;
        min-width: 0;
      }

      .gettingStartedContainer.ruijing-welcome .gettingStartedCategory > a > button {
        min-height: 280px;
      }
    }

    @media (max-width: 720px) {
      .gettingStartedContainer.ruijing-welcome .header .product-name {
        font-size: 32px !important;
      }

      .gettingStartedContainer.ruijing-welcome .header .subtitle {
        font-size: 15px !important;
      }

      .gettingStartedContainer.ruijing-welcome .gettingStartedCategory > a > button h3 {
        font-size: 26px !important;
      }
    }
  `)};

  function ensureStyle() {
    let style = document.getElementById('ruijing-welcome-style');
    if (!style) {
      style = document.createElement('style');
      style.id = 'ruijing-welcome-style';
      document.head.appendChild(style);
    }
    if (style.textContent !== welcomeCss) {
      style.textContent = welcomeCss;
    }
  }

  function getWorkspaceId() {
    const params = new URLSearchParams(location.search);
    const folder = params.get('folder') || '';
    const workspace = params.get('workspace') || '';
    const sources = [folder, workspace];

    for (const value of sources) {
      const match = decodeURIComponent(value).match(/\\/workspaces\\/([^/]+)/);
      if (match) return match[1];
    }
    return '';
  }

  function extractWorkspaceIdFromText(text) {
    const match = (text || '').trim().match(/\\b\\d+_[a-z0-9]+\\b/i);
    return match ? match[0] : '';
  }

  function escapeRegExp(value) {
    return String(value).replace(/[|\\\\{}()[\\]^$+*?.]/g, '\\\\$&');
  }

  function ensureWorkspacePill(header) {
    if (!header) return;
    const workspaceId = getWorkspaceId();
    const displayName = workspaceMap[workspaceId];
    if (!displayName) return;

    let pill = header.querySelector('.ruijing-workspace-pill');
    if (!pill) {
      pill = document.createElement('div');
      pill.className = 'ruijing-workspace-pill';
      header.appendChild(pill);
    }
    pill.innerHTML = '<span>当前工作区</span><strong>' + displayName + '</strong>';
  }

  function decorateRecentEntries(container) {
    if (!container) return;
    const heading = container.querySelector('h2');
    if (heading) heading.textContent = '最近工作区';

    const empty = container.querySelector('.empty-recent');
    if (empty) {
      empty.childNodes.forEach((node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          node.textContent = node.textContent.replace('你没有最近使用的文件夹', '当前还没有最近工作区');
        }
      });
      return;
    }

    for (const item of container.querySelectorAll('li')) {
      const entry = item.querySelector('button,a,[role="link"]');
      if (!entry) continue;

      const detail = Array.from(item.children).find((child) => child !== entry);
      const fullText = [entry.textContent, entry.getAttribute('aria-label'), entry.title, detail && detail.textContent]
        .filter(Boolean)
        .join(' ')
        .replace(/\\s+/g, ' ')
        .trim();
      const workspaceId = extractWorkspaceIdFromText(fullText);
      const displayName = workspaceMap[workspaceId];

      if (!workspaceId || !displayName || entry.dataset.ruijingRecentDecorated === '1') {
        continue;
      }

      entry.dataset.ruijingRecentDecorated = '1';
      entry.title = displayName + ' (' + workspaceId + ')';
      if (entry.getAttribute('aria-label')) {
        entry.setAttribute('aria-label', entry.getAttribute('aria-label').replace(workspaceId, displayName));
      }
      entry.textContent = displayName;

      if (detail) {
        detail.classList.add('ruijing-recent-path');
        const detailText = (detail.textContent || '').trim();
        detail.textContent = detailText.replace(new RegExp('/?' + escapeRegExp(workspaceId) + '$'), '');
      }
    }
  }

  function decorateHero(root) {
    const heading = root.querySelector('.gettingStartedCategory > h2');
    if (heading) heading.textContent = '工作台概览';

    const anchor = root.querySelector('.gettingStartedCategory > a');
    const button = anchor && anchor.querySelector('button');
    if (!button) return;

    const title = button.querySelector('h3');
    const paragraphs = button.querySelectorAll('p');
    if (title) title.textContent = heroTitle;
    if (paragraphs[0]) paragraphs[0].textContent = heroParagraphOne;
    if (paragraphs[1]) paragraphs[1].textContent = heroParagraphTwo;
    if (paragraphs[2] && paragraphs[2].childNodes.length) {
      paragraphs[2].childNodes[0].textContent = heroCta + ' ';
    }

    if (anchor) {
      anchor.removeAttribute('href');
      anchor.removeAttribute('target');
      anchor.style.pointerEvents = 'none';
      anchor.style.cursor = 'default';
    }

    button.disabled = true;
    button.style.cursor = 'default';
  }

  function decorateGuides(root) {
    const guide = root.querySelector('.index-list.getting-started');
    if (!guide) return;

    const heading = guide.querySelector('h2');
    if (heading) heading.textContent = '开发指南';

    const cards = guide.querySelectorAll('.getting-started-category');
    if (cards[0]) {
      const title = cards[0].querySelector('.category-title');
      const desc = cards[0].querySelector('.description-content');
      if (title) title.textContent = guideTitle;
      if (desc) desc.textContent = guideDescription;
    }

    if (cards[1]) {
      const title = cards[1].querySelector('.category-title');
      const desc = cards[1].querySelector('.description-content');
      if (title) title.textContent = fundamentalsTitle;
      if (desc) desc.textContent = '优先参考工作区里的 SDK 文档、页面指南和规则说明，再让 AI 生成或修改代码。';
    }

    const more = guide.querySelector('.see-all-walkthroughs');
    if (more) more.style.display = 'none';
  }

  function decorateWelcome() {
    const root = document.querySelector('.gettingStartedContainer');
    if (!root) return false;

    ensureStyle();
    root.classList.add('ruijing-welcome');
    document.title = document.title.replace(/code-server/g, brandName);

    const header = root.querySelector('.header');
    const product = header && header.querySelector('.product-name');
    const subtitle = header && header.querySelector('.subtitle');

    if (product) product.textContent = brandName;
    if (subtitle) subtitle.textContent = brandSubtitle;
    ensureWorkspacePill(header);

    const start = root.querySelector('.index-list.start-container');
    if (start) start.style.display = 'none';

    decorateRecentEntries(root.querySelector('.index-list.recently-opened'));
    decorateHero(root);
    decorateGuides(root);

    return true;
  }

  const maxAttempts = 240;
  let attempts = 0;
  let decorated = false;
  let scheduled = false;

  function stopWatching() {
    decorated = true;
    clearInterval(timer);
    observer.disconnect();
  }

  function runDecorate() {
    scheduled = false;
    if (decorated) return;
    if (decorateWelcome()) {
      stopWatching();
    }
  }

  function scheduleDecorate() {
    if (decorated || scheduled) return;
    scheduled = true;
    setTimeout(runDecorate, 100);
  }

  const observer = new MutationObserver(scheduleDecorate);

  if (document.documentElement) {
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  const timer = setInterval(() => {
    attempts += 1;
    scheduleDecorate();
    if (attempts >= maxAttempts) stopWatching();
  }, 500);

  scheduleDecorate();
})();
`;

function patchProductJson() {
  const product = JSON.parse(fs.readFileSync(productJsonPath, 'utf8'));
  product.nameShort = brandName;
  product.nameLong = brandName;
  product.defaultChatAgent = {
    extensionId: 'apaas-builder.ruijing-ai',
    chatExtensionId: 'apaas-builder.ruijing-ai',
    chatExtensionOutputId: '',
    chatExtensionOutputExtensionStateCommand: '',
    documentationUrl: '',
    termsStatementUrl: '',
    privacyStatementUrl: '',
    skusDocumentationUrl: '',
    publicCodeMatchesUrl: '',
    entitlementSignupLimitedUrl: '',
    provider: {
      default: {
        id: 'ruijing-ai.chat',
        name: '睿鲸AI',
      },
      enterprise: {
        id: '',
        name: '',
      },
      apple: {
        id: '',
        name: '',
      },
      google: {
        id: '',
        name: '',
      },
    },
    providerUriSetting: '',
  };
  fs.writeFileSync(productJsonPath, `${JSON.stringify(product, null, 2)}\n`);
}

function patchWorkbench() {
  const source = fs.readFileSync(workbenchPath, 'utf8');
  const sourceMapMarker = '\n//# sourceMappingURL=workbench.js.map';
  const sourceMapIdx = source.lastIndexOf(sourceMapMarker);
  const patchStartMarkers = [
    ';(()=>{if(globalThis.__RUIJING_BRANDING_PATCH__)return;',
    ';(() => {\n  if (globalThis.__RUIJING_BRANDING_PATCH__) return;',
  ];

  const insertIdx = sourceMapIdx >= 0 ? sourceMapIdx : source.length;

  fs.copyFileSync(workbenchPath, `${workbenchPath}.bak-branding-20260327`);
  const patchStart = patchStartMarkers
    .map((marker) => source.indexOf(marker))
    .filter((index) => index >= 0)
    .sort((a, b) => a - b)[0] ?? -1;
  const updated =
    patchStart >= 0 && patchStart < insertIdx
      ? `${source.slice(0, patchStart)}\n${brandingPatch}\n${source.slice(insertIdx)}`
      : `${source.slice(0, insertIdx)}\n${brandingPatch}\n${source.slice(insertIdx)}`;
  fs.writeFileSync(workbenchPath, updated);
  return patchStart >= 0 ? 'replaced' : 'patched';
}

function main() {
  console.log(`Auto-detected code-server ${codeServerInfo.version}: ${workbenchPath}`);
  patchProductJson();
  const state = patchWorkbench();
  console.log(`Branding ${state}.`);
}

main();
