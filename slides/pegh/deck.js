(() => {
  'use strict';
  const slides = [...document.querySelectorAll('#stage > .slide')];
  const viewport = document.getElementById('viewport');
  const counter = document.getElementById('counter');
  const previous = document.getElementById('prev-button');
  const next = document.getElementById('next-button');
  const overview = document.getElementById('overview');
  const overviewGrid = document.getElementById('overview-grid');
  const notesPanel = document.getElementById('notes-panel');
  const notesButton = document.getElementById('notes-button');
  const help = document.getElementById('help');
  const progress = document.getElementById('progress');
  const params = new URLSearchParams(location.search);
  const hashNumber = Number((location.hash.match(/^#slide-(\d+)$/) || [])[1]);
  const requested = Math.trunc(Number(params.get('slide'))) || hashNumber || 1;
  let current = Math.max(0, Math.min(slides.length - 1, requested - 1));
  let touchStart = null;

  function resize() {
    const css = getComputedStyle(viewport);
    const width = viewport.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight);
    const height = viewport.clientHeight - parseFloat(css.paddingTop) - parseFloat(css.paddingBottom);
    const scale = Math.max(.1, Math.min(width / 1280, height / 720));
    document.documentElement.style.setProperty('--scale', String(scale));
    overviewGrid.querySelectorAll('.overview-preview').forEach(preview => {
      preview.firstElementChild.style.transform = `scale(${preview.clientWidth / 1280})`;
    });
  }

  function renderNotes() {
    document.getElementById('notes-title').textContent = `${String(current + 1).padStart(2, '0')} · ${slides[current].dataset.title}`;
    document.getElementById('notes-content').innerHTML = slides[current].querySelector('.speaker-notes').innerHTML;
  }

  function showSlide(index, {announce = true, updateHash = true} = {}) {
    current = Math.max(0, Math.min(slides.length - 1, index));
    slides.forEach((slide, i) => {
      const active = i === current;
      slide.classList.toggle('is-active', active);
      slide.setAttribute('aria-hidden', String(!active));
      slide.inert = !active;
      slide.querySelector('.page').textContent = String(i + 1);
    });
    previous.disabled = current === 0;
    next.disabled = current === slides.length - 1;
    counter.textContent = `${String(current + 1).padStart(2, '0')} / ${slides.length}`;
    progress.style.width = `${((current + 1) / slides.length) * 100}%`;
    document.title = `PE-GH · ${current + 1}/${slides.length} · ${slides[current].dataset.title}`;
    if (updateHash) {
      try { history.replaceState(null, '', `${location.pathname}${location.search}#slide-${current + 1}`); }
      catch { /* Some local-file browser policies disallow history updates. */ }
    }
    if (announce) document.getElementById('status').textContent = `Trang ${current + 1} trên ${slides.length}: ${slides[current].dataset.title}`;
    overviewGrid.querySelectorAll('button').forEach((button, i) => button.setAttribute('aria-current', String(i === current)));
    renderNotes();
  }

  function setNotes(open) {
    notesPanel.hidden = !open;
    notesButton.setAttribute('aria-pressed', String(open));
    document.body.classList.toggle('notes-open', open);
    resize();
  }

  function createOverview() {
    if (overviewGrid.children.length) return;
    slides.forEach((slide, index) => {
      const button = document.createElement('button');
      button.className = 'overview-item';
      button.type = 'button';
      button.setAttribute('aria-label', `Trang ${index + 1}: ${slide.dataset.title}`);
      const preview = document.createElement('div');
      preview.className = 'overview-preview';
      const clone = slide.cloneNode(true);
      clone.removeAttribute('id');
      clone.removeAttribute('aria-labelledby');
      clone.setAttribute('aria-hidden', 'true');
      clone.inert = true;
      clone.querySelectorAll('[id]').forEach(element => element.removeAttribute('id'));
      clone.querySelectorAll('.speaker-notes').forEach(element => element.remove());
      preview.append(clone);
      const label = document.createElement('span');
      label.className = 'overview-label';
      const number = document.createElement('span');
      number.textContent = String(index + 1).padStart(2, '0');
      const text = document.createElement('span');
      text.textContent = slide.dataset.title;
      label.append(number, text);
      button.append(preview, label);
      button.addEventListener('click', () => { showSlide(index); overview.close(); });
      overviewGrid.append(button);
    });
  }

  function openOverview() {
    createOverview();
    overview.showModal();
    resize();
    overviewGrid.children[current]?.focus();
  }

  async function fullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
      else document.getElementById('status').textContent = 'Trình duyệt chưa hỗ trợ toàn màn hình. Hãy dùng F11 trên máy tính.';
    } catch {
      document.getElementById('status').textContent = 'Trình duyệt chặn toàn màn hình. Hãy dùng F11 trên máy tính.';
    }
  }

  previous.addEventListener('click', () => showSlide(current - 1));
  next.addEventListener('click', () => showSlide(current + 1));
  document.getElementById('overview-button').addEventListener('click', openOverview);
  document.getElementById('close-overview').addEventListener('click', () => overview.close());
  notesButton.addEventListener('click', () => setNotes(notesPanel.hidden));
  document.getElementById('close-notes').addEventListener('click', () => setNotes(false));
  document.getElementById('fullscreen-button').addEventListener('click', fullscreen);
  document.getElementById('print-button').addEventListener('click', () => window.print());
  document.getElementById('help-button').addEventListener('click', () => help.showModal());
  document.getElementById('close-help').addEventListener('click', () => help.close());
  for (const modal of [overview, help]) {
    modal.addEventListener('click', event => { if (event.target === modal) modal.close(); });
  }
  document.addEventListener('keydown', event => {
    if (event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
    if (event.key === 'Escape') {
      if (overview.open) overview.close();
      else if (help.open) help.close();
      else setNotes(false);
      return;
    }
    if (overview.open || help.open || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.target.closest('button, a') && [' ', 'Enter'].includes(event.key)) return;
    const key = event.key.toLowerCase();
    const actions = {
      arrowright: () => showSlide(current + 1), pagedown: () => showSlide(current + 1),
      ' ': () => showSlide(current + (event.shiftKey ? -1 : 1)),
      arrowleft: () => showSlide(current - 1), pageup: () => showSlide(current - 1),
      home: () => showSlide(0), end: () => showSlide(slides.length - 1),
      f: fullscreen, o: openOverview, n: () => setNotes(notesPanel.hidden),
      '?': () => help.showModal(),
    };
    if (actions[key]) { event.preventDefault(); actions[key](); }
  });
  viewport.addEventListener('touchstart', event => {
    if (event.touches.length === 1) touchStart = {x: event.touches[0].clientX, y: event.touches[0].clientY};
  }, {passive: true});
  viewport.addEventListener('touchend', event => {
    if (!touchStart || !event.changedTouches.length) return;
    const dx = event.changedTouches[0].clientX - touchStart.x;
    const dy = event.changedTouches[0].clientY - touchStart.y;
    if (Math.abs(dx) > 55 && Math.abs(dx) > Math.abs(dy) * 1.5) showSlide(current + (dx < 0 ? 1 : -1));
    touchStart = null;
  }, {passive: true});
  window.addEventListener('resize', resize);
  window.addEventListener('hashchange', () => {
    const number = Number((location.hash.match(/^#slide-(\d+)$/) || [])[1]);
    if (number) showSlide(number - 1, {updateHash: false});
  });
  document.addEventListener('fullscreenchange', resize);
  new ResizeObserver(resize).observe(viewport);
  showSlide(current, {announce: false});
  resize();

  // Passive headless render checks. Enabled only with ?qa=1.
  if (params.get('qa') === '1') {
    const assetLoads = [...document.querySelectorAll('#stage img')].map(img => new Promise(resolve => {
      if (img.complete) resolve();
      else { img.addEventListener('load', resolve, {once: true}); img.addEventListener('error', resolve, {once: true}); }
    }));
    Promise.all([document.fonts.ready, ...assetLoads]).then(() => setTimeout(() => {
      const initial = current;
      const errors = [];
      const bounds = [];
      document.querySelectorAll('#stage img').forEach(img => {
        if (!img.complete || !img.naturalWidth) errors.push(`image missing: ${img.alt}`);
      });
      if (document.querySelector('#stage .slide-bottom, #stage .takeaway, #stage .reference-note')) errors.push('obsolete bottom text strip');
      showSlide(-100, {announce: false});
      if (current !== 0 || !previous.disabled) errors.push('first-slide clamp');
      showSlide(100, {announce: false});
      if (current !== slides.length - 1 || !next.disabled) errors.push('last-slide clamp');
      showSlide(0, {announce: false});
      document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}));
      if (current !== 1) errors.push('right-arrow key');
      next.click();
      if (current !== 2) errors.push('next button');
      document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Home', bubbles: true}));
      if (current !== 0) errors.push('home key');
      for (let i = 0; i < slides.length; i++) {
        showSlide(i, {announce: false});
        slides[i].style.animation = 'none';
        const box = slides[i].getBoundingClientRect();
        const scale = box.width / 1280;
        const contentLimit = box.bottom - 64 * scale;
        const overflowing = [];
        const title = slides[i].querySelector('h2');
        if (title && title.getBoundingClientRect().height > 65 * scale) {
          overflowing.push({tag: 'TITLE', text: 'Content heading wraps beyond one line'});
        }
        slides[i].querySelectorAll('h1,h2,h3,p,table,.content-bound,figure,img').forEach(element => {
          if (element.closest('.speaker-notes, .institution-header')) return;
          const rect = element.getBoundingClientRect();
          if (rect.right > box.right - 50 * scale || rect.left < box.left + 50 * scale || rect.bottom > contentLimit + 2 || rect.top < box.top) {
            overflowing.push({tag: element.tagName, text: element.textContent.trim().slice(0, 65)});
          }
        });
        let bodyMetrics = null;
        const body = slides[i].querySelector('.slide-body');
        if (body) {
          const bodyBox = body.getBoundingClientRect();
          const blocks = [...body.children].map(element => element.getBoundingClientRect());
          const top = Math.min(...blocks.map(rect => rect.top));
          const bottom = Math.max(...blocks.map(rect => rect.bottom));
          bodyMetrics = {
            spaceAbove: Math.round((top - bodyBox.top) / scale),
            spaceBelow: Math.round((bodyBox.bottom - bottom) / scale),
          };
          if (top < bodyBox.top - 2 * scale || bottom > bodyBox.bottom + 2 * scale) {
            overflowing.push({tag: 'BODY', text: 'Content exceeds the allocated body area'});
          }
        }
        bounds.push({slide: i + 1, overflowing, body: bodyMetrics});
        if (overflowing.length) errors.push(`slide ${i + 1}: bounds`);
      }
      setNotes(true);
      if (notesPanel.hidden || !document.getElementById('notes-content').textContent.trim()) errors.push('notes');
      setNotes(false);
      openOverview();
      if (overviewGrid.children.length !== slides.length) errors.push('overview size');
      overview.close();
      const ids = [...document.querySelectorAll('[id]')].map(element => element.id);
      if (new Set(ids).size !== ids.length) errors.push('duplicate IDs');
      showSlide(initial, {announce: false});
      const report = {passed: !errors.length, slideCount: slides.length, imageCount: document.querySelectorAll('#stage img').length, errors, bounds};
      window.__SLIDE_QA__ = report;
      const output = document.createElement('pre');
      output.id = 'qa-report';
      output.hidden = true;
      output.dataset.status = report.passed ? 'passed' : 'failed';
      output.textContent = JSON.stringify(report);
      document.body.append(output);
    }, 100));
  }
})();
