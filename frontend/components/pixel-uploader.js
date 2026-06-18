/**
 * Pixel-style upload animation — cute retro loading indicator.
 * Shows a pixel art character that "reads" papers while processing.
 */

const PixelUploader = {
    _active: false,
    _frame: 0,
    _timer: null,
    _container: null,
    _startTime: 0,
    _status: '',

    // Pixel art frames — a little character reading
    _frames: [
        // Frame 0: standing
        `  ╔═══╗
  ║ 📖 ║
  ╚═╤═╝
   ╱ ╲
  █   █
  █   █
  ╰───╯`,
        // Frame 1: reading left
        `  ╔═══╗
  ║📖  ║
  ╚═╤═╝
  ╱   ╲
  █   █
  █   █
  ╰───╯`,
        // Frame 2: reading right
        `  ╔═══╗
  ║  📖║
  ╚═╤═╝
 ╱   ╲
  █   █
  █   █
  ╰───╯`,
        // Frame 3: excited
        `  ╔═══╗
  ║ ✨ ║
  ╚═╤═╝
  ╱   ╲
  █   █
  █   █
  ╰───╯`,
    ],

    _statusMessages: {
        pending: '排队中...',
        parsing: '正在解析 PDF...',
        ingesting: 'AI 正在阅读论文...',
        indexing: '正在建立索引...',
        done: '✅ 完成！',
        failed: '❌ 解析失败',
    },

    show(containerId, status = 'pending') {
        if (this._active) return;
        this._active = true;
        this._frame = 0;
        this._startTime = Date.now();
        this._status = status;

        const container = document.getElementById(containerId);
        if (!container) return;
        this._container = container;

        container.innerHTML = `
            <div class="pixel-uploader bg-gray-800/90 backdrop-blur rounded-2xl border border-gray-700/50 p-6
                        shadow-2xl animate-fade-in">
                <div class="flex items-start gap-4">
                    <pre id="pixel-art" class="text-emerald-400 text-xs leading-tight font-mono
                                                   whitespace-pre select-none shrink-0"></pre>
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center justify-between mb-2">
                            <h3 class="text-sm font-semibold text-white">📚 论文处理中</h3>
                            <button onclick="PixelUploader.hide()"
                                    class="text-gray-600 hover:text-gray-400 text-xs transition-colors">
                                ✕ 关闭
                            </button>
                        </div>
                        <div id="pixel-status" class="text-sm text-gray-400"></div>
                        <div class="mt-2 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                            <div id="pixel-progress" class="h-full bg-gradient-to-r from-emerald-500 to-blue-500
                                                              rounded-full transition-all duration-1000"
                                 style="width: 0%"></div>
                        </div>
                        <div id="pixel-time" class="text-[10px] text-gray-600 mt-1.5"></div>
                    </div>
                </div>
            </div>
        `;

        this._render();
        this._timer = setInterval(() => this._render(), 600);
    },

    _render() {
        const art = document.getElementById('pixel-art');
        const status = document.getElementById('pixel-status');
        const progress = document.getElementById('pixel-progress');
        const time = document.getElementById('pixel-time');
        if (!art) return;

        art.textContent = this._frames[this._frame % this._frames.length];
        this._frame++;

        const elapsed = Math.floor((Date.now() - this._startTime) / 1000);
        const mins = Math.floor(elapsed / 60);
        const secs = elapsed % 60;

        if (status) status.textContent = this._statusMessages[this._status] || '处理中...';
        if (time) time.textContent = `已用时 ${mins} 分 ${secs} 秒`;

        // Simulated progress (never reaches 100% until done)
        if (progress) {
            const pct = Math.min(95, 5 + elapsed * 1.5);
            progress.style.width = `${pct}%`;
        }
    },

    setStatus(status) {
        this._status = status;
        if (status === 'done') {
            const progress = document.getElementById('pixel-progress');
            if (progress) progress.style.width = '100%';
            const art = document.getElementById('pixel-art');
            if (art) art.textContent = `  ╔═══╗
  ║ 🎉 ║
  ╚═╤═╝
  ╱   ╲
  █   █
  █   █
  ╰───╯`;
            setTimeout(() => this.hide(), 3000);
        }
        if (status === 'failed') {
            const art = document.getElementById('pixel-art');
            if (art) art.textContent = `  ╔═══╗
  ║ 💥 ║
  ╚═╤═╝
  ╱   ╲
  █   █
  █   █
  ╰───╯`;
            setTimeout(() => this.hide(), 5000);
        }
    },

    hide() {
        this._active = false;
        if (this._timer) { clearInterval(this._timer); this._timer = null; }
        if (this._container) {
            this._container.innerHTML = '';
            this._container = null;
        }
    },
};
