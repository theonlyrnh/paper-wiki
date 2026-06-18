/**
 * Chat page — multi-turn conversation with knowledge base.
 */
let chatSessionId = null;

async function renderChatPage(container) {
    container.innerHTML = `
        <div id="chat-page" class="flex flex-col h-full min-h-0 w-full max-w-full overflow-hidden">
            <!-- Header -->
            <div class="flex items-center justify-between gap-3 mb-4 shrink-0 min-w-0">
                <h2 class="text-2xl font-bold text-white">💬 对话</h2>
                <div class="flex gap-2 shrink-0">
                    <button onclick="newChatSession()"
                            class="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm text-white transition-colors shrink-0">
                        ✚ 新对话
                    </button>
                    <button onclick="loadChatHistory()"
                            class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm text-gray-300 transition-colors shrink-0">
                        📜 历史
                    </button>
                </div>
            </div>

            <!-- Session selector (hidden by default) -->
            <div id="chat-sessions-panel" class="hidden mb-4 bg-gray-800 rounded-xl p-3 max-h-48 overflow-y-auto shrink-0 min-w-0"></div>

            <!-- Messages area -->
            <div id="chat-messages" class="flex-1 min-h-0 min-w-0 w-full max-w-full overflow-y-auto overflow-x-hidden space-y-4 mb-4 pr-2 overscroll-contain">
                <div class="text-center py-12">
                    <div class="text-5xl mb-4">🤖</div>
                    <div class="text-gray-400 text-lg">你好！我是论文知识库 AI 助手。</div>
                    <div class="text-gray-600 mt-2">输入问题，我会基于知识库内容为你解答。</div>
                    <div class="flex flex-wrap justify-center gap-2 mt-6">
                        <button onclick="sendSuggestion('Transformer 的核心架构是什么？')"
                                class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm text-gray-300 transition-colors">
                            Transformer 的核心架构是什么？
                        </button>
                        <button onclick="sendSuggestion('多头注意力机制如何工作？')"
                                class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm text-gray-300 transition-colors">
                            多头注意力机制如何工作？
                        </button>
                        <button onclick="sendSuggestion('这篇论文的主要贡献有哪些？')"
                                class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm text-gray-300 transition-colors">
                            这篇论文的主要贡献有哪些？
                        </button>
                    </div>
                </div>
            </div>

            <!-- Input area -->
            <div id="chat-input-bar" class="flex gap-3 items-end shrink-0 min-w-0 w-full max-w-full">
                <div class="flex-1 min-w-0 relative">
                    <textarea id="chat-input"
                              placeholder="输入你的问题... (Enter 发送, Shift+Enter 换行)"
                              rows="1"
                              class="w-full bg-gray-800 border border-gray-600 rounded-xl px-4 py-3
                                     text-white placeholder-gray-500 focus:outline-none focus:border-blue-500
                                     focus:ring-2 focus:ring-blue-500/20 resize-none"
                              style="max-height: 120px;"></textarea>
                </div>
                <button id="chat-send-btn" onclick="sendMessage()"
                        class="px-5 py-3 bg-blue-600 hover:bg-blue-700 rounded-xl text-white
                               font-medium transition-colors flex items-center gap-2 shrink-0
                               disabled:opacity-50 disabled:cursor-not-allowed">
                    <span>发送</span>
                    <span>↵</span>
                </button>
            </div>
        </div>
    `;

    // Auto-resize textarea
    const textarea = document.getElementById('chat-input');
    textarea.addEventListener('input', () => {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    });

    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    textarea.focus();
}

function sendSuggestion(text) {
    document.getElementById('chat-input').value = text;
    sendMessage();
}

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send-btn');
    const text = input.value.trim();
    if (!text) return;

    const messagesEl = document.getElementById('chat-messages');

    // Clear welcome if first message
    if (messagesEl.querySelector('.text-center.py-12')) {
        messagesEl.innerHTML = '';
    }

    // Add user message
    appendMessage('user', text);
    input.value = '';
    input.style.height = 'auto';

    // Disable send
    sendBtn.disabled = true;

    // Add loading indicator
    const loadingId = 'loading-' + Date.now();
    messagesEl.insertAdjacentHTML('beforeend', `
        <div id="${loadingId}" class="flex items-start gap-3">
            <div class="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center shrink-0 text-sm">🤖</div>
            <div class="bg-gray-800 rounded-xl px-4 py-3 max-w-3xl">
                <div class="flex items-center gap-2 text-gray-400">
                    <div class="animate-pulse">思考中</div>
                    <span class="animate-bounce">.</span>
                    <span class="animate-bounce" style="animation-delay:0.1s">.</span>
                    <span class="animate-bounce" style="animation-delay:0.2s">.</span>
                </div>
            </div>
        </div>
    `);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                content: text,
                session_id: chatSessionId,
            }),
        });

        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        // Save session ID
        chatSessionId = data.session_id;

        // Remove loading
        document.getElementById(loadingId)?.remove();

        // Add assistant message
        appendMessage('assistant', data.message.content, data.message.references);

    } catch (e) {
        document.getElementById(loadingId)?.remove();
        appendMessage('assistant', `❌ 请求失败: ${e.message}`, []);
    }

    sendBtn.disabled = false;
    input.focus();
}

