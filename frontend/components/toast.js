/**
 * Toast notification system — replaces alert() with non-blocking overlay notifications.
 */
const Toast = {
    container: null,

    init() {
        if (this.container) return;
        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        this.container.innerHTML = '';
        this.container.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:9999;display:flex;flex-direction:column;gap:0.5rem;pointer-events:none;';
        document.body.appendChild(this.container);
    },

    show(message, type = 'info', duration = 3000) {
        this.init();

        const colors = {
            success: { bg: '#065f46', border: '#10b981' },
            error:   { bg: '#991b1b', border: '#ef4444' },
            warning: { bg: '#92400e', border: '#f59e0b' },
            info:    { bg: '#1e3a5f', border: '#3b82f6' },
        };
        const icons = { success: '\u2713', error: '\u2717', warning: '\u26a0', info: '\u2139' };

        const c = colors[type] || colors.info;
        const toast = document.createElement('div');
        toast.style.cssText = `
            background:${c.bg};border-left:3px solid ${c.border};color:#f1f5f9;
            padding:0.75rem 1rem;border-radius:0.5rem;box-shadow:0 10px 30px rgba(0,0,0,0.4);
            display:flex;align-items:center;gap:0.6rem;min-width:280px;max-width:420px;
            pointer-events:auto;cursor:pointer;font-size:0.875rem;
            animation:toastSlideIn 0.3s ease-out;
            transition: all 0.2s ease;
        `;
        toast.innerHTML = `<span style="font-size:1.1rem;flex-shrink:0;">${icons[type]}</span>
            <span style="flex:1;line-height:1.4;">${message}</span>
            <button style="color:rgba(255,255,255,0.5);background:none;border:none;font-size:1.1rem;cursor:pointer;padding:0 0.25rem;" onclick="this.parentElement.remove()">\u00d7</button>`;
        toast.onclick = (e) => {
            if (e.target.tagName !== 'BUTTON') this.hide(toast);
        };

        this.container.appendChild(toast);

        if (duration > 0) {
            setTimeout(() => this.hide(toast), duration);
        }
    },

    hide(toast) {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(120%)';
        setTimeout(() => toast.remove(), 300);
    },

    success(msg) { this.show(msg, 'success'); },
    error(msg) { this.show(msg, 'error', 5000); },
    warning(msg) { this.show(msg, 'warning', 4000); },
    info(msg) { this.show(msg, 'info'); },
};
