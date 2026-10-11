(function () {
    'use strict';

    var form = document.getElementById('videoChatForm');
    var input = document.getElementById('chatQuestion');
    var messages = document.getElementById('chatMessages');
    var status = document.getElementById('chatStatus');
    var sendButton = document.getElementById('chatSend');
    var videoId = window.chatVideoId;

    if (!form || !input || !messages || !status || !sendButton || !videoId) return;

    // ---- Lightweight markdown → HTML ----
    function renderMarkdown(text) {
        if (!text) return '';

        var html = text;

        // Escape HTML entities first
        html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

        // Fenced code blocks: ```lang\n...\n```
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
            var langAttr = lang ? ' data-lang="' + lang + '"' : '';
            return '<pre' + langAttr + '><code>' + code.trim() + '</code></pre>';
        });

        // Inline code: `code`
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Headings: #### → h4, ### → h3, ## → h2, # → h1
        html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
        html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

        // Bold: **text**
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

        // Italic: *text*
        html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');

        // Unordered list items: - item or * item
        html = html.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');

        // Ordered list items: 1. item
        html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

        // Wrap consecutive <li> in <ul>
        html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

        // Blockquotes: > text
        html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

        // Tables (basic): | col | col |
        html = html.replace(/(?:^\|.+\|$\n?)+/gm, function (tableBlock) {
            var rows = tableBlock.trim().split('\n');
            if (rows.length < 2) return tableBlock;

            var tableHtml = '<table>';
            rows.forEach(function (row, i) {
                // Skip separator rows like |---|---|
                if (/^\|[\s\-:]+\|$/.test(row)) return;

                var tag = i === 0 ? 'th' : 'td';
                var cells = row.split('|').filter(function (c) { return c.trim() !== ''; });
                tableHtml += '<tr>';
                cells.forEach(function (cell) {
                    tableHtml += '<' + tag + '>' + cell.trim() + '</' + tag + '>';
                });
                tableHtml += '</tr>';
            });
            tableHtml += '</table>';
            return tableHtml;
        });

        // Paragraphs: wrap remaining bare lines
        html = html.replace(/^(?!<[a-z])((?!<\/).+)$/gm, '<p>$1</p>');

        // Clean up empty paragraphs
        html = html.replace(/<p>\s*<\/p>/g, '');

        return html;
    }

    // ---- Chat bubble helpers ----
    function addBubble(content, className, isHtml) {
        var bubble = document.createElement('div');
        bubble.className = 'bubble ' + className;
        if (isHtml) {
            bubble.innerHTML = content;
        } else {
            bubble.textContent = content;
        }
        messages.appendChild(bubble);
        messages.scrollTop = messages.scrollHeight;
        return bubble;
    }

    function addTypingIndicator() {
        var bubble = document.createElement('div');
        bubble.className = 'bubble bubble--ai';
        bubble.id = 'typingIndicator';
        bubble.innerHTML = '<div class="dots"><i></i><i></i><i></i></div>';
        messages.appendChild(bubble);
        messages.scrollTop = messages.scrollHeight;
        return bubble;
    }

    function removeTypingIndicator() {
        var indicator = document.getElementById('typingIndicator');
        if (indicator) indicator.remove();
    }

    function addSources(parent, sources) {
        if (!Array.isArray(sources) || sources.length === 0) return;

        var details = document.createElement('details');
        details.className = 'chat-sources';
        var summary = document.createElement('summary');
        summary.textContent = 'Sources (' + sources.length + ')';
        details.appendChild(summary);

        sources.forEach(function (source) {
            var item = document.createElement('p');
            var label = source.id || 'Source';
            var section = source.section || 'Video notes';
            var score = typeof source.similarity === 'number'
                ? ' · match ' + source.similarity.toFixed(2)
                : '';
            item.textContent = label + ' · ' + section + score;
            details.appendChild(item);
        });

        parent.appendChild(details);
    }

    // ---- Auto-resize textarea ----
    input.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 160) + 'px';
    });

    // ---- Submit on Enter (Shift+Enter for new line) ----
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            form.dispatchEvent(new Event('submit', { cancelable: true }));
        }
    });

    // ---- Click handler for prompt suggestion chips ----
    document.addEventListener('click', function (e) {
        var chip = e.target.closest('.chat-chip');
        if (chip && input && form) {
            var rawText = chip.textContent || '';
            // Strip leading emoji if present
            var text = rawText.replace(/^[^\w\s]+\s*/, '').trim();
            input.value = text;
            input.style.height = 'auto';
            input.focus();
            form.dispatchEvent(new Event('submit', { cancelable: true }));
        }
    });

    // ---- Form submission ----
    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        var question = input.value.trim();
        if (!question || sendButton.disabled) return;

        addBubble(question, 'bubble--you', false);
        input.value = '';
        input.style.height = 'auto';
        input.disabled = true;
        sendButton.disabled = true;
        status.textContent = '● Searching video transcript passages…';

        addTypingIndicator();

        try {
            var response = await fetch(
                '/api/videos/' + encodeURIComponent(videoId) + '/chat',
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question: question })
                }
            );
            var payload = await response.json();
            if (!response.ok) throw new Error(payload.error || 'Server error: Request failed.');

            removeTypingIndicator();

            var rawAnswer = payload.answer || 'Server error: Unable to generate an answer at this time.';
            var renderedAnswer = renderMarkdown(rawAnswer);
            var answer = addBubble(renderedAnswer, 'bubble--ai', true);
            addSources(answer, payload.sources);
            status.textContent = '● Answer generated from video context.';
        } catch (error) {
            removeTypingIndicator();
            var errText = error.message || 'Server error: Unable to process request.';
            // Clean up internal provider names from error string if any leaked
            errText = errText.replace(/Groq/gi, 'Server');
            addBubble(errText, 'bubble--ai', false);
            status.textContent = '⚠️ Server error: Unable to connect right now. Please try again.';
        } finally {
            input.disabled = false;
            sendButton.disabled = false;
            input.focus();
            if (messages) messages.scrollTop = messages.scrollHeight;
        }
    });
}());
