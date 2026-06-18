/**
 * Login page — centered, no sidebar offset.
 */
async function renderLoginPage(container) {
    container.innerHTML = `
        <div class="min-h-screen flex items-center justify-center">
            <div class="w-full max-w-md px-4">
                <div class="bg-gray-800/90 backdrop-blur-xl rounded-2xl border border-gray-700/50 p-8 shadow-2xl">
                    <div class="text-center mb-8">
                        <div class="text-5xl mb-3">📚</div>
                        <h1 class="text-2xl font-bold text-white">Paper Wiki</h1>
                        <p class="text-gray-500 text-sm mt-1">论文知识库 — 登录</p>
                    </div>
                    <form id="login-form" class="space-y-5">
                        <div>
                            <label class="block text-sm font-medium text-gray-400 mb-1.5">用户名</label>
                            <input type="text" id="login-username" required autocomplete="username"
                                   class="w-full px-4 py-3 bg-gray-900/50 border border-gray-700 rounded-xl
                                          text-white placeholder-gray-600 focus:outline-none focus:ring-2
                                          focus:ring-blue-500/50 focus:border-blue-500/50 transition"
                                   placeholder="输入用户名">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-400 mb-1.5">密码</label>
                            <input type="password" id="login-password" required autocomplete="current-password"
                                   class="w-full px-4 py-3 bg-gray-900/50 border border-gray-700 rounded-xl
                                          text-white placeholder-gray-600 focus:outline-none focus:ring-2
                                          focus:ring-blue-500/50 focus:border-blue-500/50 transition"
                                   placeholder="••••••••">
                        </div>
                        <div id="login-error" class="hidden text-red-400 text-sm bg-red-900/20 rounded-lg p-3"></div>
                        <button type="submit"
                                class="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl
                                       font-medium transition-all shadow-lg shadow-blue-600/20
                                       hover:shadow-blue-500/30 active:scale-[0.98]">
                            登录
                        </button>
                    </form>
                    <div class="mt-6 text-center text-sm text-gray-500">
                        没有账号？<a href="#/register" class="text-blue-400 hover:text-blue-300 transition">注册</a>
                    </div>
                </div>
            </div>
        </div>
    `;

    const form = document.getElementById('login-form');
    const errEl = document.getElementById('login-error');
    const btn = form.querySelector('button');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errEl.classList.add('hidden');
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;
        if (!username || !password) {
            errEl.textContent = '请填写用户名和密码';
            errEl.classList.remove('hidden');
            return;
        }
        try {
            btn.disabled = true; btn.textContent = '登录中...';
            await API.login(username, password);
            location.hash = '#/';
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        } finally {
            btn.disabled = false; btn.textContent = '登录';
        }
    });
}
