/**
 * Home page — overview stats, recent papers, graph insights.
 *
 * Uses event delegation for click handling (no inline onclick).
 */

/* ── Utilities ───────────────────────────────────────── */

function escAttr(str) {
    if (!str) return '';
    return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function navigateTo(hash) {
    window.location.hash = hash;
}

/* ── Render ──────────────────────────────────────────── */

async function renderHomePage(container) {
    container.innerHTML = `
        <div class="page-shell space-y-5 md:space-y-8 w-full max-w-full min-w-0" id="home-content">
            <!-- Header -->
            <div class="flex flex-wrap items-center justify-between gap-3 w-full max-w-full min-w-0">
                <div class="min-w-0 max-w-full">
                    <h2 class="text-2xl font-bold text-white tracking-tight">📊 知识库总览</h2>
                    <p class="text-gray-500 text-sm mt-1.5">基于 LLM 的智能论文知识库</p>
                </div>
                <a href="#/papers"
                   class="hidden sm:inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500
                          rounded-xl text-white text-sm font-medium transition-all shadow-lg shadow-blue-600/20
                          hover:shadow-blue-500/30 active:scale-95">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                    </svg>
                    上传论文
                </a>
            </div>

            <!-- Mobile FAB (sm 以下显示) -->
            <a href="#/papers"
               class="sm:hidden fixed bottom-6 right-6 z-10 w-14 h-14 bg-blue-600 hover:bg-blue-500
                      rounded-full flex items-center justify-center shadow-xl shadow-blue-600/40
                      text-white text-2xl transition-all active:scale-95" aria-label="上传论文">＋</a>

            <!-- Stats Cards: 2 cols on mobile/tablet, 4 on desktop -->
            <div id="home-stats" class="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4 w-full max-w-full min-w-0">
                ${[1,2,3,4].map(() => `
                    <div class="w-full max-w-full min-w-0 bg-gray-800/80 backdrop-blur rounded-2xl p-4 md:p-5 border border-gray-700/50 animate-pulse">
                        <div class="h-7 w-14 bg-gray-700 rounded mb-2"></div>
                        <div class="h-4 w-16 bg-gray-700 rounded"></div>
                    </div>
                `).join('')}
            </div>

            <!-- Raw PDF Storage Quota -->
            <div id="home-storage-quota" class="w-full max-w-full min-w-0 bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-4 md:p-5">
                <div class="text-gray-500 text-sm animate-pulse">加载上传文件空间...</div>
            </div>

            <!-- Two Columns: single on <lg, two-col on lg+ -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 w-full max-w-full min-w-0">
                <!-- Recent Papers -->
                <div class="lg:col-span-2 w-full max-w-full min-w-0 space-y-3">
                    <h3 class="text-lg font-semibold text-white flex items-center gap-2 min-w-0">
                        <span class="w-1.5 h-5 bg-blue-500 rounded-full"></span>
                        最近论文
                    </h3>
                    <div id="home-recent" class="paper-list w-full max-w-full min-w-0 bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-1
                                         divide-y divide-gray-700/50">
                        <div class="p-4 text-gray-500 animate-pulse">加载中...</div>
                    </div>
                </div>

                <!-- Graph Insights -->
                <div class="w-full max-w-full min-w-0 space-y-3">
                    <h3 class="text-lg font-semibold text-white flex items-center gap-2 min-w-0">
                        <span class="w-1.5 h-5 bg-purple-500 rounded-full"></span>
                        图谱洞察
                    </h3>
                    <div id="home-insights" class="w-full max-w-full min-w-0 bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50
                                           divide-y divide-gray-700/50">
                        <div class="p-4 text-gray-500 animate-pulse text-sm">加载中...</div>
                    </div>
                </div>
            </div>

            <!-- Spotlight + Tips -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 w-full max-w-full min-w-0">
                <div id="home-spotlight" class="w-full max-w-full min-w-0 bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-5">
                    <div class="text-gray-500 text-sm animate-pulse">加载今日焦点...</div>
                </div>
                <div id="home-tips" class="w-full max-w-full min-w-0 bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-5"></div>
            </div>

            <!-- Ingest Queue (hidden when empty) -->
            <div id="home-queue" class="hidden w-full max-w-full min-w-0 bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-3"></div>
        </div>
    `;

    // Fetch all data in parallel
    const [statsResult, quotaResult, papersResult, insightsResult, queueResult] = await Promise.allSettled([
        API.getStats(),
        API.getStorageQuota(),
        API.listPapers(1, 5),
        fetch('/api/graph/insights', { credentials: 'include' }).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }),
        API.getIngestStatus(),
    ]);

    _renderStats(statsResult);
    _renderStorageQuota(quotaResult);
    _renderRecent(papersResult);
    _renderInsights(insightsResult);
    _renderQueue(queueResult);
    _renderBottom(insightsResult);

    window.removeEventListener('storage-quota-updated', _handleStorageQuotaUpdated);
    window.addEventListener('storage-quota-updated', _handleStorageQuotaUpdated);
}

