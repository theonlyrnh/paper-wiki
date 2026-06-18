/**
 * Sidebar navigation component — with user info and logout.
 */
function renderSidebar(currentPage) {
    const navItems = [
        { id: 'home', icon: '🏠', label: '首页', hash: '#/' },
        { id: 'papers', icon: '📄', label: '论文库', hash: '#/papers' },
        { id: 'search', icon: '🔍', label: '搜索', hash: '#/search' },
        { id: 'graph', icon: '🕸️', label: '知识图谱', hash: '#/graph' },
        { id: 'chat', icon: '💬', label: 'AI 对话', hash: '#/chat' },
        { id: 'settings', icon: '⚙️', label: '设置', hash: '#/settings' },
    ];

    const user = API.currentUser;
    const userLabel = user ? (user.nickname || user.username || '') : '';
    const isAdmin = user && user.role === 'admin';

    const sidebar = document.getElementById('sidebar');
    sidebar.innerHTML = `
        <div class="px-5 py-5 border-b border-gray-800/30">
            <h1 class="text-lg font-bold text-white flex items-center gap-2.5 tracking-tight">
                <span class="w-8 h-8 rounded-lg bg-blue-600/20 flex items-center justify-center text-sm">📚</span>
                <span>论文知识库</span>
            </h1>
        </div>
        <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
            ${navItems.map(item => `
                <a href="${item.hash}"
                   class="flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150
                          ${currentPage === item.id
                              ? 'bg-blue-600/15 text-blue-400 font-medium border border-blue-500/20'
                              : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'}">
                    <span class="w-5 text-center">${item.icon}</span>
                    <span class="text-sm">${item.label}</span>
                </a>
            `).join('')}
        </nav>
        <!-- Theme toggle -->
        <div class="px-3 py-2">
            <button id="btn-theme"
                    class="flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150 w-full text-left text-gray-400 hover:text-gray-200 hover:bg-gray-800/50">
                <span id="theme-icon" class="w-5 text-center">🌙</span>
                <span id="theme-label" class="text-sm">暗色模式</span>
            </button>
        </div>
        <div class="px-4 py-3 border-t border-gray-800/30">
            <div id="sidebar-stats" class="text-[11px] text-gray-600 flex items-center gap-3 mb-3">
                <span>📄 -</span>
                <span>📝 -</span>
                <span>🕸️ -</span>
            </div>
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-2 min-w-0">
                    <div class="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                                flex items-center justify-center text-[10px] text-white font-bold shrink-0">
                        ${userLabel.charAt(0).toUpperCase()}
                    </div>
                    <div class="min-w-0">
                        <div class="text-xs text-gray-300 truncate">${escHtml(userLabel)}</div>
                        ${isAdmin ? '<div class="text-[10px] text-amber-500">管理员</div>' : ''}
                    </div>
                </div>
                <button id="btn-logout"
                        class="text-gray-600 hover:text-red-400 transition-colors p-1.5 rounded-lg
                               hover:bg-gray-800/50" title="退出登录">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                              d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
                    </svg>
                </button>
            </div>
        </div>
    `;

    // Logout handler
    document.getElementById('btn-logout').addEventListener('click', () => API.logout());

    // Theme toggle handler
    let theme = getTheme();
    function updateThemeBtn() {
        const icon = document.getElementById('theme-icon');
        const label = document.getElementById('theme-label');
        if (!icon || !label) return;
        if (theme === 'dark') { icon.textContent = '🌙'; label.textContent = '暗色模式'; }
        else { icon.textContent = '☀️'; label.textContent = '亮色模式'; }
    }
    updateThemeBtn();
    document.getElementById('btn-theme').addEventListener('click', () => {
        theme = theme === 'dark' ? 'light' : 'dark';
        applyTheme(theme);
        updateThemeBtn();
        // Save to server if logged in
        if (API.isLoggedIn()) {
            API.updateConfig({ theme }).catch(() => {});
        }
    });

    // Load stats
    API.getStats().then(stats => {
        const el = document.getElementById('sidebar-stats');
        if (!el) return;
        el.innerHTML = `
            <span class="flex items-center gap-1"><span class="text-blue-400">📄</span> ${stats.paper_count}</span>
            <span class="flex items-center gap-1"><span class="text-emerald-400">📝</span> ${stats.wiki_page_count}</span>
            <span class="flex items-center gap-1"><span class="text-purple-400">🕸️</span> ${stats.graph_node_count}</span>
        `;
    }).catch(() => {});
}
