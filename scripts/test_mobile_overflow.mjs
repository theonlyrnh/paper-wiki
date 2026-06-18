import { chromium } from 'playwright';

const BASE_URL = process.env.PW_BASE_URL || 'http://127.0.0.1:19828/';
const WIDTHS = (process.env.PW_WIDTHS || '375,390,414')
  .split(',')
  .map((w) => Number.parseInt(w.trim(), 10))
  .filter(Boolean);

const longTitle =
  'An Extremely Long Paper Title About Retrieval-Augmented Knowledge Graph Construction With AContinuousUnbrokenIdentifierThatPreviouslyExpandedCardsBeyondTheMobileViewportAndHidRightSideContent';
const longFile =
  'this-is-a-very-long-file-name-with-a-continuous-unbroken-segment-that-should-never-expand-the-card-or-create-horizontal-scroll-on-mobile-devices-2026-final-version.pdf';

function makePapers(count = 6) {
  return Array.from({ length: count }, (_, i) => ({
    id: `paper-${i + 1}`,
    title: `${longTitle} ${i + 1}`,
    filename: `${i + 1}-${longFile}`,
    authors: `A Very Long Author Name ${i + 1}, Another Long Author Name, Third Contributor With Long Institution`,
    year: 2026,
    tags: [],
    status: i % 4 === 0 ? 'parsing' : i % 4 === 1 ? 'done' : i % 4 === 2 ? 'failed' : 'pending',
    created_at: `2026-06-${String(16 - i).padStart(2, '0')} 12:00:00`,
    updated_at: `2026-06-${String(16 - i).padStart(2, '0')} 12:00:00`,
  }));
}

async function installApiMocks(page) {
  const papers = makePapers(6);
  await page.route('**/api/auth/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 1, username: 'mobile-test', nickname: 'Mobile Test', role: 'admin', can_invite: true }),
    }),
  );
  await page.route('**/api/stats', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ paper_count: papers.length, wiki_page_count: 2, graph_node_count: 3, graph_edge_count: 4, ingest_queue_size: 0 }),
    }),
  );
  await page.route('**/api/storage/quota', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ used_mb: 128, quota_mb: 1000, usage_percent: 12.8, can_upload: true }),
    }),
  );
  await page.route('**/api/papers?**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(papers),
    }),
  );
  await page.route('**/api/graph/insights', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ surprising_connections: [], hubs: [], knowledge_gaps: [] }),
    }),
  );
  await page.route('**/api/ingest/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [] }),
    }),
  );
}

function assert(condition, message, details = undefined) {
  if (!condition) {
    const suffix = details ? `\n${JSON.stringify(details, null, 2)}` : '';
    throw new Error(`${message}${suffix}`);
  }
}

async function assertNoHorizontalOverflow(page, label, width) {
  const metrics = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const offenders = Array.from(document.querySelectorAll('body *'))
      .map((el) => {
        const rect = el.getBoundingClientRect();
        return {
          tag: el.tagName.toLowerCase(),
          id: el.id,
          className: typeof el.className === 'string' ? el.className : '',
          left: Math.round(rect.left * 100) / 100,
          right: Math.round(rect.right * 100) / 100,
          width: Math.round(rect.width * 100) / 100,
        };
      })
      .filter((r) => r.width > 0 && r.right > viewportWidth + 1)
      .slice(0, 8);

    return {
      viewportWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      offenders,
    };
  });

  const scrollWidth = Math.max(metrics.documentScrollWidth, metrics.bodyScrollWidth);
  assert(
    scrollWidth <= metrics.viewportWidth + 1 && metrics.offenders.length === 0,
    `${label} 在 ${width}px 下出现横向溢出`,
    metrics,
  );
}

async function assertMobileContainersCanShrink(page, selector, label) {
  const info = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return {
      selector: sel,
      minWidth: style.minWidth,
      width: rect.width,
      viewportWidth: document.documentElement.clientWidth,
    };
  }, selector);
  assert(info, `${label} 容器不存在: ${selector}`);
  assert(info.minWidth === '0px', `${label} 容器必须允许收缩（min-width: 0）`, info);
  assert(info.width <= info.viewportWidth + 1, `${label} 容器宽度不能超过视口`, info);
}

async function assertTwoLineClamp(page, selector, label) {
  const titleInfos = await page.$$eval(selector, (nodes) =>
    nodes.map((node) => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      const lineHeight = Number.parseFloat(style.lineHeight);
      return {
        text: node.textContent.trim().slice(0, 80),
        className: node.className,
        height: rect.height,
        lineHeight,
        maxHeight: lineHeight * 2.45,
        overflowWrap: style.overflowWrap,
      };
    }),
  );
  assert(titleInfos.length > 0, `${label} 未找到标题节点: ${selector}`);
  for (const info of titleInfos) {
    assert(info.height <= info.maxHeight, `${label} 标题未限制在两行内`, info);
  }
}