/* ── Stats ────────────────────────────────────────────── */

function _renderStats(result) {
    const el = document.getElementById('home-stats');
    if (result.status !== 'fulfilled') {
        el.innerHTML = '<div class="col-span-4 text-red-400 text-sm p-4">加载失败</div>';
        return;
    }
    const s = result.value;
    const items = [
        { label: '论文', value: s.paper_count, color: 'text-blue-400', icon: '📄' },
        { label: 'Wiki 页面', value: s.wiki_page_count, color: 'text-emerald-400', icon: '📝' },
        { label: '图谱节点', value: s.graph_node_count, color: 'text-purple-400', icon: '🕸️' },
        { label: '关联边', value: s.graph_edge_count, color: 'text-amber-400', icon: '🔗' },
    ];
    el.innerHTML = items.map(({ label, value, color, icon }) => `
        <div class="w-full max-w-full min-w-0 bg-gray-800/80 backdrop-blur rounded-2xl p-4 md:p-5 border border-gray-700/50
                    hover:border-gray-600/50 transition-colors">
            <span class="text-xl">${icon}</span>
            <div class="text-3xl font-bold ${color} tracking-tight mt-2">${value}</div>
            <div class="text-gray-500 text-sm mt-1 truncate">${label}</div>
        </div>
    `).join('');
}

/* ── Storage Quota ───────────────────────────────────── */

function _formatStorageMb(value) {
    const n = Number(value || 0);
    if (n >= 1024) return `${(n / 1024).toFixed(2)} GB`;
    if (n >= 10) return `${n.toFixed(1)} MB`;
    return `${n.toFixed(3)} MB`;
}

function _quotaBarColor(percent) {
    if (percent >= 95) return 'bg-red-500';
    if (percent >= 80) return 'bg-amber-500';
    return 'bg-blue-500';
}

function _handleStorageQuotaUpdated(event) {
    _renderStorageQuota({ status: 'fulfilled', value: event.detail });
}

function _renderStorageQuota(result) {
    const el = document.getElementById('home-storage-quota');
    if (!el) return;
    if (result.status !== 'fulfilled') {
        el.innerHTML = '<div class="text-red-400 text-sm">上传文件空间加载失败</div>';
        return;
    }
    const q = result.value;
    const percent = Math.max(0, Math.min(100, Number(q.usage_percent || 0)));
    const barColor = _quotaBarColor(percent);
    const warning = percent >= 100
        ? '上传文件空间已满，暂时无法继续上传 PDF。'
        : percent >= 80
            ? '上传文件空间即将用完，建议先删除已解析论文的原始 PDF。'
            : '空间充足。';

    el.innerHTML = `
        <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 w-full max-w-full min-w-0">
            <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2 mb-2">
                    <span class="text-lg">💾</span>
                    <h3 class="text-white font-semibold">上传文件空间</h3>
                    <span class="text-xs px-2 py-0.5 rounded-full ${percent >= 100 ? 'bg-red-600/20 text-red-300' : percent >= 80 ? 'bg-amber-600/20 text-amber-300' : 'bg-blue-600/20 text-blue-300'}">
                        ${percent.toFixed(1)}%
                    </span>
                </div>
                <div class="flex items-baseline gap-2 min-w-0">
                    <span class="text-2xl font-bold text-white">${_formatStorageMb(q.used_mb)}</span>
                    <span class="text-gray-500 text-sm">/ ${_formatStorageMb(q.quota_mb)}</span>
                </div>
                <div class="mt-3 h-2.5 rounded-full bg-gray-900/70 overflow-hidden w-full max-w-full">
                    <div class="h-full ${barColor} rounded-full transition-all duration-500" style="width: ${percent}%"></div>
                </div>
                <p class="text-xs mt-2 ${percent >= 100 ? 'text-red-300' : percent >= 80 ? 'text-amber-300' : 'text-gray-500'}">
                    ${warning}
                </p>
            </div>
            <div class="lg:w-80 shrink-0 bg-gray-900/40 border border-gray-700/50 rounded-xl p-3">
                <div class="min-w-0">
                    <span class="block text-sm text-white">删除原始 PDF 只为释放空间</span>
                    <span class="block text-xs text-gray-500 mt-1 leading-relaxed">
                        已解析成 Markdown 的内容不受影响；搜索、AI 问答、Wiki 和来源切片缓存会继续可用。
                    </span>
                </div>
            </div>
        </div>
    `;
}

