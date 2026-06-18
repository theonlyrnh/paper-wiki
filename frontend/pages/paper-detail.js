/**
 * Paper detail page — markdown content, metadata, actions.
 */
async function renderPaperDetailPage(container, paperId) {
    container.innerHTML = `
        <div class="space-y-6">
            <!-- Skeleton header -->
            <div id="paper-header">
                <div class="animate-pulse space-y-3 mb-6">
                    <div class="h-4 bg-gray-700 rounded w-24"></div>
                    <div class="h-8 bg-gray-700 rounded w-2/3"></div>
                    <div class="flex gap-3 mt-3">
                        <div class="h-4 bg-gray-700 rounded w-32"></div>
                        <div class="h-4 bg-gray-700 rounded w-24"></div>
                    </div>
                </div>
            </div>
            <!-- Skeleton content -->
            <div id="paper-content">
                <div class="animate-pulse space-y-4">
                    <div class="h-6 bg-gray-700 rounded w-48"></div>
                    <div class="h-4 bg-gray-700 rounded w-full"></div>
                    <div class="h-4 bg-gray-700 rounded w-5/6"></div>
                    <div class="h-4 bg-gray-700 rounded w-4/5"></div>
                    <div class="h-4 bg-gray-700 rounded w-full"></div>
                    <div class="h-64 bg-gray-800 rounded-xl mt-4"></div>
                </div>
            </div>
        </div>
    `;

    try {
        const paper = await API.getPaper(paperId);

        // Header
        document.getElementById('paper-header').innerHTML = `
            <div class="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 w-full max-w-full min-w-0">
                <div class="min-w-0 flex-1 max-w-full">
                    <a href="#/papers" class="text-blue-400 hover:text-blue-300 text-sm mb-2 inline-block">← 返回列表</a>
                    <h2 class="text-2xl font-bold text-white break-words line-clamp-2 max-w-full">${escHtml(paper.title)}</h2>
                    <div class="text-gray-400 mt-2 flex items-center gap-3 flex-wrap text-sm min-w-0 max-w-full">
                        <span class="truncate max-w-full min-w-0">📄 ${escHtml(paper.filename)}</span>
                        ${paper.authors ? `<span class="truncate max-w-full min-w-0">👤 ${escHtml(paper.authors)}</span>` : ''}
                        ${paper.year ? `<span class="shrink-0">📅 ${paper.year}</span>` : ''}
                        <span class="status-badge status-${paper.status} shrink-0">${statusLabel(paper.status)}</span>
                        ${paper.raw_pdf_available
                            ? `<span class="shrink-0 text-xs px-2 py-0.5 rounded-full bg-blue-600/20 text-blue-300">原始 PDF ${formatRawPdfSize(paper.raw_pdf_size_mb)}</span>`
                            : `<span class="shrink-0 text-xs px-2 py-0.5 rounded-full bg-gray-700/60 text-gray-400">原始 PDF 已释放</span>`}
                    </div>
                    ${paper.tags && paper.tags.length ? `
                        <div class="flex gap-2 mt-2 flex-wrap min-w-0 max-w-full">
                            ${paper.tags.map(t => `<span class="px-2 py-1 bg-gray-700 rounded text-xs text-gray-300 max-w-full truncate">${escHtml(t)}</span>`).join('')}
                        </div>
                    ` : ''}
                </div>
                <div class="flex flex-wrap gap-2 shrink-0 sm:ml-4">
                    ${isRetryablePaperStatus(paper.status) ? `
                        <button onclick="retryPaperProcess('${paper.id}')"
                                class="px-3 py-2 bg-yellow-600/20 hover:bg-yellow-600/40 text-yellow-300 rounded-lg
                                       text-sm transition-colors shrink-0">
                            🔁 重新处理
                        </button>
                    ` : ''}
                    ${paper.status === 'done' ? `
                        <button onclick="triggerIngest('${paper.id}')"
                                class="px-3 py-2 bg-purple-600/20 hover:bg-purple-600/40 text-purple-400 rounded-lg
                                       text-sm transition-colors shrink-0">
                            🧠 摄入
                        </button>
                    ` : ''}
                    ${paper.status === 'done' && paper.raw_pdf_available ? `
                        <button onclick="deleteRawPdfConfirm('${paper.id}')"
                                class="px-3 py-2 bg-amber-600/20 hover:bg-amber-600/40 text-amber-300 rounded-lg
                                       text-sm transition-colors shrink-0">
                            🧹 删除原始 PDF
                        </button>
                    ` : ''}
                    <button onclick="deletePaperConfirm('${paper.id}')"
                            class="px-3 py-2 bg-red-600/20 hover:bg-red-600/40 text-red-400 rounded-lg
                                   text-sm transition-colors shrink-0">
                        🗑️ 删除
                    </button>
                </div>
            </div>
        `;

        // Wiki source link
        let wikiLink = '';
        if (paper.wiki_source_path) {
            const wikiName = paper.wiki_source_path.split('/').pop().replace('.md', '');
            wikiLink = `
                <div class="bg-purple-900/20 border border-purple-700/30 rounded-xl p-4 flex items-center gap-3">
                    <span class="text-2xl">📝</span>
                    <div>
                        <div class="text-purple-300 font-medium">Wiki 摘要已生成</div>
                        <div class="text-xs text-gray-500">${escHtml(paper.wiki_source_path)}</div>
                    </div>
                    <button onclick="showWikiSource('${wikiName}')"
                            class="ml-auto px-3 py-1.5 bg-purple-600/30 hover:bg-purple-600/50 rounded-lg
                                   text-sm text-purple-300 transition-colors">
                        查看 →
                    </button>
                </div>
            `;
        }

        // Content
        const contentEl = document.getElementById('paper-content');
        if (paper.status === 'failed') {
            contentEl.innerHTML = `
                ${wikiLink}
                <div class="bg-red-900/20 border border-red-800 rounded-xl p-6">
                    <h3 class="text-red-400 font-bold mb-2">❌ 解析失败</h3>
                    <p class="text-red-300">${escHtml(paper.error_msg || 'Unknown error')}</p>
                </div>
            `;
        } else if (paper.status === 'parsing' || paper.status === 'pending' || paper.status === 'ingesting') {
            contentEl.innerHTML = `
                ${wikiLink}
                <div class="bg-gray-800 rounded-xl p-8 text-center">
                    <div class="animate-spin text-5xl mb-4">⏳</div>
                    <p class="text-gray-400 text-lg">${statusLabel(paper.status)}...</p>
                    <p class="text-gray-600 text-sm mt-2">页面将在完成后自动刷新</p>
                </div>
            `;
            // Poll until terminal state
            const _poll = setInterval(async () => {
                try {
                    const p = await API.getPaper(paperId);
                    if (p.status === 'done' || p.status === 'failed') {
                        clearInterval(_poll);
                        renderPaperDetailPage(container, paperId);
                    }
                } catch (_) { clearInterval(_poll); }
            }, 5000);
            // Clean up if user navigates away
            window.addEventListener('hashchange', () => clearInterval(_poll), { once: true });
        } else if (paper.markdown_content) {
            contentEl.innerHTML = `
                ${wikiLink}
                <div class="bg-gray-800 rounded-xl overflow-hidden">
                    <div class="flex items-center justify-between px-6 py-3 border-b border-gray-700 bg-gray-850">
                        <div class="flex items-center gap-3">
                            <span class="text-gray-400 text-sm">
                                📝 ${paper.markdown_content.length.toLocaleString()} 字符
                            </span>
                        </div>
                        <span class="text-gray-600 text-xs">MinerU / pypdf 解析结果</span>
                    </div>
                    <div id="paper-markdown" class="px-6 py-6 prose prose-invert max-w-none markdown-body">
                    </div>
                </div>
            `;

            // Render markdown then KaTeX
            const mdEl = document.getElementById('paper-markdown');
            mdEl.innerHTML = MarkdownRenderer.render(paper.markdown_content);

            // KaTeX rendering
            if (typeof renderMathInElement !== 'undefined') {
                renderMathInElement(mdEl, {
                    delimiters: [
                        { left: '$$', right: '$$', display: true },
                        { left: '$', right: '$', display: false },
                        { left: '\\[', right: '\\]', display: true },
                        { left: '\\(', right: '\\)', display: false },
                    ],
                    throwOnError: false,
                });
            }
        } else {
            contentEl.innerHTML = `
                ${wikiLink}
                <div class="bg-gray-800 rounded-xl p-6 text-center text-gray-500">
                    暂无内容
                </div>
            `;
        }
    } catch (e) {
        container.innerHTML = `
            <div class="text-center py-12">
                <div class="text-red-400 text-lg">加载失败: ${e.message}</div>
                <a href="#/papers" class="text-blue-400 hover:text-blue-300 mt-4 inline-block">← 返回列表</a>
            </div>
        `;
    }
}

