"""Toast notification system for Paper Wiki."""

const Toast = {
    container: null,
    activeToasts: new Set(),
    maxToasts: 5,

    init() {
        if (this.container) return; // Already initialized

        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        this.container.className = 'fixed top-4 right-4 z-50 flex flex-col gap-2 pointer-events-none';
        this.container.style.maxWidth = '400px';
        document.body.appendChild(this.container);
    },

    show(message, type = 'info', duration = 3000) {
        if (!this.container) this.init();

        // Limit number of toasts
        if (this.activeToasts.size >= this.maxToasts) {
            const oldest = Array.from(this.activeToasts)[0];
            this.hide(oldest);
        }

        const toast = document.createElement('div');
        const toastId = 'toast-' + Date.now() + Math.random();
        toast.id = toastId;

        const colors = {
            success: 'bg-emerald-600 border-emerald-500',
            error: 'bg-red-600 border-red-500',
            warning: 'bg-amber-600 border-amber-500',
            info: 'bg-blue-600 border-blue-500'
        };
        const icons = {
            success: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>',
            error: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>',
            warning: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>',
            info: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'
        };

        toast.className = `${colors[type]} border-l-4 text-white px-4 py-3 rounded-lg shadow-xl
                           flex items-center gap-3 min-w-[280px] pointer-events-auto
                           transform transition-all duration-300 ease-out cursor-pointer
                           hover:scale-105 hover:shadow-2xl`;
        toast.style.animation = 'slideInRight 0.3s ease-out';

        const escHtml = (str) => {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        };

        toast.innerHTML = `
            <div class="flex-shrink-0">${icons[type]}</div>
            <span class="flex-1 text-sm font-medium leading-snug">${escHtml(message)}</span>
            <button class="flex-shrink-0 text-white/70 hover:text-white transition-colors ml-2"
                    aria-label="关闭">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        `;

        // Click anywhere on toast to close
        toast.onclick = (e) => {
            if (e.target.closest('button') || e.target.closest('a')) {
                // Let button/link handle their own click
            }
            this.hide(toast);
        };

        this.container.appendChild(toast);
        this.activeToasts.add(toast);

        // Auto close
        if (duration > 0) {
            setTimeout(() => this.hide(toast), duration);
        }

        return toast;
    },

    hide(toast) {
        if (typeof toast === 'string') {
            toast = document.getElementById(toast);
        }
        if (!toast || !toast.parentNode) return;

        toast.style.animation = 'slideOutRight 0.3s ease-out';
        toast.style.opacity = '0';

        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
                this.activeToasts.delete(toast);
            }
        }, 300);
    },

    // Convenience methods
    success(msg, duration) { return this.show(msg, 'success', duration); },
    error(msg, duration) { return this.show(msg, 'error', duration || 5000); },
    warning(msg, duration) { return this.show(msg, 'warning', duration || 4000); },
    info(msg, duration) { return this.show(msg, 'info', duration); },

    // Promise-aware wrapper
    async promise(promise, messages) {
        const { loading, success, error } = messages;
        let loadingToast;

        if (loading) {
            loadingToast = this.info(loading, 0); // Don't auto-hide
        }

        try {
            const result = await promise;
            if (loadingToast) this.hide(loadingToast);
            if (success) this.success(success);
            return result;
        } catch (e) {
            if (loadingToast) this.hide(loadingToast);
            if (error) {
                this.error(typeof error === 'function' ? error(e) : error);
            }
            throw e;
        }
    }
};

// Auto-initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => Toast.init());
} else {
    Toast.init();
}

// Add animations to document
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(120%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }

    @keyframes slideOutRight {
        from {
            transform: translateX(0) scale(1);
            opacity: 1;
        }
        to {
            transform: translateX(120%) scale(0.9);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);