/* ── Recent Papers ────────────────────────────────────── */

function _renderRecent(result) {
    const el = document.getElementById('home-recent');
    if (result.status !== 'fulfilled') {
        el.innerHTML = '<div class="p-4 text-red-400 text-sm">加载失败</div>';
        return;
    }
    const papers = result.value;
    const visiblePapers = papers.slice(0, 5);
    if (!papers.length) {
        el.innerHTML = `
            <div class="p-10 text-center">
                <span class="text-4xl block mb-3">📭</span>
                <div class="text-gray-400 mb-2">暂无论文</div>
                <a href="#/papers" class="text-blue-400 hover:text-blue-300 text-sm">上传第一篇 →</a>
            </div>`;
        return;
    }
    el.innerHTML = `
        ${visiblePapers.map(p => `
        <a href="#/papers/${p.id}"
           class="paper-list-item flex items-center gap-3 px-4 py-3.5 hover:bg-gray-700/40 transition-colors group cursor-pointer w-full max-w-full min-w-0 overflow-hidden">
            <span class="paper-icon text-xl shrink-0">📄</span>
            <div class="paper-card-body min-w-0 flex-1 max-w-full">
                <div class="paper-title text-white text-sm font-medium line-clamp-2 break-words group-hover:text-blue-400 transition-colors leading-snug">
                    ${escHtml(p.title)}
                </div>
                <div class="paper-meta text-xs text-gray-500 mt-0.5 truncate">
                    ${escHtml(p.filename)} · ${p.created_at.split(' ')[0]}
                </div>
            </div>
            <span class="status-badge status-${p.status} shrink-0">${statusLabel(p.status)}</span>
        </a>
        `).join('')}
        <a href="#/papers"
           class="flex items-center justify-center gap-1 px-4 py-3 text-sm text-blue-400 hover:text-blue-300 hover:bg-gray-700/30 transition-colors">
            查看全部
            <span aria-hidden="true">→</span>
        </a>
    `;
    // Only scroll when list is long
    if (papers.length > 5) {
        el.style.maxHeight = '22rem';
        el.style.overflowY = 'auto';
    } else {
        el.style.maxHeight = '';
        el.style.overflowY = '';
    }
}

/* ── Insights (event delegation, no onclick attributes) ── */

