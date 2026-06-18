/**
 * Settings page — personal settings, theme, model config, admin management.
 */
async function renderSettingsPage(container) {
    const user = API.currentUser;
    const isAdmin = API.isAdmin();
    const canInvite = API.canInvite();
    const config = await API.getConfig().catch(() => ({}));

    let adminHtml = '';

    if (canInvite) {
        adminHtml += `
        <div class="bg-gray-800/80 backdrop-blur rounded-2xl border border-amber-700/30 p-6 space-y-4">
            <div class="flex items-center justify-between">
                <h3 class="text-lg font-semibold text-amber-400">🎟️ 邀请码管理</h3>
                <div class="flex gap-2">
                    <select id="inv-count" class="px-3 py-1.5 bg-gray-900/50 border border-gray-700 rounded-lg text-white text-sm"><option value="1">1 个</option><option value="3" selected>3 个</option><option value="5">5 个</option><option value="10">10 个</option></select>
                    <select id="inv-days" class="px-3 py-1.5 bg-gray-900/50 border border-gray-700 rounded-lg text-white text-sm"><option value="7">7 天</option><option value="30" selected>30 天</option><option value="90">90 天</option></select>
                    <button id="btn-gen-inv" class="px-4 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-sm font-medium transition-all active:scale-[0.98]">生成邀请码</button>
                </div>
            </div>
            <div id="inv-new-codes" class="hidden"><p class="text-sm text-gray-400 mb-2">新邀请码（点击复制）：</p><div id="inv-new-list" class="flex flex-wrap gap-2"></div></div>
            <div id="inv-list" class="text-gray-500 text-sm">加载中...</div>
        </div>`;
    }

    if (isAdmin) {
        adminHtml += `
        <div class="bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-6 space-y-4">
            <h3 class="text-lg font-semibold text-white">👥 用户管理</h3>
            <div id="user-list" class="text-gray-500 text-sm">加载中...</div>
        </div>`;
    }

    container.innerHTML = `
        <div class="space-y-6">
            <h2 class="text-2xl font-bold text-white">⚙️ 设置</h2>

            <!-- Personal -->
            <div class="bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-6 space-y-4">
                <h3 class="text-lg font-semibold text-white">👤 个人信息</h3>
                <div class="grid grid-cols-2 gap-4 text-sm">
                    <div><span class="text-gray-500">用户名:</span> <span class="text-white">${escHtml(user?.username||'')}</span></div>
                    <div><span class="text-gray-500">昵称:</span> <span class="text-white">${escHtml(user?.nickname||'')}</span></div>
                    <div><span class="text-gray-500">角色:</span> <span class="text-amber-400">${isAdmin?'管理员':'普通用户'}</span></div>
                    <div><span class="text-gray-500">邀请权限:</span> <span class="${canInvite?'text-emerald-400':'text-gray-600'}">${canInvite?'✅ 有':'❌ 无'}</span></div>
                </div>
                <form id="nick-form" class="flex gap-2 max-w-sm pt-2">
                    <input type="text" id="nick-input" value="${escHtml(user?.nickname||'')}" placeholder="修改昵称"
                           class="flex-1 px-4 py-2 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50">
                    <button type="submit" class="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-xl text-sm transition-all">保存</button>
                </form>
            </div>

            <!-- Theme -->
            <div class="bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-6 space-y-4">
                <h3 class="text-lg font-semibold text-white">🎨 主题</h3>
                <div class="flex gap-4">
                    <button id="btn-theme-dark" class="px-5 py-3 rounded-xl border transition-all text-sm font-medium ${(config.theme||'dark')==='dark'?'bg-blue-600 border-blue-500 text-white':'bg-gray-900/50 border-gray-700 text-gray-400'}">🌙 暗色模式</button>
                    <button id="btn-theme-light" class="px-5 py-3 rounded-xl border transition-all text-sm font-medium ${config.theme==='light'?'bg-amber-500 border-amber-400 text-white':'bg-gray-900/50 border-gray-700 text-gray-400'}">☀️ 亮色模式</button>
                </div>
            </div>

            <!-- LLM Model Config -->
            <div class="bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-6 space-y-4">
                <h3 class="text-lg font-semibold text-white flex items-center gap-2">🤖 LLM 模型配置</h3>
                <p class="text-gray-500 text-sm">配置你自己的 LLM API，用于论文分析和对话。</p>
                <div class="space-y-3 max-w-xl">
                    <div>
                        <label class="block text-xs text-gray-500 mb-1">Base URL</label>
                        <input type="text" id="llm-base-url" value="${escHtml(config.llm_base_url||'')}"
                               class="w-full px-4 py-2.5 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                               placeholder="https://api.openai.com/v1">
                    </div>
                    <div>
                        <label class="block text-xs text-gray-500 mb-1">API Key <span id="llm-key-status" class="text-gray-600">${config.llm_api_key?'(已设置, 仅显示后4位)':''}</span></label>
                        <input type="password" id="llm-api-key" value="${escHtml(config.llm_api_key||'')}"
                               class="w-full px-4 py-2.5 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                               placeholder="sk-...">
                    </div>
                    <div>
                        <label class="block text-xs text-gray-500 mb-1">模型</label>
                        <div class="flex gap-2">
                            <select id="llm-model-select" class="flex-1 px-4 py-2.5 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50">
                                <option value="">${config.llm_model ? config.llm_model + ' (当前)' : '— 手动输入或获取列表 —'}</option>
                            </select>
                        </div>
                        <input type="text" id="llm-model-input" value="${escHtml(config.llm_model||'')}"
                               class="w-full px-4 py-2.5 mt-2 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                               placeholder="或手动输入模型名，如 deepseek-chat">
                        <button id="btn-list-llm" class="mt-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm transition-all">获取模型列表</button>
                    </div>
                </div>
            </div>

            <!-- Embedding Model Config -->
            <div class="bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-6 space-y-4">
                <h3 class="text-lg font-semibold text-white flex items-center gap-2">🧬 Embedding 模型配置</h3>
                <p class="text-gray-500 text-sm">配置 Embedding API，用于向量搜索。</p>
                <div class="space-y-3 max-w-xl">
                    <div>
                        <label class="block text-xs text-gray-500 mb-1">Base URL</label>
                        <input type="text" id="embed-base-url" value="${escHtml(config.embed_base_url||'')}"
                               class="w-full px-4 py-2.5 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                               placeholder="https://api.openai.com/v1">
                    </div>
                    <div>
                        <label class="block text-xs text-gray-500 mb-1">API Key <span id="embed-key-status" class="text-gray-600">${config.embed_api_key?'(已设置, 仅显示后4位)':''}</span></label>
                        <input type="password" id="embed-api-key" value="${escHtml(config.embed_api_key||'')}"
                               class="w-full px-4 py-2.5 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                               placeholder="sk-...">
                    </div>
                    <div>
                        <label class="block text-xs text-gray-500 mb-1">模型</label>
                        <select id="embed-model-select" class="flex-1 px-4 py-2.5 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50">
                            <option value="">${config.embed_model ? config.embed_model + ' (当前)' : '— 选择或手动输入 —'}</option>
                        </select>
                        <input type="text" id="embed-model-input" value="${escHtml(config.embed_model||'')}"
                               class="w-full px-4 py-2.5 mt-2 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                               placeholder="或手动输入，如 text-embedding-3-small">
                        <button id="btn-list-embed" class="mt-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm transition-all">获取模型列表</button>
                    </div>
                </div>
            </div>

            <!-- Save Config -->
            <div class="flex justify-end gap-3">
                <button id="btn-save-config" class="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm font-medium transition-all shadow-lg shadow-blue-600/20 active:scale-[0.98]">💾 保存模型配置</button>
            </div>

            <!-- Password -->
            <div class="bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-6 space-y-4">
                <h3 class="text-lg font-semibold text-white">🔒 修改密码</h3>
                <form id="pw-form" class="space-y-3 max-w-sm">
                    <input type="password" id="pw-old" placeholder="当前密码" required
                           class="w-full px-4 py-2.5 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50">
                    <input type="password" id="pw-new" placeholder="新密码 (至少 6 位)" required minlength="6"
                           class="w-full px-4 py-2.5 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50">
                    <input type="password" id="pw-new2" placeholder="确认新密码" required
                           class="w-full px-4 py-2.5 bg-gray-900/50 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50">
                    <div id="pw-msg" class="hidden text-sm rounded-lg p-2"></div>
                    <button type="submit" class="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm font-medium transition-all active:scale-[0.98]">修改密码</button>
                </form>
            </div>

            <!-- System Status -->
            <div class="bg-gray-800/80 backdrop-blur rounded-2xl border border-gray-700/50 p-6 space-y-4">
                <h3 class="text-lg font-semibold text-white">📡 系统状态</h3>
                <div id="settings-health"><span class="text-gray-500 text-sm">检测中...</span></div>
            </div>

            ${adminHtml}
        </div>
    `;

    // Health
    try {
        const h = await API.getHealth();
        document.getElementById('settings-health').innerHTML = `
            <div class="space-y-2 text-sm"><div class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full ${h.status==='ok'?'bg-green-500':'bg-red-500'}"></span><span class="text-gray-300">后端: ${h.status}</span></div><div class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full ${h.mineru_status==='ok'?'bg-green-500':'bg-red-500'}"></span><span class="text-gray-300">MinerU: ${h.mineru_status}</span></div><div class="text-gray-600">v${h.version}</div></div>`;
    } catch (e) { document.getElementById('settings-health').innerHTML = `<span class="text-red-400 text-sm">${e.message}</span>`; }

    // Nickname
    document.getElementById('nick-form').addEventListener('submit', async (e) => {
        e.preventDefault(); const v = document.getElementById('nick-input').value.trim();
        if (!v) return;
        try { await API.request('PUT','/api/auth/me/profile',{nickname:v}); if(typeof Toast!=='undefined')Toast.success('昵称已更新'); }
        catch(err){if(typeof Toast!=='undefined')Toast.error(err.message);}
    });

    // Theme
    function setThemeBtns(t) {
        const d = document.getElementById('btn-theme-dark'), l = document.getElementById('btn-theme-light');
        d.className = `px-5 py-3 rounded-xl border transition-all text-sm font-medium ${t==='dark'?'bg-blue-600 border-blue-500 text-white':'bg-gray-900/50 border-gray-700 text-gray-400'}`;
        l.className = `px-5 py-3 rounded-xl border transition-all text-sm font-medium ${t==='light'?'bg-amber-500 border-amber-400 text-white':'bg-gray-900/50 border-gray-700 text-gray-400'}`;
    }
    document.getElementById('btn-theme-dark').addEventListener('click', () => {
        applyTheme('dark'); setThemeBtns('dark'); API.updateConfig({theme:'dark'}).catch(()=>{});
    });
    document.getElementById('btn-theme-light').addEventListener('click', () => {
        applyTheme('light'); setThemeBtns('light'); API.updateConfig({theme:'light'}).catch(()=>{});
    });

    // Model listing
    async function listModels(provider) {
        const baseUrl = document.getElementById(`${provider}-base-url`).value.trim();
        const apiKey = document.getElementById(`${provider}-api-key`).value.trim();
        const select = document.getElementById(`${provider}-model-select`);
        const btn = document.getElementById(`btn-list-${provider}`);
        if (!baseUrl) { if(typeof Toast!=='undefined')Toast.warning('请先填写 Base URL'); return; }
        try {
            btn.disabled = true; btn.textContent = '获取中...';
            const res = await API.proxyListModels(provider, baseUrl, apiKey);
            select.innerHTML = '<option value="">— 选择模型 —</option>' +
                res.models.map(m => `<option value="${escHtml(m)}">${escHtml(m)}</option>`).join('');
            select.addEventListener('change', () => {
                document.getElementById(`${provider}-model-input`).value = select.value;
            });
        } catch (err) { if(typeof Toast!=='undefined')Toast.error(err.message); }
        finally { btn.disabled = false; btn.textContent = '获取模型列表'; }
    }
    document.getElementById('btn-list-llm').addEventListener('click', () => listModels('llm'));
    document.getElementById('btn-list-embed').addEventListener('click', () => listModels('embed'));

    // Save config
    document.getElementById('btn-save-config').addEventListener('click', async () => {
        const cfg = {
            llm_base_url: document.getElementById('llm-base-url').value.trim(),
            llm_api_key: document.getElementById('llm-api-key').value.trim(),
            llm_model: document.getElementById('llm-model-input').value.trim() || document.getElementById('llm-model-select').value,
            embed_base_url: document.getElementById('embed-base-url').value.trim(),
            embed_api_key: document.getElementById('embed-api-key').value.trim(),
            embed_model: document.getElementById('embed-model-input').value.trim() || document.getElementById('embed-model-select').value,
        };
        // Don't send empty api_key (keep existing)
        Object.keys(cfg).forEach(k => { if (!cfg[k] && k.endsWith('_api_key')) delete cfg[k]; });
        try {
            await API.updateConfig(cfg);
            if(typeof Toast!=='undefined')Toast.success('配置已保存');
        } catch (err) { if(typeof Toast!=='undefined')Toast.error('保存失败: ' + err.message); }
    });

    // Password
    document.getElementById('pw-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const msg = document.getElementById('pw-msg');
        const old = document.getElementById('pw-old').value;
        const nw = document.getElementById('pw-new').value;
        const nw2 = document.getElementById('pw-new2').value;
        if (nw !== nw2) { _msg(msg, '两次密码不一致', true); return; }
        try {
            await API.request('PUT','/api/auth/me/password',{old_password:old,new_password:nw});
            _msg(msg,'密码已修改，请重新登录',false);
            setTimeout(()=>API.logout(),1500);
        } catch(err){_msg(msg,err.message,true);}
    });

    // Admin
    if (canInvite) { await _loadInvitations(); document.getElementById('btn-gen-inv').addEventListener('click', async () => {
        const count = parseInt(document.getElementById('inv-count').value);
        const days = parseInt(document.getElementById('inv-days').value);
        try {
            const res = await API.createInvitations(count, days);
            const el = document.getElementById('inv-new-list');
            el.innerHTML = res.codes.map(c => `<span class="inline-flex items-center gap-2 px-3 py-1.5 bg-gray-900/50 rounded-lg font-mono text-sm text-amber-300 border border-gray-700 cursor-pointer hover:border-amber-500/50 transition-colors copy-code" data-code="${c}">${c}<span class="text-gray-600 text-xs copy-label">复制</span></span>`).join('');
            document.getElementById('inv-new-codes').classList.remove('hidden');
            el.querySelectorAll('.copy-code').forEach(span => span.addEventListener('click',()=>{navigator.clipboard.writeText(span.dataset.code);span.querySelector('.copy-label').textContent='✓ 已复制';}));
            await _loadInvitations();
        } catch(err){if(typeof Toast!=='undefined')Toast.error(err.message);}
    });}
    if (isAdmin) { await _loadUsers(); }
}

