/**
 * Markdown renderer with KaTeX math support.
 */
const MarkdownRenderer = {
    init() {
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                breaks: true,
                gfm: true,
                headerIds: true,
            });
        }
    },

    render(markdown) {
        if (!markdown) return '<p class="text-gray-500 italic">No content</p>';

        // Render markdown to HTML
        let html = typeof marked !== 'undefined'
            ? marked.parse(markdown)
            : this.fallbackRender(markdown);

        // Post-process: render math with KaTeX
        if (typeof renderMathInElement !== 'undefined') {
            const container = document.createElement('div');
            container.innerHTML = html;
            renderMathInElement(container, {
                delimiters: [
                    { left: '$$', right: '$$', display: true },
                    { left: '$', right: '$', display: false },
                    { left: '\\[', right: '\\]', display: true },
                    { left: '\\(', right: '\\)', display: false },
                ],
                throwOnError: false,
            });
            html = container.innerHTML;
        }

        // Post-process: highlight code blocks with Prism.js
        if (typeof Prism !== 'undefined') {
            const container2 = document.createElement('div');
            container2.innerHTML = html;
            container2.querySelectorAll('pre code').forEach((block) => {
                Prism.highlightElement(block);
            });
            html = container2.innerHTML;
        }

        return html;
    },

    fallbackRender(md) {
        // Basic fallback if marked.js is not loaded
        return md
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/^### (.+)$/gm, '<h3 class="text-lg font-bold mt-4 mb-2">$1</h3>')
            .replace(/^## (.+)$/gm, '<h2 class="text-xl font-bold mt-6 mb-3">$1</h2>')
            .replace(/^# (.+)$/gm, '<h1 class="text-2xl font-bold mt-6 mb-4">$1</h1>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/\n\n/g, '</p><p>')
            .replace(/\n/g, '<br>');
    },
};