function _renderInsights(result) {
    const el = document.getElementById('home-insights');
    if (result.status !== 'fulfilled') {
        el.innerHTML = '<div class="p-4 text-gray-500 text-center text-sm">暂无洞察数据</div>';
        return;
    }

    const ins = result.value;
    let html = '';

    // Surprising Connections
    if (ins.surprising_connections && ins.surprising_connections.length) {
        html += `
        <div class="p-4">
            <div class="text-xs text-gray-500 font-medium mb-2.5 uppercase tracking-wider">🔗 跨社区连接</div>
            ${ins.surprising_connections.slice(0, 5).map(c => `
                <div class="flex items-center text-sm px-3 py-2 -mx-1 rounded-lg
                            hover:bg-gray-700/50 transition-colors cursor-pointer group"
                     data-action="connection"
                     data-source-id="${escAttr(c.source_id || c.source)}"
                     data-target-id="${escAttr(c.target_id || c.target)}">
                    <span class="text-blue-300 group-hover:text-blue-200 truncate max-w-[120px]">
                        ${escHtml(c.source)}
                    </span>
                    <svg class="w-3.5 h-3.5 mx-2 text-gray-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                    </svg>
                    <span class="text-emerald-300 group-hover:text-emerald-200 truncate max-w-[120px] flex-1">
                        ${escHtml(c.target)}
                    </span>
                    <span class="text-gray-600 text-xs ml-auto shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">查看</span>
                </div>
            `).join('')}
        </div>`;
    }

    // Hubs
    if (ins.hubs && ins.hubs.length) {
        html += `
        <div class="p-4">
            <div class="text-xs text-gray-500 font-medium mb-2.5 uppercase tracking-wider">⭐ 中心节点</div>
            <div class="flex flex-wrap gap-2">
                ${ins.hubs.slice(0, 8).map(h => `
                    <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs
                                 bg-gray-700/50 text-gray-300 hover:bg-gray-600 hover:text-white
                                 transition-colors cursor-pointer"
                          data-action="node" data-node-id="${escAttr(h.id)}">
                        ${escHtml(h.label)}
                        <span class="text-gray-600">${h.degree}</span>
                    </span>
                `).join('')}
            </div>
        </div>`;
    }

    // Knowledge Gaps
    if (ins.knowledge_gaps && ins.knowledge_gaps.length) {
        html += `
        <div class="p-4">
            <div class="text-xs text-gray-500 font-medium mb-2.5 uppercase tracking-wider">
                🕳️ 知识空白
                <span class="normal-case tracking-normal font-normal ml-1">（被引用但无页面）</span>
            </div>
            <div class="flex flex-wrap gap-1.5">
                ${ins.knowledge_gaps.slice(0, 8).map(g => `
                    <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px]
                                 bg-gray-700/40 text-gray-400 hover:bg-gray-600 hover:text-white
                                 transition-colors cursor-pointer"
                          data-action="gap" data-gap-name="${escAttr(g.name)}">
                        ${escHtml(g.name)}
                        <span class="text-gray-600">×${g.referenced_by}</span>
                    </span>
                `).join('')}
            </div>
        </div>`;
    }

    el.innerHTML = html || '<div class="p-4 text-gray-500 text-center text-sm">上传更多论文以发现洞察</div>';

    // ── Event delegation: single listener handles all clicks ──
    // Remove old listener if any, then attach
    el.onclick = null;
    el.addEventListener('click', (e) => {
        const target = e.target.closest('[data-action]');
        if (!target) return;
        const action = target.getAttribute('data-action');
        switch (action) {
            case 'connection': {
                const srcId = target.getAttribute('data-source-id');
                const tgtId = target.getAttribute('data-target-id');
                window.__graphPendingNode = srcId;
                window.__graphPendingHighlight = tgtId;
                navigateTo('#/graph');
                break;
            }
            case 'node': {
                const nodeId = target.getAttribute('data-node-id');
                window.__graphPendingNode = nodeId;
                navigateTo('#/graph');
                break;
            }
            case 'gap': {
                const name = target.getAttribute('data-gap-name');
                window.__searchPendingQuery = name;
                navigateTo('#/search');
                break;
            }
        }
    });
}

/* ── Queue ────────────────────────────────────────────── */

function _renderQueue(result) {
    const el = document.getElementById('home-queue');
    if (result.status !== 'fulfilled' || !result.value.length) return; // stay hidden
    const queue = result.value.slice(0, 5);
    el.classList.remove('hidden');
    el.innerHTML = `
        <div class="flex items-center gap-2 mb-2 px-1">
            <span class="w-1.5 h-4 bg-yellow-500 rounded-full"></span>
            <span class="text-xs font-medium text-gray-400 uppercase tracking-wider">摄入队列</span>
        </div>` +
        queue.map(q => `
        <div class="flex items-center justify-between px-4 py-2.5 rounded-lg
                    ${q.status === 'failed' ? 'bg-red-900/15' : 'hover:bg-gray-700/30'} transition-colors">
            <div class="flex items-center gap-3 min-w-0">
                <span class="status-badge status-${q.status} text-[10px] shrink-0">${q.status}</span>
                <span class="text-white text-sm truncate">${escHtml(q.paper_title || q.paper_id.slice(0, 8))}</span>
                <span class="text-gray-600 text-xs shrink-0">${q.step || ''}</span>
            </div>
            <span class="text-gray-600 text-xs shrink-0 ml-3">
                ${q.updated_at ? q.updated_at.split('T')[0] : ''}
            </span>
        </div>
    `).join('');
}