async function assertSingleLineMeta(page, selector, label) {
  const metaInfos = await page.$$eval(selector, (nodes) =>
    nodes.map((node) => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      const lineHeight = Number.parseFloat(style.lineHeight);
      return {
        text: node.textContent.trim().slice(0, 80),
        className: node.className,
        height: rect.height,
        lineHeight,
        whiteSpace: style.whiteSpace,
        overflow: style.overflow,
        textOverflow: style.textOverflow,
      };
    }),
  );
  assert(metaInfos.length > 0, `${label} 未找到 meta 节点: ${selector}`);
  for (const info of metaInfos) {
    assert(info.height <= info.lineHeight * 1.6, `${label} meta 信息必须保持单行`, info);
    assert(info.whiteSpace === 'nowrap', `${label} meta 信息必须使用 nowrap`, info);
    assert(info.textOverflow === 'ellipsis', `${label} meta 信息必须使用省略号`, info);
  }
}

async function assertRecentPapers(page, width) {
  await page.goto(`${BASE_URL}#/`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#home-recent a[href^="#/papers/"]', { timeout: 10000 });

  await assertNoHorizontalOverflow(page, '首页最近论文', width);
  await assertMobileContainersCanShrink(page, 'main', '页面主内容');
  await assertMobileContainersCanShrink(page, '#main-content', '页面根内容');
  await assertMobileContainersCanShrink(page, '#home-content', '首页内容');

  const recentCount = await page.locator('#home-recent a[href^="#/papers/"]').count();
  assert(recentCount >= 1 && recentCount <= 5, '首页最近论文必须只显示 1 到 5 篇', { recentCount });

  const viewAllCount = await page.locator('#home-recent a[href="#/papers"]').count();
  assert(viewAllCount >= 1, '首页最近论文区域必须提供“查看全部”入口', { viewAllCount });

  await assertTwoLineClamp(page, '#home-recent .paper-title', '首页最近论文');
  await assertSingleLineMeta(page, '#home-recent .paper-meta', '首页最近论文');
}

async function assertPaperLibrary(page, width) {
  await page.goto(`${BASE_URL}#/papers`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#papers-list a[href^="#/papers/"]', { timeout: 10000 });

  await assertNoHorizontalOverflow(page, '论文库', width);
  await assertMobileContainersCanShrink(page, 'main', '论文库主内容');
  await assertMobileContainersCanShrink(page, '#main-content', '论文库根内容');
  await assertMobileContainersCanShrink(page, '#papers-page', '论文库页面');
  await assertMobileContainersCanShrink(page, '#papers-list', '论文卡片列表');

  await assertTwoLineClamp(page, '#papers-list .paper-title', '论文库');
  await assertSingleLineMeta(page, '#papers-list .paper-meta', '论文库');

  const cardChecks = await page.$$eval('#papers-list a[href^="#/papers/"]', (cards) =>
    cards.slice(0, 3).map((card) => {
      const icon = card.querySelector('.paper-icon');
      const body = card.querySelector('.paper-card-body');
      return {
        cardWidth: card.getBoundingClientRect().width,
        viewportWidth: document.documentElement.clientWidth,
        iconFlexShrink: icon ? getComputedStyle(icon).flexShrink : null,
        bodyMinWidth: body ? getComputedStyle(body).minWidth : null,
        bodyFlexGrow: body ? getComputedStyle(body).flexGrow : null,
      };
    }),
  );
  assert(cardChecks.length > 0, '论文库未找到论文卡片');
  for (const info of cardChecks) {
    assert(info.cardWidth <= info.viewportWidth + 1, '论文卡片不能超过视口宽度', info);
    assert(info.iconFlexShrink === '0', '论文图标区域必须 shrink: 0', info);
    assert(info.bodyMinWidth === '0px', '论文文本内容区域必须 min-width: 0', info);
    assert(Number(info.bodyFlexGrow) > 0, '论文文本内容区域必须 flex: 1', info);
  }

  await page.click('button[data-filter="done"]');
  await page.waitForSelector('#papers-list a[href^="#/papers/"]', { timeout: 10000 });
  const tabShrink = await page.$$eval('#filter-tabs .filter-tab', (tabs) =>
    tabs.map((tab) => ({ text: tab.textContent.trim(), flexShrink: getComputedStyle(tab).flexShrink, className: tab.className })),
  );
  for (const info of tabShrink) {
    assert(info.flexShrink === '0', '筛选按钮在切换后也必须保持 shrink-0，避免挤压移动端页面', info);
  }
  await assertNoHorizontalOverflow(page, '论文库筛选后', width);
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of WIDTHS) {
      const page = await browser.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 1, isMobile: true });
      await installApiMocks(page);
      await assertRecentPapers(page, width);
      await assertPaperLibrary(page, width);
      await page.close();
      console.log(`✓ mobile overflow regression passed at ${width}px`);
    }
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error.stack || error.message || error);
  process.exit(1);
});
