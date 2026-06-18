/**
 * Papers list page — upload (single/batch), list, filter.
 */
async function renderPapersPage(container) {
    container.innerHTML = `
        <div id="papers-page" class="page-shell space-y-6 w-full max-w-full min-w-0">
            <div class="flex flex-wrap items-center justify-between gap-2 w-full max-w-full min-w-0">
                <h2 class="text-2xl font-bold text-white min-w-0">📄 论文库</h2>
                <div class="flex gap-2 min-w-0">
                    <label class="cursor-pointer bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg
                                  flex items-center gap-2 transition-colors text-sm shrink-0">
                        <span>📤</span> 上传论文
                        <input type="file" id="upload-input" accept=".pdf" multiple class="hidden" />
                    </label>
                    <button onclick="showBatchProgress()"
                            class="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm text-gray-300 transition-colors shrink-0">
                        📊 进度
                    </button>
                </div>
            </div>

            <div id="upload-progress" class="hidden w-full max-w-full min-w-0 overflow-hidden bg-gray-800 rounded-xl p-4"></div>
            <div id="batch-progress" class="hidden w-full max-w-full min-w-0 overflow-hidden bg-gray-800 rounded-xl p-4"></div>

            <!-- Filter tabs: horizontal scroll on mobile -->
            <div class="flex gap-2 overflow-x-auto pb-1 w-full max-w-full min-w-0" id="filter-tabs">
                <button onclick="filterPapers(null)" data-filter=""
                        class="filter-tab shrink-0 px-3 py-1.5 rounded-lg text-sm transition-colors bg-blue-600 text-white">
                    全部
                </button>
                <button onclick="filterPapers('done')" data-filter="done"
                        class="filter-tab shrink-0 px-3 py-1.5 rounded-lg text-sm transition-colors bg-gray-700 text-gray-300 hover:bg-gray-600">
                    ✅ 完成
                </button>
                <button onclick="filterPapers('parsing')" data-filter="parsing"
                        class="filter-tab shrink-0 px-3 py-1.5 rounded-lg text-sm transition-colors bg-gray-700 text-gray-300 hover:bg-gray-600">
                    ⏳ 解析中
                </button>
                <button onclick="filterPapers('failed')" data-filter="failed"
                        class="filter-tab shrink-0 px-3 py-1.5 rounded-lg text-sm transition-colors bg-gray-700 text-gray-300 hover:bg-gray-600">
                    ❌ 失败
                </button>
            </div>

            <div id="papers-list" class="paper-list space-y-3 w-full max-w-full min-w-0">
                <div class="text-gray-500 animate-pulse">加载中...</div>
            </div>
        </div>
    `;

    // Upload handler (supports multiple files)
    document.getElementById('upload-input').addEventListener('change', async (e) => {
        const files = Array.from(e.target.files);
        if (files.length === 0) return;

        const prog = document.getElementById('upload-progress');
        prog.classList.remove('hidden');

        if (files.length === 1) {
            PixelUploader.show('upload-progress', 'uploading');
            try {
                const result = await API.uploadPaper(files[0]);
                PixelUploader.setStatus('parsing');
                // Poll for paper status
                const poll = setInterval(async () => {
                    try {
                        const papers = await API.listPapers(1, 5);
                        const p = papers.find(pp => pp.id === result.id);
                        if (p) {
                            if (p.status === 'done') {
                                clearInterval(poll);
                                PixelUploader.setStatus('done');
                                loadPapersList();
                            } else if (p.status === 'failed') {
                                clearInterval(poll);
                                PixelUploader.setStatus('failed');
                                loadPapersList();
                            } else {
                                PixelUploader.setStatus(p.status);
                            }
                        }
                    } catch(e) {}
                }, 2000);
            } catch (err) {
                PixelUploader.setStatus('failed');
                setTimeout(() => PixelUploader.hide(), 5000);
            }
        } else {
            // Batch upload
            prog.innerHTML = `
                <div class="flex items-center gap-3 min-w-0">
                    <div class="animate-spin text-blue-400 text-xl">⏳</div>
                    <span class="text-gray-300 min-w-0 truncate">正在上传 ${files.length} 个文件...</span>
                </div>`;
            try {
                const form = new FormData();
                files.forEach(f => form.append('files', f));
                const resp = await fetch('/api/batch/upload', { method: 'POST', credentials: 'include', body: form });
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.detail || 'Upload failed');

                const accepted = data.results.filter(r => r.status === 'queued').length;
                const skipped = data.results.filter(r => r.status === 'skipped').length;
                const rejected = data.results.filter(r => r.status === 'rejected').length;

                prog.innerHTML = `
                    <div class="space-y-2">
                        <div class="${rejected ? 'text-amber-400' : 'text-green-400'}">
                            ✅ 批量上传完成: ${accepted} 篇已接受${skipped ? `, ${skipped} 篇跳过(重复)` : ''}${rejected ? `, ${rejected} 篇因空间不足被拒绝` : ''}
                        </div>
                        <div class="space-y-1">
                            ${data.results.map(r => `
                                <div class="flex items-center gap-2 text-sm min-w-0">
                                    <span class="${r.status === 'rejected' ? 'text-red-400' : r.status === 'skipped' ? 'text-yellow-400' : 'text-green-400'} shrink-0">
                                        ${r.status === 'rejected' ? '🚫' : r.status === 'skipped' ? '⏭️' : '✅'}
                                    </span>
                                    <span class="text-gray-300 min-w-0 flex-1 truncate">${escHtml(r.filename)}</span>
                                    <span class="text-gray-600 shrink-0 truncate max-w-[40%]">${r.message}</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>`;
                API.refreshStorageQuota().catch(() => {});
                setTimeout(() => { prog.classList.add('hidden'); loadPapersList(); }, 4000);
                // Start auto-polling for batch progress
                startBatchAutoPoll();
            } catch (err) {
                prog.innerHTML = `<div class="text-red-400">❌ 批量上传失败: ${err.message}</div>`;
            }
        }
        e.target.value = '';  // Reset input
    });

    await loadPapersList();
}

let currentFilter = null;

function filterPapers(status) {
    currentFilter = status;
    // Update tab styles
    document.querySelectorAll('.filter-tab').forEach(tab => {
        const f = tab.getAttribute('data-filter');
        if (f === (status || '')) {
            tab.className = 'filter-tab shrink-0 px-3 py-1.5 rounded-lg text-sm transition-colors bg-blue-600 text-white';
        } else {
            tab.className = 'filter-tab shrink-0 px-3 py-1.5 rounded-lg text-sm transition-colors bg-gray-700 text-gray-300 hover:bg-gray-600';
        }
    });
    loadPapersList();
}

async function loadPapersList() {
    const el = document.getElementById('papers-list');
    try {
        const papers = await API.listPapers(1, 100, currentFilter);
        // Auto-start batch poll if any papers are processing
        const processing = papers.filter(p => ['pending', 'parsing', 'ingesting'].includes(p.status));
        if (processing.length > 0 && !_batchPollTimer) {
            startBatchAutoPoll();
        }
        if (papers.length === 0) {
            el.innerHTML = `
                <div class="text-center py-12">
                    <div class="text-6xl mb-4">${currentFilter ? '🔍' : '📭'}</div>
                    <div class="text-gray-400 text-lg">${currentFilter ? '没有匹配的论文' : '论文库为空'}</div>
                    ${!currentFilter ? '<div class="text-gray-600 mt-2">点击右上角「上传论文」开始</div>' : ''}
                </div>`;
            return;
        }
        el.innerHTML = papers.map((p, i) => `
            <a href="#/papers/${p.id}"
               class="paper-list-item block w-full max-w-full min-w-0 overflow-hidden bg-gray-800 rounded-xl p-4 hover:bg-gray-750 hover:shadow-lg hover:shadow-black/20
                      hover:-translate-y-0.5 transition-all duration-200 group">
                <div class="flex items-start gap-3 w-full max-w-full min-w-0">
                    <span class="paper-icon text-xl shrink-0 mt-0.5 group-hover:scale-110 transition-transform duration-200">📄</span>
                    <div class="paper-card-body min-w-0 flex-1 max-w-full">
                        <div class="paper-title text-white font-semibold text-base line-clamp-2 break-words
                                    group-hover:text-blue-300 transition-colors leading-snug">
                            ${escHtml(p.title)}
                        </div>
                        <div class="paper-meta text-sm text-gray-500 mt-1 truncate">
                            ${p.authors ? escHtml(p.authors) + ' · ' : ''}
                            ${p.year || ''} · ${escHtml(p.filename)}
                        </div>
                        <div class="flex items-center gap-3 mt-2 min-w-0">
                            <span class="status-badge status-${p.status} shrink-0">${statusLabel(p.status)}</span>
                            <span class="text-gray-600 text-xs truncate min-w-0 flex-1">${p.created_at.split(' ')[0]}</span>
                            ${isRetryablePaperStatus(p.status) ? `
                                <button type="button"
                                        onclick="retryPaperFromList(event, '${p.id}')"
                                        class="shrink-0 px-2 py-1 rounded-lg bg-yellow-600/20 hover:bg-yellow-600/40
                                               text-yellow-300 text-xs transition-colors">
                                    🔁 重试
                                </button>
                            ` : ''}
                            ${p.status === 'done' && p.raw_pdf_available ? `
                                <button type="button"
                                        onclick="deleteRawPdfFromList(event, '${p.id}')"
                                        class="shrink-0 px-2 py-1 rounded-lg bg-amber-600/20 hover:bg-amber-600/40
                                               text-amber-300 text-xs transition-colors">
                                    🧹 释放 PDF
                                </button>
                            ` : ''}
                            ${p.status === 'done' && !p.raw_pdf_available ? `
                                <span class="shrink-0 text-[11px] text-gray-600">PDF 已释放</span>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </a>
        `).join('');
    } catch (e) {
        el.innerHTML = `<div class="text-red-400">加载失败: ${e.message}</div>`;
    }
}

function isRetryablePaperStatus(status) {
    return ['failed', 'parsing', 'pending', 'ingesting'].includes(status);
}

async function retryPaperFromList(event, paperId) {
    event.preventDefault();
    event.stopPropagation();
    try {
        const result = await API.retryPaper(paperId);
        if (typeof Toast !== 'undefined') {
            Toast.success(result.mode === 'ingest' ? '已重新触发 Wiki 摄入' : '已重新触发 PDF 解析');
        }
        await loadPapersList();
    } catch (e) {
        if (typeof Toast !== 'undefined' && e.message !== '请求已取消') {
            Toast.error('重试失败: ' + e.message);
        }
    }
}

async function deleteRawPdfFromList(event, paperId) {
    event.preventDefault();
    event.stopPropagation();
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
        await loadPapersList();
    } catch (e) {
        if (typeof Toast !== 'undefined' && e.message !== '请求已取消') {
            Toast.error('删除原始 PDF 失败: ' + e.message);
        }
    }
}

async function showBatchProgress() {
    const el = document.getElementById('batch-progress');
    el.classList.toggle('hidden');
    if (el.classList.contains('hidden')) {
        stopBatchAutoPoll();
        return;
    }
    await refreshBatchProgress();
}

let _batchPollTimer = null;
let _listRefreshTimer = null;

function startBatchAutoPoll() {
    stopBatchAutoPoll();
    const el = document.getElementById('batch-progress');
    el.classList.remove('hidden');
    refreshBatchProgress();
    _batchPollTimer = setInterval(refreshBatchProgress, 3000);
    // Also refresh the paper list every 5 seconds
    if (!_listRefreshTimer) {
        _listRefreshTimer = setInterval(() => {
            loadPapersList();
        }, 5000);
    }
}

function stopBatchAutoPoll() {
    if (_batchPollTimer) {
        clearInterval(_batchPollTimer);
        _batchPollTimer = null;
    }
    if (_listRefreshTimer) {
        clearInterval(_listRefreshTimer);
        _listRefreshTimer = null;
    }
}

async function refreshBatchProgress() {
    const el = document.getElementById('batch-progress');
    if (el.classList.contains('hidden')) return;

    try {
        const resp = await fetch('/api/batch/progress', { credentials: 'include' });
        const data = await resp.json();
        const inProgress = data.in_progress || 0;
        const total = data.total || 0;
        const done = data.done || 0;
        const failed = data.failed || 0;
        const pending = (data.by_status?.pending || 0) + (data.by_status?.parsing || 0);
        const ingesting = data.by_status?.ingesting || 0;
        const pct = total > 0 ? Math.round((done + failed) / total * 100) : 0;

        el.innerHTML = `
            <div class="space-y-3">
                <div class="flex items-center justify-between">
                    <span class="text-gray-400 text-sm">批量处理进度</span>
                    ${inProgress > 0 ? `<span class="text-xs text-blue-300 animate-pulse">⏳ 处理中...</span>` : `<span class="text-xs text-gray-500">✅ 全部完成</span>`}
                </div>
                <div class="w-full bg-gray-700 rounded-full h-2">
                    <div class="h-2 rounded-full transition-all duration-500 ${failed > 0 ? 'bg-gradient-to-r from-green-500 via-yellow-500 to-red-500' : 'bg-green-500'}" style="width: ${pct}%"></div>
                </div>
                <div class="grid grid-cols-4 gap-3 text-center w-full max-w-full min-w-0">
                    <div class="min-w-0"><div class="text-xl font-bold text-white truncate">${total}</div><div class="text-xs text-gray-500 truncate">总计</div></div>
                    <div class="min-w-0"><div class="text-xl font-bold text-green-400 truncate">${done}</div><div class="text-xs text-gray-500 truncate">✅ 完成</div></div>
                    <div class="min-w-0">
                        <div class="text-xl font-bold text-blue-400 truncate">${inProgress}</div>
                        <div class="text-xs text-gray-500 truncate">⏳ 处理中</div>
                        ${pending > 0 ? `<div class="text-[10px] text-gray-600">排队 ${pending}</div>` : ''}
                        ${ingesting > 0 ? `<div class="text-[10px] text-gray-600">摄入 ${ingesting}</div>` : ''}
                    </div>
                    <div class="min-w-0"><div class="text-xl font-bold text-red-400 truncate">${failed}</div><div class="text-xs text-gray-500 truncate">❌ 失败</div></div>
                </div>
                ${inProgress > 0 ? `
                    <div class="text-center text-xs text-gray-500">每 3 秒自动刷新 · 每篇约 2-4 分钟</div>
                ` : `
                    <div class="text-center">
                        <button onclick="stopBatchAutoPoll(); document.getElementById('batch-progress').classList.add('hidden'); loadPapersList();"
                                class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm text-gray-300 transition-colors">
                            关闭
                        </button>
                    </div>
                `}
            </div>
        `;

        // Auto-stop when all done
        if (inProgress === 0 && total > 0) {
            stopBatchAutoPoll();
            loadPapersList();
        }
    } catch (e) {
        el.innerHTML = `<div class="text-red-400 text-sm">${e.message}</div>`;
    }
}
