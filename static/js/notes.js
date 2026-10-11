/* ==========================================================================
   LearnTube — notebook workspace
   Renders the lecture JSON into the handwritten notes, the revision sheet,
   the flashcard deck, and the practice paper.
   ========================================================================== */

(function () {
    'use strict';

    var DATA = (typeof lectureData !== 'undefined' && lectureData) ? lectureData : {};
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    var $  = function (id) { return document.getElementById(id); };
    var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text != null) n.textContent = text;
        return n;
    }

    /* a stable key so progress sticks to this lecture, not the browser */
    var slug = String(DATA.title || 'lecture').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 60);

    function load(key, fallback) {
        try {
            var raw = localStorage.getItem('lt:' + key + ':' + slug);
            return raw == null ? fallback : JSON.parse(raw);
        } catch (e) { return fallback; }
    }
    function save(key, value) {
        try { localStorage.setItem('lt:' + key + ':' + slug, JSON.stringify(value)); } catch (e) {}
    }

    function shuffle(arr) {
        var a = arr.slice(), i, j, t;
        for (i = a.length - 1; i > 0; i--) {
            j = Math.floor(Math.random() * (i + 1));
            t = a[i]; a[i] = a[j]; a[j] = t;
        }
        return a;
    }

    /* Reveals are a nicety; being able to read the page is not. Anything
       already on screen is shown straight away rather than waiting on the
       observer, so a stalled callback can never leave content invisible. */
    function revealIfVisible(els, root) {
        var top = 0, bottom = window.innerHeight;
        if (root) {
            var r = root.getBoundingClientRect();
            top = r.top; bottom = r.bottom;
        }
        els.forEach(function (node) {
            var b = node.getBoundingClientRect();
            if (b.top < bottom && b.bottom > top) node.classList.add('is-in');
        });
    }

    /* ======================================================================
       1. DESK LAMP
       ====================================================================== */
    (function theme() {
        var btn = $('themeToggle');
        var saved = null;
        try { saved = localStorage.getItem('lt:theme'); } catch (e) {}

        function apply(mode) {
            if (mode === 'dark') {
                document.documentElement.setAttribute('data-theme', 'dark');
            } else {
                document.documentElement.removeAttribute('data-theme');
            }
            if (btn) {
                btn.setAttribute('aria-pressed', mode === 'dark' ? 'true' : 'false');
                btn.querySelector('.lamp-text').textContent = mode === 'dark' ? 'Lamp off' : 'Desk lamp';
            }
        }

        apply(saved === 'dark' ? 'dark' : 'light');

        if (btn) {
            btn.addEventListener('click', function () {
                var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
                apply(next);
                try { localStorage.setItem('lt:theme', next); } catch (e) {}
            });
        }
    }());

    /* ======================================================================
       2. RAIL (mobile)
       ====================================================================== */
    (function rail() {
        var open = $('railOpen');
        if (!open) return;
        open.addEventListener('click', function () {
            document.body.classList.toggle('rail-out');
        });
        document.addEventListener('click', function (e) {
            if (!document.body.classList.contains('rail-out')) return;
            if (e.target.closest('.rail') || e.target.closest('.rail-open')) return;
            document.body.classList.remove('rail-out');
        });
    }());

    /* ======================================================================
       3. DIVIDER TABS
       ====================================================================== */
    var tabs = $$('.divider');
    var activePane = 'paneNotes';

    function showPane(paneId, focusIt) {
        activePane = paneId;
        var isChat = paneId === 'paneChat';
        document.body.classList.toggle('chat-mode-active', isChat);

        tabs.forEach(function (t) {
            var on = t.getAttribute('data-pane') === paneId;
            t.classList.toggle('is-active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        $$('.pane').forEach(function (p) {
            p.classList.toggle('is-active', p.id === paneId);
        });
        var sheets = $('sheets');
        if (sheets) {
            sheets.classList.toggle('chat-mode-active', isChat);
            if (!isChat) window.scrollTo(0, 0);
        }
        if (focusIt) {
            var pane = $(paneId);
            if (pane) pane.focus({ preventScroll: true });
        }
        if (paneId === 'paneSummary') revealSummary();
        if (paneId === 'paneCards') deck.wake();
        if (isChat) {
            var chatInput = $('chatQuestion');
            if (chatInput) {
                setTimeout(function () { chatInput.focus(); }, 50);
            }
        }
    }

    tabs.forEach(function (t, i) {
        t.addEventListener('click', function () { showPane(t.getAttribute('data-pane'), false); });
        t.addEventListener('keydown', function (e) {
            var dir = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
            if (!dir) return;
            e.preventDefault();
            var next = tabs[(i + dir + tabs.length) % tabs.length];
            next.focus();
            showPane(next.getAttribute('data-pane'), false);
        });
    });

    /* ======================================================================
       4. HEADER
       ====================================================================== */
    var sections   = Array.isArray(DATA.sections) ? DATA.sections : [];
    var defs       = Array.isArray(DATA.definitions) ? DATA.definitions : [];
    var terms      = Array.isArray(DATA.important_terms) ? DATA.important_terms : [];
    var takeaways  = Array.isArray(DATA.key_takeaways) ? DATA.key_takeaways : [];
    var examTips   = Array.isArray(DATA.exam_tips) ? DATA.exam_tips : [];
    var tricks     = Array.isArray(DATA.memory_tricks) ? DATA.memory_tricks : [];
    var mixups     = Array.isArray(DATA.frequently_confused_topics) ? DATA.frequently_confused_topics : [];

    if ($('docTitle')) $('docTitle').textContent = DATA.title || 'Your notebook';
    if ($('chipLevel')) $('chipLevel').textContent = DATA.difficulty || '—';
    if ($('chipTime')) $('chipTime').textContent = DATA.estimated_study_time || '—';
    if ($('chipSections')) $('chipSections').textContent = sections.length || '—';

    /* ======================================================================
       5. NOTES — the handwriting. Structure and wording are untouched;
       only the paper around it changed.
       ====================================================================== */
    (function renderNotes() {
        var host = $('notesContainer');
        if (!host) return;

        if (!sections.length) {
            host.appendChild(el('p', null, 'No notes came back for this lecture.'));
            return;
        }

        sections.forEach(function (sec, i) {
            var wrap = el('section', 'note-sec hw-in');
            wrap.id = 'sec-' + i;

            var h2 = el('h2');
            var n = el('span', 'sec-n', String(i + 1).padStart(2, '0'));
            h2.appendChild(n);
            h2.appendChild(document.createTextNode(sec.heading || 'Section ' + (i + 1)));
            wrap.appendChild(h2);

            (sec.subtopics || []).forEach(function (st) {
                if (st.title) wrap.appendChild(el('h3', null, st.title));
                if (st.content) wrap.appendChild(el('p', null, st.content));

                if ((st.important_points || []).length) {
                    var ul = el('ul');
                    st.important_points.forEach(function (p) { ul.appendChild(el('li', null, p)); });
                    wrap.appendChild(ul);
                }

                (st.learning_assets || []).forEach(function (a) {
                    var box = el('div', 'asset');
                    var head = el('div', 'asset-h');
                    head.appendChild(document.createTextNode(a.type || 'note'));
                    if (a.title) head.appendChild(el('em', null, a.title));
                    box.appendChild(head);
                    box.appendChild(el('pre', 'asset-body', a.content || ''));
                    wrap.appendChild(box);
                });

                (st.examples || []).forEach(function (ex) {
                    var box = el('div', 'callout-box');
                    box.appendChild(el('b', null, 'Example'));
                    box.appendChild(document.createTextNode(ex));
                    wrap.appendChild(box);
                });

                (st.common_mistakes || []).forEach(function (m) {
                    var box = el('div', 'callout-box mistake');
                    box.appendChild(el('b', null, 'Easy to get wrong'));
                    box.appendChild(document.createTextNode(m));
                    wrap.appendChild(box);
                });
            });

            host.appendChild(wrap);
        });

        if (tricks.length || examTips.length) {
            var extra = el('section', 'note-sec hw-in');
            extra.id = 'sec-' + sections.length;

            var h2 = el('h2');
            h2.appendChild(el('span', 'sec-n', String(sections.length + 1).padStart(2, '0')));
            h2.appendChild(document.createTextNode('Before the exam'));
            extra.appendChild(h2);

            tricks.forEach(function (t) {
                var box = el('div', 'callout-box memory-trick');
                box.appendChild(el('b', null, 'Memory trick'));
                box.appendChild(document.createTextNode(t));
                extra.appendChild(box);
            });
            examTips.forEach(function (t) {
                var box = el('div', 'callout-box exam-tip');
                box.appendChild(el('b', null, 'Exam tip'));
                box.appendChild(document.createTextNode(t));
                extra.appendChild(box);
            });

            extra.appendChild(el('p', 'margin-note', 'read this page last, the night before'));
            host.appendChild(extra);
        }
    }());

    /* ======================================================================
       6. CONTENTS, REVISED TICKS, READING PROGRESS
       ====================================================================== */
    var noteSections = $$('.note-sec');
    var revised = load('revised', []);
    if (!Array.isArray(revised)) revised = [];

    (function buildToc() {
        var list = $('tocList');
        if (!list) return;

        noteSections.forEach(function (secEl, i) {
            var heading = secEl.querySelector('h2');
            var label = heading ? heading.textContent.replace(/^\d+/, '').trim() : 'Section ' + (i + 1);

            var li = el('li', 'toc-item');
            li.setAttribute('data-idx', i);

            var link = el('button', 'toc-link');
            link.type = 'button';
            link.appendChild(el('span', 'toc-text', label));
            link.addEventListener('click', function () {
                if (activePane !== 'paneNotes') showPane('paneNotes', false);
                var target = $('sec-' + i) || secEl;
                target.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
                document.body.classList.remove('rail-out');
            });

            var tick = el('button', 'toc-tick', '✓');
            tick.type = 'button';
            tick.title = 'Mark as revised';
            tick.setAttribute('aria-label', 'Mark "' + label + '" as revised');
            tick.addEventListener('click', function (e) {
                e.stopPropagation();
                var at = revised.indexOf(i);
                if (at === -1) revised.push(i); else revised.splice(at, 1);
                save('revised', revised);
                paintRevised();
            });

            li.appendChild(link);
            li.appendChild(tick);
            list.appendChild(li);
        });

        /* the chip counts what you can actually tick off, which includes the
           exam-prep sheet the renderer adds — otherwise it disagrees with the
           "n of m" beside the ring */
        if ($('chipSections')) $('chipSections').textContent = noteSections.length || '—';

        paintRevised();
    }());

    function paintRevised() {
        var items = $$('.toc-item');
        items.forEach(function (li) {
            var i = Number(li.getAttribute('data-idx'));
            li.classList.toggle('is-revised', revised.indexOf(i) !== -1);
        });
        var total = items.length || 1;
        var done = revised.length;
        if ($('revisedRing')) $('revisedRing').style.setProperty('--pct', (done / total).toFixed(3));
        if ($('revisedNum')) $('revisedNum').textContent = done;
        if ($('revisedCount')) $('revisedCount').textContent = done + ' of ' + items.length;
    }

    (function trackReading() {
        var sheets = $('sheets');
        var fill = $('readFill');
        if (!sheets) return;

        window.addEventListener('scroll', function () {
            if (fill && activePane === 'paneNotes') {
                var max = document.documentElement.scrollHeight - window.innerHeight;
                fill.style.width = (max > 0 ? (window.scrollY / max) * 100 : 0) + '%';
            }
        }, { passive: true });

        if (!('IntersectionObserver' in window) || !noteSections.length) return;

        /* reveal the handwriting as it comes up the page */
        var revealer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                entry.target.classList.add('is-in');
                revealer.unobserve(entry.target);
            });
        }, { threshold: 0.08 });

        noteSections.forEach(function (s, i) {
            if (reduced || i === 0) s.classList.add('is-in');
            else revealer.observe(s);
        });
        revealIfVisible(noteSections);

        /* which section am I actually reading */
        var current = -1;
        var spy = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                var i = noteSections.indexOf(entry.target);
                if (i === current) return;
                current = i;
                $$('.toc-item').forEach(function (li) {
                    li.classList.toggle('is-current', Number(li.getAttribute('data-idx')) === i);
                });
            });
        }, { rootMargin: '-12% 0px -70% 0px' });

        noteSections.forEach(function (s) { spy.observe(s); });
    }());

    /* ======================================================================
       7. SUMMARY — the revision sheet
       ====================================================================== */
    (function renderSummary() {
        var abstract = $('summaryText');
        if (abstract) {
            var text = DATA.summary || DATA.overview || '';
            var cut = text.indexOf('. ');
            if (cut > 20 && cut < text.length - 2) {
                /* the first sentence is the whole lecture in one line — it gets
                   the highlighter and the display size. The rest is supporting
                   detail, set smaller so the sheet opens with an answer rather
                   than a wall of text. */
                abstract.appendChild(el('span', 'swipe', text.slice(0, cut + 1)));
                abstract.appendChild(el('span', 'rev-rest', text.slice(cut + 2)));
            } else {
                abstract.textContent = text;
            }
        }

        var tk = $('takeawaysList');
        if (tk) takeaways.forEach(function (t) { tk.appendChild(el('li', null, t)); });

        var gl = $('definitionsList');
        if (gl) {
            defs.forEach(function (d, i) {
                var card = el('div', 'def-card');
                card.style.setProperty('--rot', ((i % 3) - 1) * 0.5 + 'deg');
                card.appendChild(el('span', 'def-term', d.term || ''));
                card.appendChild(el('p', 'def-body', d.meaning || ''));
                gl.appendChild(card);
            });
        }

        var mx = $('mixupsList');
        if (mx) {
            if (!mixups.length) {
                mx.appendChild(el('p', 'def-body', 'Nothing flagged as commonly confused in this lecture.'));
            }
            mixups.forEach(function (m) {
                var box = el('div', 'mixup');
                box.appendChild(el('p', 'mixup-t', m.topic || ''));
                var rows = el('div', 'mixup-rows');

                var bad = el('div', 'mixup-row mixup-row--bad');
                bad.appendChild(el('b', null, 'Mixed up'));
                bad.appendChild(el('p', null, m.confusion || ''));

                var good = el('div', 'mixup-row mixup-row--good');
                good.appendChild(el('b', null, 'Actually'));
                good.appendChild(el('p', null, m.correct_concept || ''));

                rows.appendChild(bad);
                rows.appendChild(good);
                box.appendChild(rows);
                mx.appendChild(box);
            });
        }

        var tb = $('termsList');
        if (tb) terms.forEach(function (t) { tb.appendChild(el('li', null, t)); });

        if ($('statSections')) $('statSections').setAttribute('data-count', sections.length);
        if ($('statDefs')) $('statDefs').setAttribute('data-count', defs.length);
        if ($('statTerms')) $('statTerms').setAttribute('data-count', terms.length);
    }());

    var summaryShown = false;
    function revealSummary() {
        var pane = $('paneSummary');
        if (!pane) return;

        var blocks = $$('[data-sr]', pane);
        if (reduced || !('IntersectionObserver' in window)) {
            blocks.forEach(function (b) { b.classList.add('is-in'); });
        } else if (!summaryShown) {
            var obs = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry, i) {
                    if (!entry.isIntersecting) return;
                    var t = entry.target;
                    setTimeout(function () { t.classList.add('is-in'); }, i * 100);
                    obs.unobserve(t);
                });
            }, { threshold: 0.14 });
            blocks.forEach(function (b) { obs.observe(b); });
            revealIfVisible(blocks);
        }

        if (!summaryShown) countUp();
        summaryShown = true;
    }

    function countUp() {
        $$('.count').forEach(function (node) {
            var target = Number(node.getAttribute('data-count')) || 0;
            if (reduced) { node.textContent = target; return; }
            var start = performance.now();
            var dur = 850;
            var settled = false;
            (function step(now) {
                var p = Math.min(1, (now - start) / dur);
                var eased = 1 - Math.pow(1 - p, 3);
                node.textContent = Math.round(target * eased);
                if (p < 1) requestAnimationFrame(step);
                else settled = true;
            })(start);
            /* if frames never arrive, the number still has to be right */
            setTimeout(function () { if (!settled) node.textContent = target; }, dur + 400);
        });
    }

    /* ======================================================================
       8. FLASHCARD DECK
       ====================================================================== */
    var cards = [];

    var deck = (function () {
        var scene   = $('deck');
        var card3d  = $('card3d');
        var stamp   = $('deckStamp');
        var done    = $('deckDone');
        var order   = [];
        var idx     = 0;
        var verdicts = {};      /* card id -> 'got' | 'again' */
        var woken   = false;

        function paintChrome() {
            if ($('deckPos')) $('deckPos').textContent = Math.min(idx + 1, order.length) + ' / ' + order.length;

            var got = 0, again = 0, k;
            for (k in verdicts) {
                if (verdicts[k] === 'got') got++;
                else if (verdicts[k] === 'again') again++;
            }
            if ($('deckKnown')) $('deckKnown').textContent = got + ' filed';

            var pips = $('deckPips');
            if (pips) {
                pips.innerHTML = '';
                order.forEach(function (c, i) {
                    var p = el('span', 'pip');
                    if (verdicts[c.id] === 'got') p.classList.add('is-got');
                    else if (verdicts[c.id] === 'again') p.classList.add('is-again');
                    if (i === idx) p.classList.add('is-now');
                    pips.appendChild(p);
                });
            }

            var left = order.length - idx;
            scene.classList.toggle('no-1', left <= 1);
            scene.classList.toggle('no-2', left <= 2);

            if ($('btnPrev')) $('btnPrev').disabled = idx === 0;
            if ($('btnNext')) $('btnNext').disabled = idx >= order.length - 1;
            return { got: got, again: again };
        }

        function paint(dir) {
            if (idx >= order.length) return finish();

            var c = order[idx];
            card3d.classList.remove('is-flipped');
            card3d.hidden = false;
            if (done) done.hidden = true;

            $('fcType').textContent = c.type || 'card';
            $('fcDiff').textContent = c.difficulty || '';
            $('fcDiff').setAttribute('data-d', c.difficulty || 'medium');
            $('fcTopic').textContent = c.topic || '';
            $('fcQuestion').textContent = c.question || '';
            $('fcAnswer').textContent = c.answer || '';

            paintChrome();

            if (!reduced) {
                scene.style.setProperty('--dir', dir === -1 ? -1 : 1);
                scene.classList.remove('is-deal');
                void scene.offsetWidth;
                scene.classList.add('is-deal');
            }
        }

        function flip() {
            if (idx >= order.length) return;
            card3d.classList.toggle('is-flipped');
            if (!reduced && card3d.classList.contains('is-flipped')) {
                scene.classList.remove('is-lift');
                void scene.offsetWidth;
                scene.classList.add('is-lift');
            }
        }

        function move(step) {
            var next = idx + step;
            if (next < 0) return;
            idx = next;
            if (idx >= order.length) finish();
            else paint(step < 0 ? -1 : 1);
        }

        function rate(kind) {
            if (idx >= order.length) return;
            verdicts[order[idx].id] = kind;
            paintChrome();

            if (stamp) {
                stamp.textContent = kind === 'got' ? 'filed' : 'again';
                stamp.className = 'deck-stamp is-on ' + (kind === 'got' ? 'is-got' : 'is-again');
                setTimeout(function () { stamp.className = 'deck-stamp'; }, 820);
            }

            setTimeout(function () { move(1); }, reduced ? 60 : 520);
        }

        function finish() {
            var tally = paintChrome();
            card3d.hidden = true;
            if (!done) return;
            done.hidden = false;

            var flagged = order.filter(function (c) { return verdicts[c.id] === 'again'; });
            $('deckDoneS').textContent = tally.got + ' of ' + order.length +
                ' filed away' + (flagged.length ? ', ' + flagged.length + ' still shaky.' : '. Clean sweep.');
            $('deckAgain').textContent = flagged.length
                ? 'Redo the ' + flagged.length + ' you flagged'
                : 'Shuffle and go again';
        }

        function restart(only) {
            order = shuffle(only && only.length ? only : cards);
            idx = 0;
            if (!only) verdicts = {};
            paint(1);
        }

        function start(list) {
            cards = list;
            order = shuffle(list);
            idx = 0;
            verdicts = {};
            card3d.setAttribute('tabindex', '0');
            card3d.setAttribute('role', 'button');
            card3d.setAttribute('aria-label', 'Flashcard — activate to see the answer');
            paint(1);
        }

        if (card3d) {
            card3d.addEventListener('click', function (e) {
                if (e.target.closest('.verdict')) return;
                flip();
            });
            card3d.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); flip(); }
            });
        }
        if ($('btnGot')) $('btnGot').addEventListener('click', function (e) { e.stopPropagation(); rate('got'); });
        if ($('btnAgain')) $('btnAgain').addEventListener('click', function (e) { e.stopPropagation(); rate('again'); });
        if ($('btnNext')) $('btnNext').addEventListener('click', function () { move(1); });
        if ($('btnPrev')) $('btnPrev').addEventListener('click', function () { move(-1); });
        if ($('deckAgain')) $('deckAgain').addEventListener('click', function () {
            var flagged = order.filter(function (c) { return verdicts[c.id] === 'again'; });
            restart(flagged);
        });

        return {
            start: start,
            flip: flip,
            move: move,
            rate: rate,
            wake: function () {
                if (woken || !order.length) { woken = true; return; }
                woken = true;
                paint(1);
            }
        };
    }());

    /* pull the real deck the pipeline generated; fall back to the glossary */
    function fallbackCards() {
        return defs.map(function (d, i) {
            return {
                id: 'def-' + i,
                question: 'What does "' + (d.term || '') + '" mean?',
                answer: d.meaning || '',
                type: 'definition',
                difficulty: 'medium',
                topic: 'Glossary'
            };
        });
    }

    /* use the per-video flashcards the pipeline generated (injected into this
       page as DATA.flashcards); fall back to glossary-derived cards when none
       were produced. No network fetch — the old /api/flashcards endpoint served
       one global deck shared across every video. */
    (function initDeck() {
        var list = Array.isArray(DATA.flashcards) ? DATA.flashcards.slice() : [];
        if (!list.length) list = fallbackCards();
        list = list.map(function (c, i) {
            if (c.id == null) c.id = 'c-' + i;
            return c;
        });
        if ($('chipCards')) $('chipCards').textContent = list.length;
        if ($('statCards')) $('statCards').setAttribute('data-count', list.length);
        if (list.length) deck.start(list);
        else if ($('fcQuestion')) $('fcQuestion').textContent = 'No flashcards for this lecture yet.';
        buildQuizPool(list);
    }());

    /* ======================================================================
       9. QUIZ — a practice paper marked in red pen
       Every wrong option is a real answer from elsewhere in this lecture,
       so the shape of an option never gives it away.
       ====================================================================== */
    var pool = [];

    function buildQuizPool(list) {
        pool = [];

        /* recall questions straight off the flashcards */
        list.forEach(function (c) {
            if (!c.question || !c.answer) return;
            var siblings = list.filter(function (o) {
                return o.id !== c.id && o.answer && o.type === c.type;
            });
            if (siblings.length < 3) {
                siblings = list.filter(function (o) { return o.id !== c.id && o.answer; });
            }
            if (siblings.length < 3) return;
            pool.push({
                topic: c.topic || 'This lecture',
                weak: c.topic || 'This lecture',
                text: c.question,
                right: c.answer,
                wrong: shuffle(siblings).slice(0, 3).map(function (o) { return o.answer; })
            });
        });

        /* term-matching from the glossary — shorter options, changes the rhythm */
        defs.forEach(function (d) {
            if (!d.term || !d.meaning) return;
            var others = defs.filter(function (o) { return o.term !== d.term; });
            if (others.length < 3) return;
            pool.push({
                topic: 'Glossary',
                /* the term, not the tab it came from — "re-read Glossary" is
                   no help, "re-read Chunk overlap" is */
                weak: d.term,
                text: 'Which term does this describe? “' + d.meaning + '”',
                right: d.term,
                wrong: shuffle(others).slice(0, 3).map(function (o) { return o.term; })
            });
        });

        /* the mix-ups make the sharpest questions — ask for the correction */
        mixups.forEach(function (m) {
            if (!m.topic || !m.correct_concept) return;
            var others = mixups.filter(function (o) { return o.topic !== m.topic; });
            var wrong = [m.confusion].concat(others.map(function (o) { return o.correct_concept; }));
            if (wrong.length < 3) return;
            pool.push({
                topic: 'Easy to mix up',
                weak: m.topic,
                text: 'People get ' + m.topic + ' wrong. What\'s actually true?',
                right: m.correct_concept,
                wrong: wrong.slice(0, 3)
            });
        });

        var best = load('quizbest', null);
        if (best && $('quizBest')) {
            $('quizBest').hidden = false;
            $('quizBest').textContent = 'Best so far: ' + best.pct + '% (' + best.right + ' of ' + best.total + ')';
        }
    }

    (function quiz() {
        var startBox  = $('quizStart');
        var runBox    = $('quizRun');
        var resultBox = $('quizResult');
        if (!startBox || !runBox || !resultBox) return;

        var paper = [];
        var at = 0;
        var right = 0;
        var missed = [];
        var locked = false;
        var LETTERS = ['A', 'B', 'C', 'D'];

        function begin() {
            if (!pool.length) {
                $('quizGo').textContent = 'Not enough notes to build a paper';
                $('quizGo').disabled = true;
                return;
            }

            var want = 5;
            var picked = document.querySelector('input[name="qlen"]:checked');
            if (picked) want = Number(picked.value) || 0;

            paper = shuffle(pool);
            if (want > 0) paper = paper.slice(0, Math.min(want, paper.length));

            at = 0; right = 0; missed = []; locked = false;

            startBox.hidden = true;
            resultBox.hidden = true;
            runBox.hidden = false;
            render();
        }

        function render() {
            var q = paper[at];
            locked = false;

            $('quizCount').textContent = 'Q' + (at + 1) + ' / ' + paper.length;
            $('quizScore').textContent = right + ' right';
            $('quizFill').style.width = ((at / paper.length) * 100) + '%';

            $('qTopic').textContent = q.topic;
            $('qText').textContent = q.text;
            $('qMark').hidden = true;
            $('qMark').classList.remove('is-wrong');
            $('qNext').hidden = true;
            $('qNext').textContent = at === paper.length - 1 ? 'See the marks →' : 'Next question →';

            var opts = $('qOpts');
            opts.innerHTML = '';
            var choices = shuffle([q.right].concat(q.wrong));

            choices.forEach(function (choice, i) {
                var li = el('li');
                var btn = el('button', 'qopt');
                btn.type = 'button';
                btn.appendChild(el('span', 'qopt-k', LETTERS[i]));
                btn.appendChild(el('span', 'qopt-t', choice));
                btn.addEventListener('click', function () { answer(btn, choice === q.right, q); });
                li.appendChild(btn);
                opts.appendChild(li);
            });

            var card = $('qcard');
            card.classList.remove('is-new');
            void card.offsetWidth;
            if (!reduced) card.classList.add('is-new');
        }

        function answer(btn, correct, q) {
            if (locked) return;
            locked = true;

            var buttons = $$('.qopt', $('qOpts'));
            buttons.forEach(function (b) {
                b.disabled = true;
                var label = b.querySelector('.qopt-t').textContent;
                if (label === q.right) b.classList.add('is-right');
                else if (b === btn) b.classList.add('is-wrong');
                else b.classList.add('is-dim');
            });

            if (correct) right++;
            else missed.push(q.weak || q.topic);

            var mark = $('qMark');
            var glyph = $('qMarkGlyph');
            glyph.innerHTML = correct
                ? '<path d="M9 25 L19 35 L39 11"/>'
                : '<path d="M12 12 L36 36"/><path d="M36 12 L12 36"/>';
            mark.classList.toggle('is-wrong', !correct);
            $('qVerdict').textContent = correct ? 'Right.' : 'Not that one.';
            $('qWhy').textContent = correct
                ? 'Filed under ' + (q.weak || q.topic) + '.'
                : 'The right answer is marked above. Re-read ' + (q.weak || q.topic) + '.';
            mark.hidden = false;

            $('quizScore').textContent = right + ' right';
            $('quizFill').style.width = (((at + 1) / paper.length) * 100) + '%';
            $('qNext').hidden = false;
            $('qNext').focus({ preventScroll: true });
        }

        function next() {
            at++;
            if (at >= paper.length) finish();
            else render();
        }

        function finish() {
            runBox.hidden = true;
            resultBox.hidden = false;

            var pct = Math.round((right / paper.length) * 100);
            $('gradePct').textContent = pct + '%';

            var line, note;
            if (pct === 100)      { line = 'Full marks.'; note = 'Nothing left to revise here. Tick the sections off in the contents list and move on.'; }
            else if (pct >= 80)   { line = 'Solid.'; note = 'You know this lecture. Skim the topics below once more and you\'re done with it.'; }
            else if (pct >= 55)   { line = 'Half there.'; note = 'The shape is right but the details aren\'t sticking yet. Run the flashcard deck, then sit this again.'; }
            else                  { line = 'Worth a second pass.'; note = 'Read the notes tab properly before the next attempt — this paper only asks what\'s in them.'; }

            $('markLine').textContent = line;
            $('markNote').textContent = note;

            /* re-run the red-pen circle every time the sheet appears */
            var ring = $('gradeCircle');
            if (ring && !reduced) {
                ring.style.animation = 'none';
                void ring.getBoundingClientRect();
                ring.style.animation = '';
            }

            var unique = missed.filter(function (t, i) { return missed.indexOf(t) === i; });
            var box = $('weakspots');
            if (unique.length) {
                box.hidden = false;
                var ul = $('weakList');
                ul.innerHTML = '';
                unique.forEach(function (t) { ul.appendChild(el('li', null, t)); });
            } else {
                box.hidden = true;
            }

            var best = load('quizbest', null);
            if (!best || pct > best.pct) {
                save('quizbest', { pct: pct, right: right, total: paper.length });
                if ($('quizBest')) {
                    $('quizBest').hidden = false;
                    $('quizBest').textContent = 'Best so far: ' + pct + '% (' + right + ' of ' + paper.length + ')';
                }
            }
        }

        $('quizGo').addEventListener('click', begin);
        $('qNext').addEventListener('click', next);
        $('quizRetry').addEventListener('click', function () {
            resultBox.hidden = true;
            startBox.hidden = false;
        });
        $('quizToNotes').addEventListener('click', function () { showPane('paneNotes', true); });
    }());

    /* ======================================================================
       10. KEYBOARD — only where it makes sense
       ====================================================================== */
    document.addEventListener('keydown', function (e) {
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        var tag = (document.activeElement && document.activeElement.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
        if (activePane !== 'paneCards') return;

        if (e.key === ' ' || e.key === 'Spacebar') { e.preventDefault(); deck.flip(); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); deck.move(1); }
        else if (e.key === 'ArrowLeft')  { e.preventDefault(); deck.move(-1); }
        else if (e.key === '1') { deck.rate('again'); }
        else if (e.key === '2') { deck.rate('got'); }
    });

}());
