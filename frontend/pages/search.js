/**
 * Search page — hybrid BM25 + vector semantic search with results display.
 */
let searchMode = 'hybrid';
let _lastSearchQuery = '';

function pdfCleanedFallbackHtml() {
    return `
        <div class="text-gray-500 text-xs leading-relaxed text-center py-4 px-3">
            <div class="text-lg mb-1">🧹</div>
            <div class="text-gray-400">原始 PDF 已释放</div>
            <div class="mt-1">删除 PDF 只是释放空间；相关内容已转为 Markdown，不影响搜索、AI 问答和 Wiki。</div>
        </div>
    `;
}

async function renderSearchPage(container) {
    container.innerHTML = `
        <div class="space-y-4">
            <div class="flex flex-wrap items-center justify-between gap-2">
                <h2 class="text-2xl font-bold text-white">🔍 搜索</h2>
                <div class="flex gap-1 bg-gray-800 rounded-lg p-1">
                    <button onclick="setSearchMode('hybrid')" id="mode-hybrid"
                            class="mode-btn px-3 py-1 rounded text-xs font-medium transition-colors bg-blue-600 text-white">
                        混合
                    </button>
                    <button onclick="setSearchMode('bm25')" id="mode-bm25"
                            class="mode-btn px-3 py-1 rounded text-xs font-medium transition-colors text-gray-400 hover:text-white">
                        关键词
                    </button>
                    <button onclick="setSearchMode('vector')" id="mode-vector"
                            class="mode-btn px-3 py-1 rounded text-xs font-medium transition-colors text-gray-400 hover:text-white">
                        语义
                    </button>
                </div>
            </div>

            <div class="relative">
                <input type="text" id="search-input"
                       placeholder="搜索知识库..."
                       class="w-full bg-gray-800 border border-gray-600 rounded-xl px-4 py-3 pl-11 pr-24
                              text-white placeholder-gray-500 focus:outline-none focus:border-blue-500
                              focus:ring-2 focus:ring-blue-500/20"
                       autocomplete="off" />
                <span class="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-500 text-lg">🔍</span>
                <div id="search-mode-badge" class="absolute right-3 top-1/2 -translate-y-1/2
                     text-xs px-2 py-0.5 rounded bg-blue-600/30 text-blue-300 whitespace-nowrap">
                    混合搜索
                </div>
            </div>

            <div id="search-results" class="space-y-3">
                <div class="text-gray-500 text-center py-8">
                    <div class="text-4xl mb-3">💡</div>
                    <div>输入关键词或自然语言描述开始搜索</div>
                    <div class="text-sm text-gray-600 mt-2">
                        试试："如何降低注意力机制的计算复杂度" 或 "what is self-attention"
                    </div>
                </div>
            </div>
        </div>
    `;

    const input = document.getElementById('search-input');
    let debounce = null;

    input.addEventListener('input', () => {
        clearTimeout(debounce);
        debounce = setTimeout(() => doSearch(input.value.trim()), 300);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            clearTimeout(debounce);
            doSearch(input.value.trim());
        }
    });

    input.focus();

    // If navigated from another page (e.g. home page knowledge gap), auto-search
    if (window.__searchPendingQuery) {
        const q = window.__searchPendingQuery;
        window.__searchPendingQuery = null;
        input.value = q;
        doSearch(q);
    }
}

function setSearchMode(mode) {
    searchMode = mode;
    const labels = { hybrid: '混合搜索', bm25: '关键词搜索', vector: '语义搜索' };
    const colors = { hybrid: 'bg-blue-600/30 text-blue-300', bm25: 'bg-green-600/30 text-green-300', vector: 'bg-purple-600/30 text-purple-300' };

    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.className = 'mode-btn px-3 py-1 rounded text-xs font-medium transition-colors text-gray-400 hover:text-white';
    });
    const activeBtn = document.getElementById(`mode-${mode}`);
    if (activeBtn) activeBtn.className = 'mode-btn px-3 py-1 rounded text-xs font-medium transition-colors bg-blue-600 text-white';

    const badge = document.getElementById('search-mode-badge');
    if (badge) {
        badge.textContent = labels[mode];
        badge.className = `absolute right-4 top-1/2 -translate-y-1/2 text-xs px-2 py-0.5 rounded ${colors[mode]}`;
    }

    // Re-search with current query
    const input = document.getElementById('search-input');
    if (input && input.value.trim()) doSearch(input.value.trim());
}

