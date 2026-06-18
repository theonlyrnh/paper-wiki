/**
 * API client — auth + admin + permission delegation.
 */
const API = {
    base: '',
    _currentUser: null,
    _abortControllers: new Map(),
    _pendingRequests: new Map(),

    _makeRequestKey(method, path, body) {
        return `${method}:${path}:${body ? JSON.stringify(body) : ''}`;
    },

    async request(method, path, body = null) {
        // Cancel any previous identical request
        const key = this._makeRequestKey(method, path, body);
        if (this._pendingRequests.has(key)) {
            const prev = this._pendingRequests.get(key);
            if (prev.controller) prev.controller.abort();
        }

        const controller = new AbortController();
        this._pendingRequests.set(key, { controller, timestamp: Date.now() });

        const opts = {
            method,
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            signal: controller.signal,
        };
        if (body) opts.body = JSON.stringify(body);

        let resp;
        try {
            resp = await fetch(`${this.base}${path}`, opts);
        } catch (e) {
            if (e.name === 'AbortError') {
                const err = new Error('请求已取消');
                err.aborted = true;
                throw err;
            }
            if (typeof Toast !== 'undefined') Toast.error('网络连接失败，请检查网络');
            throw new Error('网络连接失败');
        }

        if (resp.status === 401) {
            this._currentUser = null;
            if (!location.hash.startsWith('#/login') && !location.hash.startsWith('#/register'))
                location.hash = '#/login';
            throw new Error('未登录');
        }
        // Clean up pending request
        this._pendingRequests.delete(key);
        if (!resp.ok) {
            let detail = '';
            try {
                const err = await resp.json();
                detail = err.detail || err.message || '';
            } catch (_) {}
            const msg = detail || `请求失败 (${resp.status})`;
            if (typeof Toast !== 'undefined') Toast.error(msg);
            throw new Error(msg);
        }
        return resp.json();
    },

    // ── Auth ──
    async login(username, password) {
        const r = await this.request('POST', '/api/auth/login', { username, password });
        this._currentUser = r.user;
        return r;
    },
    async register(username, password, invitation_code, nickname = '') {
        const r = await this.request('POST', '/api/auth/register', {
            username, password, invitation_code, nickname,
        });
        this._currentUser = r.user;
        return r;
    },
    async logout() {
        try { await this.request('POST', '/api/auth/logout'); } catch (e) {}
        this._currentUser = null;
        location.hash = '#/login';
    },
    async getMe() {
        try { this._currentUser = await this.request('GET', '/api/auth/me'); return this._currentUser; }
        catch (e) { this._currentUser = null; return null; }
    },
    async checkUsername(username) {
        return (await fetch(`${this.base}/api/auth/check-username?username=${encodeURIComponent(username)}`)).json();
    },

    get currentUser() { return this._currentUser; },
    isLoggedIn() { return !!this._currentUser; },
    isAdmin() { return this._currentUser?.role === 'admin'; },
    canInvite() { return this._currentUser?.role === 'admin' || !!this._currentUser?.can_invite; },

    // ── User Config ──
    async getConfig() {
        const cfg = await this.request('GET', '/api/auth/me/config');
        this._config = cfg;
        return cfg;
    },
    async updateConfig(cfg) {
        await this.request('PUT', '/api/auth/me/config', cfg);
        // Update local to reflect
        Object.assign(this._config || {}, cfg);
        return true;
    },
    get currentConfig() { return this._config || {}; },

    // ── Proxy: List models ──
    async proxyListModels(provider, base_url, api_key) {
        return this.request('POST', '/api/auth/proxy/models', { provider, base_url, api_key });
    },

    // ── Admin: Users ──
    async adminListUsers(page = 1) { return this.request('GET', `/api/auth/admin/users?page=${page}`); },
    async adminUpdateUser(userId, data) { return this.request('PUT', `/api/auth/admin/users/${userId}`, data); },
    async adminSetInvitePermission(userId, canInvite) {
        return this.request('PUT', `/api/auth/admin/users/${userId}/invite-permission?can_invite=${canInvite}`);
    },

    // ── Invitations (admin or can_invite users) ──
    async createInvitations(count = 1, expiresDays = 30) {
        return this.request('POST', '/api/auth/invitations', { count, expires_days: expiresDays });
    },
    async listInvitations() { return this.request('GET', '/api/auth/invitations'); },
    async deleteInvitation(codeId) { return this.request('DELETE', `/api/auth/invitations/${codeId}`); },

    // ── Papers ──
    async uploadPaper(file) {
        const form = new FormData();
        form.append('file', file);
        const resp = await fetch(`${this.base}/api/papers/upload`, { method: 'POST', credentials: 'include', body: form });
        if (resp.status === 401) { location.hash = '#/login'; throw new Error('未登录'); }
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({ detail: resp.statusText }))).detail);
        const data = await resp.json();
        this.refreshStorageQuota().catch(() => {});
        return data;
    },
    async listPapers(page = 1, pageSize = 20, status = null) {
        let url = `/api/papers?page=${page}&page_size=${pageSize}`;
        if (status) url += `&status=${encodeURIComponent(status)}`;
        return this.request('GET', url);
    },
    async getPaper(id) { return this.request('GET', `/api/papers/${id}`); },
    async deletePaper(id) { return this.request('DELETE', `/api/papers/${id}`); },
    async deleteRawPdf(id) {
        const result = await this.request('DELETE', `/api/papers/${id}/raw-pdf?ensure_cache=true`);
        this.refreshStorageQuota().catch(() => {});
        return result;
    },
    async retryPaper(id, mode = 'auto') {
        return this.request('POST', `/api/papers/${id}/retry?mode=${encodeURIComponent(mode)}`);
    },

    // ── System ──
    async getHealth() {
        const r = await fetch(`${this.base}/api/health`);
        if (!r.ok) throw new Error(r.statusText);
        return r.json();
    },
    async getStats() { return this.request('GET', '/api/stats'); },
    async getStorageQuota() { return this.request('GET', '/api/storage/quota'); },
    async refreshStorageQuota() {
        const quota = await this.getStorageQuota();
        window.dispatchEvent(new CustomEvent('storage-quota-updated', { detail: quota }));
        return quota;
    },

    // ── Ingest ──
    async getIngestStatus() { return this.request('GET', '/api/ingest/status'); },
    async cancelIngest(id) { return this.request('POST', `/api/ingest/cancel/${id}`); },
    async retryIngest(id) { return this.request('POST', `/api/ingest/retry/${id}`); },
};