function formatRawPdfSize(value) {
    const n = Number(value || 0);
    if (n >= 1024) return `${(n / 1024).toFixed(2)}GB`;
    if (n >= 10) return `${n.toFixed(1)}MB`;
    return `${n.toFixed(3)}MB`;
}

async function triggerIngest(paperId) {
    if (!confirm('触发 LLM 摄入？将分析论文并生成 Wiki 页面。')) return;
    try {
        const resp = await fetch(`/api/papers/${paperId}/ingest`, { method: 'POST', credentials: 'include' });
        const data = await resp.json();
        if (resp.ok) {
            if (typeof Toast !== 'undefined') Toast.success('摄入已触发，请稍后查看 Wiki 页面');
            location.reload();
        } else {
            if (typeof Toast !== 'undefined') Toast.error(data.detail || 'Unknown error');
        }
    } catch (e) {
        if (typeof Toast !== 'undefined') Toast.error('请求失败: ' + e.message);
    }
}

async function retryPaperProcess(paperId, mode = 'auto') {
    try {
        const result = await API.retryPaper(paperId, mode);
        if (typeof Toast !== 'undefined') {
            Toast.success(result.mode === 'ingest' ? '已重新触发 Wiki 摄入' : '已重新触发 PDF 解析');
        }
        location.reload();
    } catch (e) {
        if (typeof Toast !== 'undefined' && e.message !== '请求已取消') {
            Toast.error('重新处理失败: ' + e.message);
        }
    }
}