function appendMessage(role, content, references) {
    const messagesEl = document.getElementById('chat-messages');
    const isUser = role === 'user';
    const msgId = 'msg-' + Date.now();

    // Render markdown with KaTeX
    const rendered = isUser ? escHtml(content) : MarkdownRenderer.render(content);

    // Format references panel
    let refsHtml = '';
    if (references && references.length > 0) {
        refsHtml = `
            <details class="mt-3 border-t border-gray-700 pt-2">
                <summary class="text-xs text-gray-500 cursor-pointer hover:text-gray-300">
                    📚 引用来源 (${references.length}) <span class="text-[10px] text-gray-600">— 点击查看 PDF 原文</span>
                </summary>
                <div class="mt-2 space-y-1" id="refs-${msgId}">
                    ${references.map(r => `
                        <div class="flex items-center gap-2 text-xs py-1 px-2 rounded cursor-pointer
                                    hover:bg-gray-700/50 transition-colors group"
                             data-ref-name="${escHtml(r.name)}"
                             data-ref-type="${escHtml(r.type)}"
                             data-ref-title="${escHtml(r.title)}">
                            <span class="text-gray-600 shrink-0">[${r.index}]</span>
                            <span class="px-1.5 py-0.5 rounded text-[10px] shrink-0 ${typeBadgeColor(r.type)}">${escHtml(r.type)}</span>
                            <span class="text-gray-300 group-hover:text-white transition-colors">${escHtml(r.title)}</span>
                            <span class="text-gray-700 text-[10px] ml-auto shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">📄</span>
                        </div>
                    `).join('')}
                </div>
            </details>
        `;
    }

    const msgDiv = document.createElement('div');
    msgDiv.id = msgId;
    msgDiv.className = `flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`;
    msgDiv.innerHTML = `
            <div class="w-8 h-8 rounded-full ${isUser ? 'bg-blue-600' : 'bg-purple-600'}
                        flex items-center justify-center shrink-0 text-sm">
                ${isUser ? '👤' : '🤖'}
            </div>
            <div class="max-w-3xl">
                <div class="${isUser ? 'bg-blue-600/20 border border-blue-500/30' : 'bg-gray-800'}
                            rounded-xl px-4 py-3">
                    <div class="prose prose-invert max-w-none markdown-body text-sm leading-relaxed">
                        ${rendered}
                    </div>
                    ${refsHtml}
                </div>
            </div>
    `;
    messagesEl.appendChild(msgDiv);

    // Attach ref click handlers via event delegation
    if (refsHtml) {
        const refsContainer = document.getElementById('refs-' + msgId);
        if (refsContainer) {
            refsContainer.addEventListener('click', (e) => {
                const target = e.target.closest('[data-ref-name]');
                if (!target) return;
                const name = target.getAttribute('data-ref-name');
                const type = target.getAttribute('data-ref-type');
                _chatShowPdfSlices(name, type, target);
            });
        }
    }

    // Re-render KaTeX in the new message
    if (!isUser && typeof renderMathInElement !== 'undefined') {
        const msgEl = document.getElementById(msgId);
        if (msgEl) {
            renderMathInElement(msgEl, {
                delimiters: [
                    { left: '$$', right: '$$', display: true },
                    { left: '$', right: '$', display: false },
                    { left: '\\[', right: '\\]', display: true },
                    { left: '\\(', right: '\\)', display: false },
                ],
                throwOnError: false,
            });
        }
    }

    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function newChatSession() {
    chatSessionId = null;
    renderChatPage(document.getElementById('main-content'));
}

async function loadChatHistory() {
    const panel = document.getElementById('chat-sessions-panel');
    panel.classList.toggle('hidden');

    if (panel.classList.contains('hidden')) return;

    try {
        const resp = await fetch('/api/chat/sessions', { credentials: 'include' });
        const sessions = await resp.json();

        if (sessions.length === 0) {
            panel.innerHTML = '<div class="text-gray-500 text-sm text-center py-2">暂无历史对话</div>';
            return;
        }

        panel.innerHTML = `
            <div class="text-gray-400 text-xs mb-2">历史对话</div>
            <div class="space-y-1">
                ${sessions.map(s => `
                    <button onclick="loadSession('${s.id}', '${escHtml(s.title)}')"
                            class="w-full text-left px-3 py-2 rounded-lg hover:bg-gray-700 transition-colors
                                   flex items-center justify-between ${chatSessionId === s.id ? 'bg-gray-700' : ''}">
                        <span class="text-gray-300 text-sm truncate">${escHtml(s.title)}</span>
                        <div class="flex items-center gap-2">
                            <span class="text-gray-600 text-xs">${s.updated_at.split(' ')[0]}</span>
                            <button onclick="event.stopPropagation(); deleteSession('${s.id}')"
                                    class="text-gray-600 hover:text-red-400 text-xs">🗑</button>
                        </div>
                    </button>
                `).join('')}
            </div>
        `;
    } catch (e) {
        panel.innerHTML = `<div class="text-red-400 text-sm">${e.message}</div>`;
    }
}

async function loadSession(sessionId, title) {
    chatSessionId = sessionId;
    document.getElementById('chat-sessions-panel').classList.add('hidden');

    const messagesEl = document.getElementById('chat-messages');
    messagesEl.innerHTML = '<div class="text-center py-4 text-gray-400 animate-pulse">加载对话...</div>';

    try {
        const resp = await fetch(`/api/chat/sessions/${sessionId}/messages`, { credentials: 'include' });
        const messages = await resp.json();

        messagesEl.innerHTML = '';
        for (const msg of messages) {
            appendMessage(msg.role, msg.content, msg.references);
        }
    } catch (e) {
        messagesEl.innerHTML = `<div class="text-red-400 text-center py-4">${e.message}</div>`;
    }
}

async function deleteSession(sessionId) {
    if (!confirm('确定删除这个对话？')) return;
    try {
        await fetch(`/api/chat/sessions/${sessionId}`, { method: 'DELETE', credentials: 'include' });
        if (chatSessionId === sessionId) newChatSession();
        else loadChatHistory();
    } catch (e) {
        if (typeof Toast !== 'undefined') Toast.error('删除失败: ' + e.message);
    }
}

/**
 * Show PDF slices in an overlay for a clicked chat reference.
 */
async function _chatShowPdfSlices(name, type, clickedEl) {
    // Prevent duplicate overlays
    const existing = document.getElementById('chat-pdf-overlay');
    if (existing) existing.remove();

    // Normalize: strip user prefix (u1_), normalize type to singular
    let cleanName = name.replace(/^u\d+_/, '');
    const _TYPE_SINGULAR = { sources: 'source', entities: 'entity', concepts: 'concept' };
    let cleanType = _TYPE_SINGULAR[type] || type;

    // Create overlay
    const overlay = document.createElement('div');
    overlay.id = 'chat-pdf-overlay';
    overlay.className = 'fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6 cursor-pointer';
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            overlay.querySelectorAll('img').forEach(img => {
                if (img._blobUrl) URL.revokeObjectURL(img._blobUrl);
            });
            overlay.remove();
        }
    });

    const panel = document.createElement('div');
    panel.className = 'bg-gray-900 rounded-2xl border border-gray-700 max-w-lg w-full max-h-[85vh] overflow-y-auto p-5 shadow-2xl';
    panel.style.cursor = 'default';
    panel.innerHTML = `
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-white font-semibold text-sm truncate pr-4">${escHtml(cleanName.replace(/-/g, ' '))}</h3>
            <button onclick="document.getElementById('chat-pdf-overlay').remove()" class="text-gray-500 hover:text-white text-lg shrink-0">✕</button>
        </div>
        <div id="chat-pdf-slices-content" class="space-y-3">
            <div class="text-center py-8 text-gray-500 text-sm animate-pulse">加载 PDF 原文...</div>
        </div>
    `;
    panel.addEventListener('click', (e) => e.stopPropagation());
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    const content = document.getElementById('chat-pdf-slices-content');

    try {
        // 1. Fetch wiki page to get source_highlights
        const wikiResp = await fetch(`/api/wiki/page/${cleanType}/${cleanName}`, { credentials: 'include' });
        if (!wikiResp.ok) throw new Error('Wiki page not found');
        const wikiData = await wikiResp.json();

        const sourceHighlights = wikiData.source_highlights || [];
        if (!sourceHighlights.length) {
            content.innerHTML = '<div class="text-gray-500 text-center py-6 text-sm">暂无来源论文</div>';
            return;
        }

        // 2. Build slice containers
        content.innerHTML = sourceHighlights.map((h, i) => `
            <div class="bg-gray-800 rounded-xl border border-gray-700/50 overflow-hidden">
                <div class="px-3 py-1.5 bg-gray-700/50 border-b border-gray-700/30">
                    <span class="text-xs text-blue-400">📄 ${escHtml((h.paper_title || '').slice(0, 50))}</span>
                </div>
                <div id="chat-slices-${i}" class="p-2 space-y-2">
                    <div class="text-center py-4 text-gray-600 text-xs animate-pulse">加载切片...</div>
                </div>
            </div>
        `).join('');

        // 3. Fetch PDF highlights for each source
        const searchQuery = wikiData.title || cleanName;
        for (let i = 0; i < sourceHighlights.length; i++) {
            const h = sourceHighlights[i];
            const slicesEl = document.getElementById(`chat-slices-${i}`);
            if (!slicesEl || !h.paper_id) continue;

            try {
                const hlResp = await fetch(`/api/papers/${h.paper_id}/pdf-highlights`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        snippets: (h.highlights || []).map(hl => ({
                            text: hl.text, start_line: hl.start_line, end_line: hl.end_line
                        })),
                        query: searchQuery,
                    }),
                });
                if (!hlResp.ok) {
                    slicesEl.innerHTML = '<div class="text-gray-600 text-xs text-center py-3">加载失败</div>';
                    continue;
                }
                const hlData = await hlResp.json();
                const slices = hlData.slices || [];

                if (!slices.length) {
                    if (hlData.pdf_available === false) {
                        slicesEl.innerHTML = typeof pdfCleanedFallbackHtml === 'function'
                            ? pdfCleanedFallbackHtml()
                            : '<div class="text-gray-500 text-xs text-center py-3">原始 PDF 已释放，相关内容已转为 Markdown / Wiki。</div>';
                        continue;
                    }
                    slicesEl.innerHTML = '<div class="text-gray-600 text-xs text-center py-3">未找到匹配段落</div>';
                    continue;
                }

                slicesEl.innerHTML = slices.map((sl, si) => {
                    const imgId = `chat-pdf-img-${i}-${si}`;
                    return `
                        <div class="cursor-pointer hover:ring-2 ring-amber-500/30 rounded overflow-hidden transition-all"
                             onclick="_chatZoomSlice(this.querySelector('img'))">
                            <div class="flex items-center justify-between px-1 mb-1">
                                <span class="text-[10px] text-gray-600">第 ${sl.page} 页 · 匹配 ${sl.score}%${hlData.cache_status === 'hit' ? ' · 缓存' : ''}</span>
                            </div>
                            <img id="${imgId}" class="w-full rounded border border-gray-700/30" alt="Page ${sl.page}" loading="lazy">
                        </div>
                    `;
                }).join('');

                // Load images as blob URLs
                slices.forEach((sl, si) => {
                    const img = document.getElementById(`chat-pdf-img-${i}-${si}`);
                    if (img && sl.image) {
                        const byteString = atob(sl.image.split(',')[1]);
                        const mime = sl.image.split(';')[0].split(':')[1] || 'image/jpeg';
                        const ab = new ArrayBuffer(byteString.length);
                        const ia = new Uint8Array(ab);
                        for (let j = 0; j < byteString.length; j++) ia[j] = byteString.charCodeAt(j);
                        const blob = new Blob([ab], { type: mime });
                        const url = URL.createObjectURL(blob);
                        img.src = url;
                        img._blobUrl = url;
                    }
                });
            } catch (e) {
                slicesEl.innerHTML = '<div class="text-red-500 text-xs p-2">加载失败</div>';
            }
        }
    } catch (e) {
        content.innerHTML = `<div class="text-red-400 text-center py-6 text-sm">${e.message}</div>`;
    }
}

function _chatZoomSlice(imgEl) {
    const overlay = document.getElementById('chat-pdf-overlay');
    if (!overlay) return;
    const zoom = document.createElement('div');
    zoom.id = 'chat-pdf-zoom';
    zoom.className = 'fixed inset-0 z-[60] bg-black/90 flex items-center justify-center p-8 cursor-pointer';
    const clone = document.createElement('img');
    clone.className = 'max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl';
    clone.src = imgEl.src;
    clone.style.cursor = 'default';
    zoom.addEventListener('click', (e) => {
        if (e.target === zoom) zoom.remove();
    });
    zoom.appendChild(clone);
    document.body.appendChild(zoom);
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
