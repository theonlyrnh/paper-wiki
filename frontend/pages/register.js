/**
 * Register page — centered, username + invite code, real-time duplicate check.
 */
async function renderRegisterPage(container) {
    container.innerHTML = `
        <div class="min-h-screen flex items-center justify-center">
            <div class="w-full max-w-md px-4">
                <div class="bg-gray-800/90 backdrop-blur-xl rounded-2xl border border-gray-700/50 p-8 shadow-2xl">
                    <div class="text-center mb-8">
                        <div class="text-5xl mb-3">📚</div>
                        <h1 class="text-2xl font-bold text-white">Paper Wiki</h1>
                        <p class="text-gray-500 text-sm mt-1">注册 — 需要邀请码</p>
                    </div>
                    <form id="register-form" class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-400 mb-1.5">用户名</label>
                            <div class="relative">
                                <input type="text" id="reg-username" required autocomplete="username"
                                       class="w-full px-4 py-3 pr-10 bg-gray-900/50 border border-gray-700 rounded-xl
                                              text-white placeholder-gray-600 focus:outline-none focus:ring-2
                                              focus:ring-blue-500/50 transition"
                                       placeholder="2-30 字符">
                                <span id="reg-username-icon" class="absolute right-3 top-1/2 -translate-y-1/2 text-lg"></span>
                            </div>
                            <p id="reg-username-hint" class="text-xs text-gray-600 mt-1 hidden"></p>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-400 mb-1.5">昵称 <span class="text-gray-600">(选填)</span></label>
                            <input type="text" id="reg-nickname"
                                   class="w-full px-4 py-3 bg-gray-900/50 border border-gray-700 rounded-xl
                                          text-white placeholder-gray-600 focus:outline-none focus:ring-2
                                          focus:ring-blue-500/50 transition" placeholder="显示名称">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-400 mb-1.5">密码 <span class="text-gray-600">(至少 6 位)</span></label>
                            <input type="password" id="reg-password" required minlength="6" autocomplete="new-password"
                                   class="w-full px-4 py-3 bg-gray-900/50 border border-gray-700 rounded-xl
                                          text-white placeholder-gray-600 focus:outline-none focus:ring-2
                                          focus:ring-blue-500/50 transition" placeholder="••••••••">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-400 mb-1.5">确认密码</label>
                            <input type="password" id="reg-password2" required autocomplete="new-password"
                                   class="w-full px-4 py-3 bg-gray-900/50 border border-gray-700 rounded-xl
                                          text-white placeholder-gray-600 focus:outline-none focus:ring-2
                                          focus:ring-blue-500/50 transition" placeholder="••••••••">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-400 mb-1.5">邀请码</label>
                            <input type="text" id="reg-code" required autocomplete="off"
                                   class="w-full px-4 py-3 bg-gray-900/50 border border-gray-700 rounded-xl
                                          text-white placeholder-gray-600 focus:outline-none focus:ring-2
                                          focus:ring-blue-500/50 transition font-mono tracking-wider"
                                   placeholder="PW-XXXXXXXX">
                        </div>
                        <div id="reg-error" class="hidden text-red-400 text-sm bg-red-900/20 rounded-lg p-3"></div>
                        <div id="reg-success" class="hidden text-emerald-400 text-sm bg-emerald-900/20 rounded-lg p-3"></div>
                        <button type="submit"
                                class="w-full py-3 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl
                                       font-medium transition-all shadow-lg shadow-emerald-600/20
                                       hover:shadow-emerald-500/30 active:scale-[0.98]">注册</button>
                    </form>
                    <div class="mt-6 text-center text-sm text-gray-500">
                        已有账号？<a href="#/login" class="text-blue-400 hover:text-blue-300 transition">登录</a>
                    </div>
                </div>
            </div>
        </div>
    `;

    const usernameInput = document.getElementById('reg-username');
    const usernameIcon = document.getElementById('reg-username-icon');
    const usernameHint = document.getElementById('reg-username-hint');
    let checkTimer = null;

    usernameInput.addEventListener('input', () => {
        clearTimeout(checkTimer);
        const val = usernameInput.value.trim();
        if (val.length < 2) { usernameIcon.textContent = ''; usernameHint.classList.add('hidden'); return; }
        usernameIcon.textContent = '⏳';
        checkTimer = setTimeout(async () => {
            try {
                const res = await API.checkUsername(val);
                if (res.available) {
                    usernameIcon.textContent = '✅';
                    usernameHint.textContent = '用户名可用';
                    usernameHint.className = 'text-xs text-emerald-400 mt-1 hidden';
                } else {
                    usernameIcon.textContent = '❌';
                    usernameHint.textContent = res.reason || '不可用';
                    usernameHint.className = 'text-xs text-red-400 mt-1';
                    usernameHint.classList.remove('hidden');
                }
            } catch (e) { usernameIcon.textContent = ''; usernameHint.classList.add('hidden'); }
        }, 400);
    });

    const form = document.getElementById('register-form');
    const errEl = document.getElementById('reg-error');
    const successEl = document.getElementById('reg-success');
    const btn = form.querySelector('button');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errEl.classList.add('hidden'); successEl.classList.add('hidden');
        const username = document.getElementById('reg-username').value.trim();
        const nickname = document.getElementById('reg-nickname').value.trim();
        const password = document.getElementById('reg-password').value;
        const password2 = document.getElementById('reg-password2').value;
        const code = document.getElementById('reg-code').value.trim();
        if (password !== password2) { errEl.textContent = '两次密码不一致'; errEl.classList.remove('hidden'); return; }
        if (password.length < 6) { errEl.textContent = '密码至少 6 位'; errEl.classList.remove('hidden'); return; }
        if (!code) { errEl.textContent = '请输入邀请码'; errEl.classList.remove('hidden'); return; }
        try {
            btn.disabled = true; btn.textContent = '注册中...';
            await API.register(username, password, code, nickname);
            successEl.textContent = '注册成功！正在跳转...';
            successEl.classList.remove('hidden');
            setTimeout(() => { location.hash = '#/'; }, 500);
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        } finally { btn.disabled = false; btn.textContent = '注册'; }
    });
}