function _msg(el,t,isErr){el.textContent=t;el.className=`text-sm rounded-lg p-2 ${isErr?'text-red-400 bg-red-900/20':'text-emerald-400 bg-emerald-900/20'}`;el.classList.remove('hidden');}

async function _loadInvitations() {
    const el = document.getElementById('inv-list'); if (!el) return;
    try {
        const res = await API.listInvitations();
        if (!res.codes.length) { el.innerHTML='<p class="text-gray-600">暂无邀请码</p>'; return; }
        el.innerHTML=`<table class="w-full text-sm"><thead><tr class="text-gray-500 text-xs uppercase"><th class="text-left py-2 pr-4">邀请码</th><th class="text-left py-2 pr-4">状态</th><th class="text-left py-2 pr-4">使用者</th><th class="text-left py-2 pr-4">创建者</th><th class="text-left py-2">操作</th></tr></thead><tbody>${res.codes.map(c=>{const used=!!c.used_by,expired=c.expires_at&&new Date(c.expires_at)<new Date();let st='<span class="text-emerald-400">可用</span>';if(used)st='<span class="text-gray-500">已用</span>';else if(expired)st='<span class="text-red-400">已过期</span>';return`<tr class="border-t border-gray-800/50"><td class="py-2 pr-4 font-mono text-amber-300">${c.code}</td><td class="py-2 pr-4">${st}</td><td class="py-2 pr-4 text-gray-400">${c.used_by_username||'-'}</td><td class="py-2 pr-4 text-gray-500">${c.created_by_username||'-'}</td><td class="py-2">${!used?`<button data-del-code="${c.id}" class="text-red-500 hover:text-red-400 text-xs">删除</button>`:''}</td></tr>`}).join('')}</tbody></table>`;
        el.querySelectorAll('[data-del-code]').forEach(btn=>btn.addEventListener('click',async()=>{if(!confirm('删除此邀请码？'))return;await API.deleteInvitation(parseInt(btn.dataset.delCode));await _loadInvitations();}));
    } catch(e){el.innerHTML=`<span class="text-red-400">${e.message}</span>`;}
}

