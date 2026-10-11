/* ==========================================================
   LearnTube — landing page interactions
   Everything here is an enhancement. With JS off, the form
   still posts straight to /process and the page still reads.
   ========================================================== */

(function () {
    'use strict';

    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* ------------------------------------------------------
       1. Index-card tilt
       Each card declares its own angle so the row looks like
       cards dropped on a desk rather than a grid.
    ------------------------------------------------------ */
    document.querySelectorAll('[data-tilt]').forEach(function (el) {
        el.style.setProperty('--tilt', el.getAttribute('data-tilt') + 'deg');
    });

    /* ------------------------------------------------------
       2. Scroll reveal
    ------------------------------------------------------ */
    var revealables = document.querySelectorAll('.reveal');

    if (reduced || !('IntersectionObserver' in window)) {
        revealables.forEach(function (el) { el.classList.add('is-in'); });
    } else {
        var revealObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry, i) {
                if (!entry.isIntersecting) return;
                var el = entry.target;
                setTimeout(function () { el.classList.add('is-in'); }, i * 90);
                revealObserver.unobserve(el);
            });
        }, { threshold: 0.18, rootMargin: '0px 0px -60px' });

        revealables.forEach(function (el) { revealObserver.observe(el); });
    }

    /* ------------------------------------------------------
       3. The transcript ticks along like it's being spoken
       Only runs while the spread is actually on screen.
    ------------------------------------------------------ */
    var transcript = document.getElementById('transcript');

    if (transcript && !reduced) {
        var lines = Array.prototype.slice.call(transcript.querySelectorAll('p'));
        var cursor = 0;
        var timer = null;

        function tick() {
            if (cursor >= lines.length) {
                // hold the full page for a beat, then start over
                timer = setTimeout(function () {
                    lines.forEach(function (l) { l.classList.remove('is-said'); });
                    cursor = 0;
                    tick();
                }, 2600);
                return;
            }
            lines[cursor].classList.add('is-said');
            cursor += 1;
            timer = setTimeout(tick, 480);
        }

        function stop() {
            if (timer) { clearTimeout(timer); timer = null; }
        }

        if ('IntersectionObserver' in window) {
            new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        if (!timer) tick();
                    } else {
                        stop();
                    }
                });
            }, { threshold: 0.25 }).observe(transcript);
        } else {
            tick();
        }
    }

    /* ------------------------------------------------------
       4. Sample loader
       Submits the "__sample__" sentinel, which /process maps
       to the prebuilt notebook (json_txt.json) instead of
       running the full pipeline.
    ------------------------------------------------------ */
    var form  = document.getElementById('paste');
    var input = document.getElementById('youtube_url');
    var chip  = document.getElementById('sampleChip');

    if (chip && form && input) {
        chip.addEventListener('click', function () {
            input.value = '__sample__';
            if (typeof form.requestSubmit === 'function') {
                form.requestSubmit();
            } else {
                form.dispatchEvent(new Event('submit', { cancelable: true }));
            }
        });
    }

    /* ------------------------------------------------------
       4b. Continue chip — last video from localStorage
    ------------------------------------------------------ */
    var continueChip  = document.getElementById('continueChip');
    var continueTitle = document.getElementById('continueTitle');

    if (continueChip && continueTitle) {
        try {
            var last = JSON.parse(localStorage.getItem('lt_last_video') || 'null');
            if (last && last.id && last.title) {
                continueTitle.textContent = last.title;
                continueChip.hidden = false;
                continueChip.addEventListener('click', function () {
                    // Re-submit with the video URL format that triggers the cache hit
                    // We post the video URL which will hit the cache
                    input.value = 'https://www.youtube.com/watch?v=' + last.id;
                    if (typeof form.requestSubmit === 'function') {
                        form.requestSubmit();
                    } else {
                        form.dispatchEvent(new Event('submit', { cancelable: true }));
                    }
                });
            }
        } catch (e) { /* localStorage may be blocked */ }
    }

    /* ------------------------------------------------------
       5. Processing overlay
       Staged to mirror the real pipeline order.
       The form submits normally — the overlay runs until the
       browser navigates to the result page.
    ------------------------------------------------------ */
    var proc      = document.getElementById('proc');
    var procTitle = document.getElementById('procTitle');
    var procFill  = document.getElementById('procFill');
    var procSteps = proc ? proc.querySelectorAll('[data-step]') : [];

    // Approximate durations for each pipeline step (ms). This is a FAKE
    // animation — it is NOT tied to real backend progress. When the steps run
    // out it just holds at 95% ("Almost done…") until the synchronous POST to
    // /process actually returns and the browser navigates to the result page.
    var durations = [4000, 3000, 3000, 5000, 25000, 15000, 12000, 8000];

    function runOverlay() {
        proc.hidden = false;
        document.body.style.overflow = 'hidden';

        var total = procSteps.length;
        var i = 0;

        function advance() {
            if (i > 0) {
                procSteps[i - 1].classList.remove('is-active');
                procSteps[i - 1].classList.add('is-done');
            }

            if (i >= total) {
                // All steps shown — hold on the last one
                procFill.style.width = '95%';
                procTitle.textContent = 'Almost done — finishing up…';
                return;
            }

            var step = procSteps[i];
            step.classList.add('is-active');
            procTitle.textContent = step.textContent.trim();
            procFill.style.width = Math.round(((i + 1) / total) * 90) + '%';

            i += 1;
            setTimeout(advance, reduced ? 200 : durations[i - 1] || 5000);
        }

        advance();
    }

    if (form && input && proc) {
        form.addEventListener('submit', function (e) {
            var value = input.value.trim();

            if (!value) {
                e.preventDefault();
                input.classList.add('is-invalid');
                input.focus();
                setTimeout(function () { input.classList.remove('is-invalid'); }, 600);
                return;
            }

            // For the sample notebook, use the quick animation
            if (value === '__sample__') {
                e.preventDefault();
                var quickDurations = [400, 300, 300, 200, 200, 200, 200, 200];
                // Override durations temporarily
                var origDurations = durations;
                durations = quickDurations;
                runOverlay();
                durations = origDurations;
                // Submit after quick animation
                setTimeout(function () {
                    HTMLFormElement.prototype.submit.call(form);
                }, 2200);
                return;
            }

            // For real URLs: show overlay while the form submits normally
            // The browser will navigate to the result page when the server responds
            runOverlay();
            // Allow the default form submission to proceed
        });
    }

    /* ------------------------------------------------------
       6. Paste straight into the box from anywhere on the page
    ------------------------------------------------------ */
    if (input) {
        document.addEventListener('paste', function (e) {
            if (document.activeElement === input) return;

            var tag = (document.activeElement.tagName || '').toLowerCase();
            if (tag === 'input' || tag === 'textarea') return;

            var text = (e.clipboardData || window.clipboardData).getData('text') || '';
            if (!/youtu\.?be/i.test(text)) return;

            e.preventDefault();
            input.value = text.trim();
            input.focus();
            input.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
        });
    }
}());