/* ── Bottom: Spotlight + Tips ──────────────────────────── */

const _TIPS = [
    { icon: '🔍', title: '语义搜索技巧', body: '不知道关键词？用自然语言描述概念，语义搜索比关键词匹配更懂你的意图。' },
    { icon: '💬', title: 'AI 问答技巧', body: '追问细节时说"请结合论文原文"——AI 会引用具体来源，方便溯源验证。' },
    { icon: '🕸️', title: '发现隐藏联系', body: '图谱中"跨社区连接"往往是最有创意的研究方向——不同领域的交汇处正是创新点。' },
    { icon: '📄', title: '批量上传', body: '支持同时选择多篇 PDF 上传，系统会自动去重，已上传的论文不会重复处理。' },
    { icon: '🧠', title: '摄入 = 生成知识', body: '上传后记得点"摄入"，LLM 才会提取实体并生成 Wiki 页面——知识库真正的增长时刻。' },
    { icon: '📝', title: 'Wiki 溯源', body: '每个 Wiki 页面都关联 PDF 原文段落，点击引用来源可跳转到对应页面截图验证。' },
    { icon: '🎯', title: '混合搜索最准', body: '"混合搜索"结合关键词与语义向量，对学术术语精确、对自然语言描述准确，两者兼顾。' },
];

function _renderBottom(insightsResult) {
    _renderSpotlight(insightsResult);
    _renderTips();
}

function _renderSpotlight(insightsResult) {
    const el = document.getElementById('home-spotlight');
    if (!el) return;
    const hubs = insightsResult.status === 'fulfilled' ? insightsResult.value?.hubs : null;
    if (!hubs?.length) {
        el.innerHTML = `
            <div class="text-xs text-gray-500 font-medium uppercase tracking-wider mb-3">💡 今日焦点</div>
            <div class="text-gray-600 text-sm">摄入更多论文后，这里将展示知识图谱的核心概念。</div>`;
        return;
    }
    const hub = hubs[new Date().getDate() % hubs.length];
    el.innerHTML = `
        <div class="text-xs text-gray-500 font-medium uppercase tracking-wider mb-3">💡 今日焦点</div>
        <div class="flex items-start gap-3">
            <span class="w-10 h-10 rounded-xl bg-blue-600/20 flex items-center justify-center text-lg shrink-0">🔮</span>
            <div class="min-w-0">
                <div class="text-white font-semibold truncate">${escHtml(hub.label)}</div>
                <div class="text-gray-500 text-xs mt-0.5">中心节点 · ${hub.degree} 个关联</div>
            </div>
        </div>
        <p class="text-gray-400 text-sm mt-3 leading-relaxed">
            这是当前知识库中连接最广泛的概念之一，关联了 ${hub.degree} 个节点。
            探索它的关联网络，可能发现意想不到的跨领域联系。
        </p>
        <button class="mt-3 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                data-node-id="${escAttr(hub.id)}">在图谱中查看 →</button>`;
    el.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-node-id]');
        if (!btn) return;
        window.__graphPendingNode = btn.dataset.nodeId;
        navigateTo('#/graph');
    });
}

function _renderTips() {
    const el = document.getElementById('home-tips');
    if (!el) return;
    const tip = _TIPS[new Date().getDay()];
    el.innerHTML = `
        <div class="text-xs text-gray-500 font-medium uppercase tracking-wider mb-3">✨ 使用技巧</div>
        <div class="flex items-start gap-3">
            <span class="w-10 h-10 rounded-xl bg-purple-600/20 flex items-center justify-center text-lg shrink-0">${tip.icon}</span>
            <div>
                <div class="text-white font-semibold">${escHtml(tip.title)}</div>
                <p class="text-gray-400 text-sm mt-1.5 leading-relaxed">${escHtml(tip.body)}</p>
            </div>
        </div>
        <div class="mt-4 pt-3 border-t border-gray-700/50">
            <span class="text-gray-600 text-xs">每天轮换 · 共 ${_TIPS.length} 条</span>
        </div>`;
}
