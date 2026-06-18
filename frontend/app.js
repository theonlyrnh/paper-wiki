/**
 * Main application — SPA router, auth check, theme support.
 */

// Utility functions (global)
function escHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function statusLabel(status) {
    const labels = { pending: '等待中', parsing: '解析中', ingesting: '摄入中', done: '完成', failed: '失败' };
    return labels[status] || status;
}

// Theme management
function applyTheme(theme) {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.documentElement.classList.toggle('light', theme !== 'dark');
    localStorage.setItem('pw_theme', theme);
}

function getTheme() {
    return localStorage.getItem('pw_theme') || 'dark';
}

// Router
function getRoute() {
    const hash = window.location.hash || '#/';
    const parts = hash.replace('#', '').split('/').filter(Boolean);
    return { path: parts, full: hash };
}
const PUBLIC_PAGES = new Set(['login', 'register']);

function setMainContentMode(pageId) {
    const container = document.getElementById('main-content');
    if (!container) return;
    const isChat = pageId === 'chat';
    container.classList.toggle('overflow-hidden', isChat);
    container.classList.toggle('overflow-y-auto', !isChat);
    container.classList.toggle('overflow-x-hidden', !isChat);
    container.classList.add('min-h-0');
    container.scrollTop = 0;
}

async function navigate() {
    const route = getRoute();
    const container = document.getElementById('main-content');
    const pageId = route.path[0] || 'home';

    if (PUBLIC_PAGES.has(pageId)) {
        document.getElementById('sidebar').style.display = 'none';
        document.querySelector('main').style.marginLeft = '0';
        setMainContentMode(pageId);
        switch (pageId) {
            case 'login': await renderLoginPage(container); break;
            case 'register': await renderRegisterPage(container); break;
        }
        return;
    }

    if (!API.isLoggedIn()) {
        const user = await API.getMe();
        if (!user) { location.hash = '#/login'; return; }
    }

    document.getElementById('sidebar').style.display = '';
    document.querySelector('main').style.marginLeft = '';
    renderSidebar(pageId);
    setMainContentMode(pageId);

    switch (pageId) {
        case 'home': await renderHomePage(container); break;
        case 'papers':
            route.path[1] ? await renderPaperDetailPage(container, route.path[1]) : await renderPapersPage(container);
            break;
        case 'search': renderSearchPage(container); break;
        case 'graph': renderGraphPage(container); break;
        case 'chat': renderChatPage(container); break;
        case 'settings': await renderSettingsPage(container); break;
        default:
            container.innerHTML = `<div class="text-center py-12"><div class="text-6xl mb-4">🤷</div><div class="text-gray-400 text-lg">页面不存在</div><a href="#/" class="text-blue-400 hover:text-blue-300 mt-4 inline-block">← 回到首页</a></div>`;
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    MarkdownRenderer.init();
    applyTheme(getTheme());
    window.addEventListener('hashchange', navigate);
    await API.getMe();
    navigate();
});