/* ----------------------------------------------------------
   Added: path tabs (single lecture / whole playlist) + playlist entry
---------------------------------------------------------- */
(function () {
    'use strict';

    var tabs = Array.prototype.slice.call(document.querySelectorAll('.pathtab'));

    function activate(tab, focus) {
        tabs.forEach(function (t) {
            var on = t === tab;
            t.classList.toggle('is-active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
            var f = document.getElementById(t.getAttribute('data-target'));
            if (f) f.hidden = !on;
        });
        if (focus) {
            var active = document.getElementById(tab.getAttribute('data-target'));
            var inp = active && active.querySelector('input[type="text"]');
            if (inp) inp.focus();
        }
    }

    tabs.forEach(function (t) {
        t.addEventListener('click', function () { activate(t, true); });
    });

    /* playlist form → brief "opening your course map" overlay, then submit */
    var pform = document.getElementById('formPlaylist');
    var pinput = document.getElementById('playlist_url');
    var proc = document.getElementById('proc');
    var procTitle = document.getElementById('procTitle');
    var procSteps = document.getElementById('procSteps');
    var procFill = document.getElementById('procFill');

    if (pform && pinput) {
        pform.addEventListener('submit', function (e) {
            if (!pinput.value.trim()) {
                e.preventDefault();
                pinput.classList.add('is-invalid');
                pinput.focus();
                setTimeout(function () { pinput.classList.remove('is-invalid'); }, 500);
                return;
            }
            if (proc) {
                proc.hidden = false;
                document.body.style.overflow = 'hidden';
                if (procTitle) procTitle.textContent = 'Opening your course map…';
                if (procSteps) procSteps.hidden = true;
                if (procFill) procFill.style.width = '85%';
            }
        });
    }
}());