async function _loadUsers() {
    const el = document.getElementById('user-list'); if (!el) return;
    try {
        const res = await API.adminListUsers();
        if (!res.users.length) { el.innerHTML='<p class="text-gray-600">暂无用户</p>'; return; }
        el.innerHTML=`<table class="w-full text-sm"><thead><tr class="text-gray-500 text-xs uppercase"><th class="text-left py-2 pr-4">用户名</th><th class="text-left py-2 pr-4">昵称</th><th class="text-left py-2 pr-4">角色</th><th class="text-left py-2 pr-4">状态</th><th class="text-left py-2 pr-4">邀请权限</th><th class="text-left py-2">操作</th></tr></thead><tbody>${res.users.map(u=>{const isSelf=u.id===API.currentUser.id;return`<tr class="border-t border-gray-800/50"><td class="py-2 pr-4 text-white font-medium">${escHtml(u.username)}${isSelf?' <span class="text-gray-600 text-xs">(我)</span>':''}</td><td class="py-2 pr-4 text-gray-400">${escHtml(u.nickname||'-')}</td><td class="py-2 pr-4 ${u.role==='admin'?'text-amber-400':'text-gray-500'}">${u.role}</td><td class="py-2 pr-4"><span class="${u.status==='active'?'text-emerald-400':'text-red-400'}">${u.status==='active'?'正常':'禁用'}</span></td><td class="py-2 pr-4">${u.role==='admin'?'<span class="text-amber-400 text-xs">管理员自带</span>':`<label class="inline-flex items-center gap-1.5 cursor-pointer"><input type="checkbox" class="invite-toggle rounded bg-gray-700 border-gray-600 text-amber-500 focus:ring-amber-500/30" data-uid="${u.id}" ${u.can_invite?'checked':''}><span class="text-xs text-gray-500">${u.can_invite?'已授权':'未授权'}</span></label>`}</td><td class="py-2 flex gap-2">${!isSelf?(u.status==='active'?`<button data-disable="${u.id}" class="text-red-500 hover:text-red-400 text-xs">禁用</button>`:`<button data-enable="${u.id}" class="text-emerald-500 hover:text-emerald-400 text-xs">启用</button>`):''}<button data-reset-pw="${u.id}" class="text-blue-500 hover:text-blue-400 text-xs">重置密码</button></td></tr>`}).join('')}</tbody></table>`;
        el.querySelectorAll('.invite-toggle').forEach(cb=>cb.addEventListener('change',async()=>{const uid=parseInt(cb.dataset.uid),checked=cb.checked;try{await API.adminSetInvitePermission(uid,checked);cb.nextElementSibling.textContent=checked?'已授权':'未授权';}catch(err){cb.checked=!checked;if(typeof Toast!=='undefined')Toast.error(err.message);}}));
        el.addEventListener('click',async(e)=>{const btn=e.target.closest('button');if(!btn)return;if(btn.dataset.disable){if(!confirm('确定禁用？'))return;await API.adminUpdateUser(parseInt(btn.dataset.disable),{status:'disabled'});await _loadUsers();}if(btn.dataset.enable){await API.adminUpdateUser(parseInt(btn.dataset.enable),{status:'active'});await _loadUsers();}if(btn.dataset.resetPw){const pw=prompt('新密码（至少6位）：');if(!pw||pw.length<6)return;try{await API.adminUpdateUser(parseInt(btn.dataset.resetPw),{new_password:pw});if(typeof Toast!=='undefined')Toast.success('密码已重置');}catch(err){if(typeof Toast!=='undefined')Toast.error(err.message);}}});
    } catch(e){el.innerHTML=`<span class="text-red-400">${e.message}</span>`;}
}