async function doSearch(query) {
    _lastSearchQuery = query;
    const el = document.getElementById('search-results');
    if (!query) {
        el.innerHTML = `
            <div class="text-gray-500 text-center py-8">
                <div class="text-4xl mb-3">💡</div>
                <div>输入关键词或自然语言描述开始搜索</div>
            </div>`;
        return;
    }

    el.innerHTML = '<div class="text-gray-400 text-center py-4 animate-pulse">搜索中...</div>';

    try {
        const resp = await fetch(`/api/search?q=${encodeURIComponent(query)}&mode=${searchMode}`, { credentials: 'include' });
        const data = await resp.json();

        if (data.results.length === 0) {
            el.innerHTML = `
                <div class="text-center py-8">
                    <div class="text-4xl mb-3">🔎</div>
                    <div class="text-gray-400">未找到「${escHtml(query)}」的结果</div>
                    <div class="text-gray-600 text-sm mt-2">试试切换搜索模式或使用不同的关键词</div>
                </div>`;
            return;
        }

        el.innerHTML = `
            <div class="flex items-center justify-between mb-1">
                <div class="text-sm text-gray-500">${data.count} 个结果 · ${data.mode} 模式</div>
            </div>
            ${data.results.map(r => {
                const sources = r.search_sources || [];
                const sourceBadge = sources.length === 2
                    ? '<span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-600/20 text-blue-400">混合</span>'
                    : sources.includes('vector')
                    ? '<span class="text-[10px] px-1.5 py-0.5 rounded bg-purple-600/20 text-purple-400">语义</span>'
                    : '<span class="text-[10px] px-1.5 py-0.5 rounded bg-green-600/20 text-green-400">关键词</span>';
                const papers = r.papers || [];
                const paperCount = papers.length;
                const paperCountBadge = paperCount > 1 ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-600/20 text-blue-400">📄 ${paperCount}篇</span>` : '';
                const paperLinks = papers.length ? `
                    <div class="flex items-center gap-1.5 mt-2 flex-wrap">
                        <span class="text-[10px] text-gray-600">📄 来源:</span>
                        ${papers.map(p => `
                            <a href="#/papers/${p.id}" class="text-[10px] px-2 py-0.5 rounded bg-gray-700/50 text-blue-400 hover:text-blue-300 hover:bg-gray-600/50 transition-colors truncate max-w-[200px]" onclick="event.stopPropagation()" title="${escHtml(p.title)}">
                                ${escHtml(p.title.slice(0, 30))}
                            </a>
                        `).join('')}
                    </div>` : '';
                return `
                <div class="bg-gray-800 rounded-xl p-4 hover:bg-gray-750 transition-colors cursor-pointer"
                     onclick="showWikiPage('${escHtml(r.name)}', '${escHtml(r.type)}')">
                    <div class="flex items-center gap-2 mb-2 flex-wrap">
                        <span class="text-xs px-2 py-0.5 rounded-full ${typeBadgeColor(r.type)}">${escHtml(r.type)}</span>
                        <span class="text-white font-semibold">${escHtml(r.title)}</span>
                        ${sourceBadge}
                        ${paperCountBadge}
                        <span class="text-xs text-gray-600 ml-auto">${r.score.toFixed(4)}</span>
                    </div>
                    <div class="text-sm text-gray-400 line-clamp-2">${escHtml(r.snippet)}</div>
                    ${paperLinks}
                </div>
            `}).join('')}
        `;
    } catch (e) {
        el.innerHTML = `<div class="text-red-400">搜索失败: ${e.message}</div>`;
    }
}

function typeBadgeColor(type) {
    const colors = {
        source: 'bg-blue-600/30 text-blue-300',
        entity: 'bg-green-600/30 text-green-300',
        concept: 'bg-purple-600/30 text-purple-300',
        root: 'bg-gray-600/30 text-gray-300',
    };
    return colors[type] || 'bg-gray-600/30 text-gray-300';
}

async function showWikiPage(name, type) {
    // Clean up previous PDF images from memory
    _cleanupPdfSlices();

    const container = document.getElementById('main-content');
    container.innerHTML = '<div class="text-center py-12 animate-pulse text-gray-400">加载中...</div>';

    try {
        const resp = await fetch(`/api/wiki/page/${type}/${name}`, { credentials: 'include' });
        if (!resp.ok) throw new Error('Page not found');
        const data = await resp.json();

        // Search query for context (from last search or page title)
        const searchQuery = _lastSearchQuery || data.title || '';

        container.innerHTML = `
            <div class="space-y-4">
                <button onclick="backToSearch()" class="text-blue-400 hover:text-blue-300 text-sm cursor-pointer">← 返回搜索</button>
                <div class="flex items-center gap-2">
                    <span class="text-xs px-2 py-0.5 rounded-full ${typeBadgeColor(type)}">${escHtml(type)}</span>
                    <h2 class="text-2xl font-bold text-white">${escHtml(data.title || name)}</h2>
                </div>
                <div class="flex gap-6">
                    <!-- Left: Wiki content -->
                    <div class="flex-1 min-w-0">
                        <div class="bg-gray-800 rounded-xl p-6">
                            <div class="prose prose-invert max-w-none markdown-body">
                                ${MarkdownRenderer.render(data.content)}
                            </div>
                        </div>
                    </div>
                    <!-- Right: PDF slices -->
                    <div class="w-96 shrink-0" id="pdf-slices-panel">
                        <div class="text-gray-500 text-xs text-center py-4">加载 PDF 相关段落...</div>
                    </div>
                </div>
            </div>
        `;

        // Load PDF slices from all source papers
        const sourceHighlights = data.source_highlights || [];
        if (sourceHighlights.length) {
            _loadPdfSlices(sourceHighlights, searchQuery);
        } else {
            document.getElementById('pdf-slices-panel').innerHTML =
                '<div class="text-gray-600 text-xs text-center py-4">暂无来源论文</div>';
        }
    } catch (e) {
        container.innerHTML = `
            <button onclick="backToSearch()" class="text-blue-400 hover:text-blue-300 text-sm cursor-pointer">← 返回搜索</button>
            <div class="text-red-400 mt-4">加载失败: ${e.message}</div>
        `;
    }
}

// Track loaded images for cleanup
let _pdfBlobUrls = [];

async function _loadPdfSlices(sourceHighlights, searchQuery) {
    const panel = document.getElementById('pdf-slices-panel');
    if (!panel) return;

    panel.innerHTML = sourceHighlights.map((h, hi) => `
        <div class="mb-4 bg-gray-800/80 rounded-xl border border-gray-700/50 overflow-hidden">
            <div class="px-3 py-1.5 bg-gray-700/50 border-b border-gray-700/30">
                <a href="#/papers/${h.paper_id}" class="text-xs text-blue-400 hover:text-blue-300 truncate">
                    📄 ${escHtml((h.paper_title || '').slice(0, 50))}
                </a>
            </div>
            <div id="pdf-slices-${hi}" class="p-2 space-y-2">
                <div class="text-center py-6 text-gray-600 text-xs animate-pulse">加载中...</div>
            </div>
        </div>
    `).join('');

    for (let hi = 0; hi < sourceHighlights.length; hi++) {
        const h = sourceHighlights[hi];
        if (!h.paper_id) continue;
        try {
            const highlights = h.highlights || [];
            const resp = await fetch(`/api/papers/${h.paper_id}/pdf-highlights`, {
                method: 'POST',
                credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    snippets: highlights.map(hl => ({
                        text: hl.text, start_line: hl.start_line, end_line: hl.end_line
                    })),
                    query: searchQuery,
                }),
            });
            if (!resp.ok) continue;
            const data = await resp.json();
            const slicesEl = document.getElementById(`pdf-slices-${hi}`);
            if (!slicesEl) continue;

            if (!data.slices || !data.slices.length) {
                if (data.pdf_available === false) {
                    slicesEl.innerHTML = pdfCleanedFallbackHtml();
                    continue;
                }
                slicesEl.innerHTML = '<div class="text-gray-600 text-xs text-center py-4">未找到匹配段落</div>';
                continue;
            }

            slicesEl.innerHTML = data.slices.map((sl, si) => {
                // Generate unique ID for this image
                const imgId = `pdf-slice-${hi}-${si}`;
                return `
                    <div class="cursor-pointer hover:ring-2 ring-amber-500/30 rounded transition-all overflow-hidden"
                         onclick="_pdfZoomIn(this.querySelector('img'))">
                        <div class="flex items-center justify-between px-1 mb-1">
                            <span class="text-[10px] text-gray-600">第 ${sl.page} 页 · 匹配 ${sl.score}%${data.cache_status === 'hit' ? ' · 缓存' : ''}</span>
                        </div>
                        <img id="${imgId}" class="w-full rounded border border-gray-700/30"
                             alt="Page ${sl.page}" loading="lazy">
                    </div>
                `;
            }).join('');

            // Load images lazily
            data.slices.forEach((sl, si) => {
                const img = document.getElementById(`pdf-slice-${hi}-${si}`);
                if (img) {
                    // Convert base64 to blob URL for memory management
                    const byteString = atob(sl.image.split(',')[1]);
                    const mime = sl.image.split(';')[0].split(':')[1] || 'image/jpeg';
                    const ab = new ArrayBuffer(byteString.length);
                    const ia = new Uint8Array(ab);
                    for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
                    const blob = new Blob([ab], {type: mime});
                    const url = URL.createObjectURL(blob);
                    _pdfBlobUrls.push(url);
                    img.src = url;
                }
            });
        } catch (e) {
            const slicesEl = document.getElementById(`pdf-slices-${hi}`);
            if (slicesEl) slicesEl.innerHTML = '<div class="text-red-500 text-xs p-2">加载失败</div>';
        }
    }
}

function _pdfZoomIn(imgEl) {
    // Create full-screen overlay, click background to close
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-8 cursor-pointer';
    overlay.id = 'pdf-zoom-overlay';
    const clone = imgEl.cloneNode(false); // clone img without children
    clone.className = 'max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl';
    clone.src = imgEl.src;
    clone.style.cursor = 'default';
    // Click overlay background (not image) → close
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });
    overlay.appendChild(clone);
    document.body.appendChild(overlay);
}

function _cleanupPdfSlices() {
    _pdfBlobUrls.forEach(url => URL.revokeObjectURL(url));
    _pdfBlobUrls = [];
}

function backToSearch() {
    _cleanupPdfSlices();
    const container = document.getElementById('main-content');
    renderSearchPage(container).then(() => {
        // Restore previous query if any
        const input = document.getElementById('search-input');
        if (input && _lastSearchQuery) {
            input.value = _lastSearchQuery;
            doSearch(_lastSearchQuery);
        }
    });
}
