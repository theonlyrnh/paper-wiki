import { chromium } from 'playwright';

const BASE_URL = process.env.PW_BASE_URL || 'http://127.0.0.1:19828/';
const WIDTH = Number.parseInt(process.env.PW_WIDTH || '390', 10);
const HEIGHT = Number.parseInt(process.env.PW_HEIGHT || '900', 10);

function assert(condition, message, details = undefined) {
  if (!condition) {
    const suffix = details ? `\n${JSON.stringify(details, null, 2)}` : '';
    throw new Error(`${message}${suffix}`);
  }
}

function longAssistantText(index) {
  return [
    `这是第 ${index} 条用于布局回归测试的长消息。`,
    '这段内容会让消息列表产生足够的内部滚动高度，用于验证鼠标滚轮不会冒泡到 body、main 或 #main-content。',
    '如果页面外层可以滚动，聊天输入框会被推离底部，页面底部会出现非预期空白。',
  ].join(' ');
}

function makeMessages(count = 36) {
  return Array.from({ length: count }, (_, i) => ({
    role: i % 2 === 0 ? 'user' : 'assistant',
    content: i % 2 === 0 ? `测试问题 ${i + 1}` : longAssistantText(i + 1),
    references: [],
  }));
}

async function installApiMocks(page) {
  await page.route('**/api/auth/me', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 1, username: 'chat-layout-test', nickname: 'Chat Layout Test', role: 'admin', can_invite: true }),
  }));

  await page.route('**/api/chat/sessions', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{ id: 'layout-session', title: '布局测试会话', updated_at: '2026-06-18 09:00:00' }]),
  }));

  await page.route('**/api/chat/sessions/layout-session/messages', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(makeMessages()),
  }));

  await page.route('**/api/chat', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session_id: 'layout-session',
      message: { role: 'assistant', content: longAssistantText(999), references: [] },
    }),
  }));
}

async function readLayoutMetrics(page) {
  return page.evaluate(() => {
    const html = document.documentElement;
    const body = document.body;
    const main = document.querySelector('main');
    const mainContent = document.querySelector('#main-content');
    const chatPage = document.querySelector('#chat-page');
    const messages = document.querySelector('#chat-messages');
    const input = document.querySelector('#chat-input');
    const inputBar = document.querySelector('#chat-input-bar') || input?.parentElement?.parentElement;

    function box(el) {
      if (!el) return null;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return {
        top: rect.top,
        bottom: rect.bottom,
        height: rect.height,
        width: rect.width,
        overflowY: style.overflowY,
        minHeight: style.minHeight,
        flexShrink: style.flexShrink,
        scrollTop: el.scrollTop,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
      };
    }

    return {
      viewport: { width: innerWidth, height: innerHeight },
      windowScrollY: window.scrollY,
      documentScrollTop: html.scrollTop,
      bodyScrollTop: body.scrollTop,
      documentScrollHeight: html.scrollHeight,
      documentClientHeight: html.clientHeight,
      bodyScrollHeight: body.scrollHeight,
      bodyClientHeight: body.clientHeight,
      main: box(main),
      mainContent: box(mainContent),
      chatPage: box(chatPage),
      messages: box(messages),
      inputBar: box(inputBar),
    };
  });
}

async function assertNoPageScroll(page, label) {
  const metrics = await readLayoutMetrics(page);
  assert(metrics.windowScrollY === 0, `${label}: window.scrollY 必须保持 0`, metrics);
  assert(metrics.documentScrollTop === 0, `${label}: documentElement.scrollTop 必须保持 0`, metrics);
  assert(metrics.bodyScrollTop === 0, `${label}: body.scrollTop 必须保持 0`, metrics);
  assert(metrics.documentScrollHeight <= metrics.documentClientHeight + 1, `${label}: html 不应产生页面级纵向滚动`, metrics);
  assert(metrics.bodyScrollHeight <= metrics.bodyClientHeight + 1, `${label}: body 不应产生页面级纵向滚动`, metrics);
  assert(metrics.main && metrics.main.overflowY === 'hidden', `${label}: main 必须 overflow-y: hidden`, metrics);
  assert(metrics.mainContent && metrics.mainContent.overflowY === 'hidden', `${label}: #main-content 在聊天页必须 overflow-y: hidden`, metrics);
  assert(metrics.chatPage && metrics.chatPage.overflowY === 'hidden', `${label}: #chat-page 必须 overflow-y: hidden`, metrics);
  assert(metrics.messages && metrics.messages.overflowY === 'auto', `${label}: #chat-messages 必须作为内部滚动区`, metrics);
  assert(metrics.messages.scrollHeight > metrics.messages.clientHeight + 20, `${label}: 测试数据必须让消息列表出现内部滚动`, metrics);
  assert(metrics.inputBar && metrics.inputBar.flexShrink === '0', `${label}: 输入区必须 flex-shrink: 0`, metrics);
  return metrics;
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1, isMobile: WIDTH < 768 });
    await installApiMocks(page);

    await page.goto(`${BASE_URL}#/chat`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#chat-messages', { timeout: 10000 });
    await page.waitForSelector('#chat-input', { timeout: 10000 });

    await page.click('button:has-text("历史")');
    await page.waitForSelector('button:has-text("布局测试会话")', { timeout: 10000 });
    await page.click('button:has-text("布局测试会话")');
    await page.waitForFunction(() => {
      const messages = document.querySelector('#chat-messages');
      return messages && messages.children.length >= 30 && messages.scrollHeight > messages.clientHeight + 20;
    }, { timeout: 10000 });

    const before = await assertNoPageScroll(page, '滚动前');
    const beforeInputBottom = before.inputBar.bottom;
    const beforeMessageScrollTop = before.messages.scrollTop;

    await page.mouse.move(Math.floor(WIDTH / 2), Math.floor(HEIGHT / 2));
    await page.mouse.wheel(0, 900);
    await page.waitForTimeout(100);

    const after = await assertNoPageScroll(page, '滚动后');
    const inputDelta = Math.abs(after.inputBar.bottom - beforeInputBottom);
    assert(inputDelta <= 1.5, '滚轮后输入框底部位置不应移动', { beforeInputBottom, afterInputBottom: after.inputBar.bottom, inputDelta, after });
    assert(after.messages.scrollTop > beforeMessageScrollTop, '滚轮应该只滚动 #chat-messages 消息列表', { beforeMessageScrollTop, afterMessageScrollTop: after.messages.scrollTop, after });

    await page.close();
    console.log(`✓ chat scroll layout regression passed at ${WIDTH}x${HEIGHT}`);
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error.stack || error.message || error);
  process.exit(1);
});