async function deleteRawPdfConfirm(paperId) {
    const message = [
        '温馨提示：删除 PDF 只是为了释放空间，不会影响您的正常使用。',
        '',
        '论文内容已经转化为 Markdown；搜索、AI 问答、Wiki 等功能不受影响。',
        '系统会先缓存来源搜索需要的 PDF 图片切片，尽量避免搜索页面右侧来源截图消失。',
        '',
        '确认删除这篇论文的原始 PDF 吗？'
    ].join('\n');
    if (!confirm(message)) return;
    try {
        const result = await API.deleteRawPdf(paperId);
        if (typeof Toast !== 'undefined') {
            const freed = result.freed_mb ? `${Number(result.freed_mb).toFixed(3)}MB` : '空间';
            Toast.success(`原始 PDF 已删除，释放 ${freed}`);
        }
        const container = document.getElementById('main-content');
        renderPaperDetailPage(container, paperId);
    } catch (e) {
        if (typeof Toast !== 'undefined' && e.message !== '请求已取消') {
            Toast.error('删除原始 PDF 失败: ' + e.message);
        }
    }
}

async function showWikiSource(name) {
    const container = document.getElementById('main-content');
    try {
        const resp = await fetch(`/api/wiki/page/source/${name}`, { credentials: 'include' });
        if (!resp.ok) throw new Error('Page not found');
        const data = await resp.json();

        container.innerHTML = `
            <div class="space-y-4">
                <a href="#/papers" class="text-blue-400 hover:text-blue-300 text-sm">← 返回论文列表</a>
                <div class="flex items-center gap-2">
                    <span class="px-2 py-0.5 rounded-full bg-blue-600/30 text-blue-300 text-xs">source</span>
                    <h2 class="text-2xl font-bold text-white">${escHtml(data.title || name)}</h2>
                </div>
                <div id="wiki-source-content" class="bg-gray-800 rounded-xl px-6 py-6 prose prose-invert max-w-none markdown-body">
                </div>
            </div>
        `;

        const mdEl = document.getElementById('wiki-source-content');
        mdEl.innerHTML = MarkdownRenderer.render(data.content);
        if (typeof renderMathInElement !== 'undefined') {
            renderMathInElement(mdEl, {
                delimiters: [
                    { left: '$$', right: '$$', display: true },
                    { left: '$', right: '$', display: false },
                    { left: '\\[', right: '\\]', display: true },
                    { left: '\\(', right: '\\)', display: false },
                ],
                throwOnError: false,
            });
        }
    } catch (e) {
        if (typeof Toast !== 'undefined') Toast.error('加载失败: ' + e.message);
    }
}

async function deletePaperConfirm(paperId) {
    if (!confirm('确定要删除这篇论文吗？相关文件也会被删除。')) return;
    try {
        await API.deletePaper(paperId);
        if (typeof Toast !== 'undefined') Toast.success('论文已删除');
        window.location.hash = '#/papers';
    } catch (e) {
        if (typeof Toast !== 'undefined') Toast.error('删除失败: ' + e.message);
    }
}
