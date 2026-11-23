(() => {
  'use strict';

  // ---- language: Chinese as written, English from i18n.js ---------------------
  // The page is written in Chinese; t() gives the English when the viewer reads
  // English, filling in the values ({0}, {1}…). Sentences the server writes go
  // through tx(), which also recognises them with their values in place.
  const I18N = window.TL_I18N || { en: {}, server: {} };
  const LANG = (() => {
    try {
      const chosen = localStorage.getItem('tl-lang');
      if (chosen === 'zh' || chosen === 'en') return chosen;
    } catch (error) { /* no storage: follow the browser */ }
    const wanted = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || 'zh'];
    return wanted.some((tag) => /^zh/i.test(tag)) ? 'zh' : 'en';
  })();
  const LOCALE = LANG === 'en' ? 'en-US' : 'zh-CN';
  document.documentElement.lang = LANG === 'en' ? 'en' : 'zh-CN';
  document.title = LANG === 'en' ? 'Time Library · Server' : '忆凡尘 · 服务端';
  const fill = (text, args) => (args.length ? text.replace(/\{(\d+)\}/g, (slot, n) => (args[n] === undefined ? slot : String(args[n]))) : text);
  function t(key, ...args) {
    return fill(LANG === 'en' && I18N.en[key] ? I18N.en[key] : key, args);
  }
  const SERVER_PATTERNS = Object.entries(I18N.server || {}).map(([zh, en]) => {
    const order = (zh.match(/\{\d+\}/g) || []).map((slot) => Number(slot.slice(1, -1)));
    const source = zh.split(/\{\d+\}/).map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('(.+?)');
    return [new RegExp(`^${source}$`), order, en];
  });
  function tx(text) {
    if (LANG !== 'en' || !text) return text;
    if (I18N.en[text]) return I18N.en[text];
    for (const [pattern, order, en] of SERVER_PATTERNS) {
      const found = pattern.exec(text);
      if (found) {
        const args = [];
        order.forEach((n, index) => { args[n] = found[index + 1]; });
        return fill(en, args);
      }
    }
    return text;
  }
  function switchLanguage() {
    try { localStorage.setItem('tl-lang', LANG === 'en' ? 'zh' : 'en'); } catch (error) { /* this page only */ }
    location.reload();
  }
  const languageButton = () => h('button', { class: 'btn quiet lang-switch', type: 'button', lang: LANG === 'en' ? 'zh-CN' : 'en', onclick: switchLanguage },
    LANG === 'en' ? '中文' : 'English');

  const root = document.getElementById('app');
  const REFRESH_MS = 10000;

  const state = {
    route: 'overview',
    gate: null, // 'setup' | 'login' | null (signed in)
    gateError: '',
    gateBusy: false,
    devices: null,
    overview: null,
    now: Date.now() / 1000,
    loadError: '',
    pairing: null, // { token, expires_at }
    pairingBusy: false,
    showToken: false,
    copied: '',
    more: null, // device id whose "connect another agent" sentence is open
    confirm: null, // { title, body, action, run }
    confirmBusy: false,
    models: null, // { sources, slots, protocols }
    sourceForm: null, // { id | null, name, base_url, protocol, api_key }
    sourceBusy: {}, // source id -> what is running
    sourceNote: {}, // source id -> { ok, text }
    shownKeys: {}, // source id -> key, while revealed
    picker: null, // source id whose model list is open
    slotBusy: {}, // "slot:role" -> true
    slotNote: {}, // "slot:role" -> { ok, text }
    localModel: null, // the built-in local model's status
    distill: null, // distillation status
    memories: null, // { memories, counts, retention_days, now }
    memQuery: '',
    memFilter: '', // '' | 'active' | 'expired' | 'folded'
    memShelf: '', // '' | 'zhiyi' | 'xingce' | 'toolbook' | 'experience' | 'errata'
    evolution: null, // how memories are replaced and drawn up into experience
    vectors: null, // recall by meaning: the small embedding model on the server
    projects: null, // declared projects, each with its memories, experience and whiteboard
    doctor: null, // the nightly checkup and the memory on/off comparison
    update: null, // the server's version, the newest release, and an update under way
    updateLooking: false, // asking GitHub which release is newest
    updateFrom: '', // the version that was running when an update was started here
    memProject: '', // the memory list narrowed to one project
    memSelected: null,
    memJump: null, // a memory opened through a fold link
    sent: null, // what was sent to models, newest first
    sentOpen: null, // one of them, with its texts
    sentTask: '',
    sentScope: '',
    notes: null, // notes of conversations that went quiet, for the window that goes on
    placing: {}, // "device|folder" -> the project name being typed for it
    scopeDraft: null, // the import range being chosen, before it is used
    scopePreview: null, // how much that range holds
    memDetail: null,
    memView: '', // '' = memories, 'words' = the original words themselves
    words: { query: '', who: '', agent: '', since: '', until: '' }, // what is searched for in them
    wordsResult: null,
    wordsBusy: false,
    wordsError: '',
    wordsOpen: null, // the conversation around one turn
    distillNote: '',
  };

  // ---- small helpers ------------------------------------------------------

  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else if (key === 'width') node.style.width = value;
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  const ICONS = {
    overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    devices: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8"/><path d="M12 16v4"/>',
    models: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    import: '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    memory: '<path d="M4 19V5a2 2 0 0 1 2-2h14v14H6a2 2 0 0 0-2 2z"/><path d="M6 21h14"/><path d="M8 7h8M8 11h5"/>',
    projects: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 10h18"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="M3 3l18 18"/><path d="M10.6 5.1A10.9 10.9 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.2M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7a10.6 10.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
  };

  function icon(name, size) {
    const span = document.createElement('span');
    const s = size || 18;
    // Constant markup only: never built from data.
    span.innerHTML = `<svg aria-hidden="true" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
    return span.firstChild;
  }

  async function api(method, path, body) {
    let response;
    try {
      response = await fetch(path, {
        method,
        credentials: 'same-origin',
        headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error) {
      throw { status: 0, code: 'unreachable' };
    }
    let payload = {};
    try { payload = await response.json(); } catch (error) { /* not JSON */ }
    if (!response.ok) throw { status: response.status, code: payload.error || 'error', detail: payload.message || '' };
    return payload;
  }

  const MESSAGES = {
    unreachable: t('连不上服务端,稍后会自动重试。'),
    wrong_password: t('密码不对。'),
    too_many_attempts: t('试错次数太多,请过几分钟再试。'),
    password_too_short: t('密码至少 8 位。'),
    wrong_server_key: t('服务端钥匙不对:请把 admin_token.txt 里那一整行原样复制过来。'),
    already_set_up: t('管理密码已经设置过了,请直接登录。'),
    cross_site_request: t('这个请求来自别的网站,已拒绝。'),
    device_not_found: t('这台电脑已经不在列表里了。'),
    agent_not_found: t('这个 agent 已经不在列表里了。'),
    source_not_found: t('这个模型来源已经不在了。'),
    model_required: t('先选一个模型。'),
    invalid_field: t('有一项填得不对,请检查地址、协议和名称。'),
    model_auth: t('key 不对或已经失效。'),
    model_quota: t('余额不足。'),
    model_unreachable: t('连不上这个地址。'),
    model_not_found: t('地址、协议或模型名不对(接口返回 404)。'),
    model_bad_response: t('接口有回应,但不是所选协议的格式,换个协议试试。'),
    model_http: t('接口拒绝了这次请求。'),
    local_model_unavailable: t('这个安装包没有带本机模型程序。'),
    builtin_source: t('本机模型在它自己的卡片里管理。'),
    already_running: t('已经在进行中了。'),
    no_model: t('还没给「日常提炼」选模型,先到「模型」页选一个。'),
    no_import_model: t('还没给「历史导入」选模型,先到「模型」页选一个。'),
    local_model_busy: t('本机模型正在做另一项任务,它一次只能做一件;做完后再开始,或给这项任务换成在线模型。'),
    not_running: t('现在没有在进行的整理。'),
    memory_not_found: t('这条记忆已经不在了。'),
    update_not_supported: t('这台服务端不是由容器启动的,不能在这里更新。Docker 部署拉一次新镜像后就可以了。'),
    update_busy: t('正在更新,等这次结束。'),
    nothing_to_update: t('没有比现在更新的版本,先点「检查更新」。'),
    update_needs_image: t('这一版换了运行环境,要拉一次新镜像。'),
    update_not_possible: t('这一版现在不能在这里更新。'),
    update_failed_before: t('这一版试过、没能正常运行,已经退回。等下一版。'),
    nothing_to_go_back: t('没有可以退回的上一版。'),
  };
  const say = (error) => MESSAGES[error && error.code] || t('出了点问题,请再试一次。');

  function relTime(at) {
    if (!at) return '—';
    const seconds = Math.max(0, state.now - at);
    if (seconds < 60) return t('刚刚');
    if (seconds < 3600) return t('{0} 分钟前', Math.floor(seconds / 60));
    if (seconds < 86400) return t('{0} 小时前', Math.floor(seconds / 3600));
    if (seconds < 86400 * 30) return t('{0} 天前', Math.floor(seconds / 86400));
    return new Date(at * 1000).toLocaleDateString(LOCALE);
  }

  const num = (value) => Number(value || 0).toLocaleString(LOCALE);

  function bytes(value) {
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = Number(value || 0);
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
    return `${size >= 100 || unit === 0 ? Math.round(size) : size.toFixed(1)} ${units[unit]}`;
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (error) { /* fall through */ }
    // Plain http on a home network is not a "secure context": use the old way.
    const area = h('textarea', { class: 'clip', readonly: true });
    area.value = text;
    document.body.append(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (error) { ok = false; }
    area.remove();
    return ok;
  }

  function startOfToday() {
    const day = new Date();
    day.setHours(0, 0, 0, 0);
    return day.getTime() / 1000;
  }

  // ---- data ---------------------------------------------------------------

  async function loadSession() {
    try {
      const session = await api('GET', '/api/v1/admin/session');
      state.gate = session.signed_in ? null : (session.setup_needed ? 'setup' : 'login');
    } catch (error) {
      state.gate = 'login';
      state.gateError = say(error);
    }
  }

  let lastPainted = '';
  let busyTimer = null;

  function paintKey() {
    const overview = state.overview ? Object.assign({}, state.overview, { now: 0 }) : null;
    // Relative times ("3 分钟前") only change by the minute, and only two pages show them.
    const minute = state.route === 'overview' || state.route === 'devices' ? Math.floor(state.now / 60) : 0;
    const memories = state.memories ? Object.assign({}, state.memories, { now: 0 }) : null;
    return JSON.stringify([state.route, state.devices, overview, state.models, state.localModel, state.distill, memories, state.memDetail, minute, state.loadError,
      state.scopeDraft, state.scopePreview, state.evolution, state.vectors, state.projects, state.memProject, state.doctor,
      state.update, state.updateLooking, state.notes, state.sent, state.sentOpen, state.memView, state.wordsResult, state.wordsOpen, state.wordsBusy]);
  }

  // `quiet` is the background poll: it repaints only when something changed, and
  // never while the viewer has text selected, so focus and selection survive.
  async function refresh(quiet) {
    if (state.gate) return;
    try {
      if (state.route === 'devices') {
        const reply = await api('GET', '/api/v1/admin/devices');
        state.devices = reply.devices;
        state.now = reply.now;
      } else if (state.route === 'overview') {
        const [reply, distill, doctor] = await Promise.all([
          api('GET', `/api/v1/admin/overview?since=${startOfToday()}`), api('GET', '/api/v1/admin/distill'), api('GET', '/api/v1/admin/doctor')]);
        state.overview = reply;
        state.now = reply.now;
        state.distill = distill;
        state.doctor = doctor;
        await loadUpdate();
        if (state.doctor.checkup_running || state.doctor.compare_running) {
          clearTimeout(busyTimer);
          busyTimer = setTimeout(() => { if (state.route === 'overview') refresh(true); }, 3000);
        }
      } else if (state.route === 'models') {
        const query = new URLSearchParams({ since: String(startOfToday()) });
        if (state.sentTask) query.set('task', state.sentTask);
        if (state.sentScope) query.set('scope', state.sentScope);
        [state.models, state.localModel, state.vectors, state.sent] = await Promise.all([
          api('GET', '/api/v1/admin/models'), api('GET', '/api/v1/admin/local-model'), api('GET', '/api/v1/admin/vectors'), api('GET', `/api/v1/admin/sent?${query}`)]);
        if (['downloading', 'verifying', 'starting'].includes(state.localModel.phase) || ['downloading', 'verifying', 'loading', 'indexing'].includes(state.vectors.phase)) {
          // Something is in progress: look again soon instead of waiting for the slow poll.
          clearTimeout(busyTimer);
          busyTimer = setTimeout(() => { if (state.route === 'models') refresh(true); }, 2500);
        }
      } else if (state.route === 'import') {
        state.distill = await api('GET', '/api/v1/admin/distill');
        state.now = Date.now() / 1000;
        if (state.distill.lives && state.distill.lives.import && state.distill.lives.import.pausing) {
          clearTimeout(busyTimer);
          busyTimer = setTimeout(() => { if (state.route === 'import') refresh(true); }, 2500);
        }
      } else if (state.route === 'projects') {
        [state.projects, state.notes] = await Promise.all([api('GET', '/api/v1/admin/projects'), api('GET', '/api/v1/admin/notes')]);
        state.now = Date.now() / 1000;
      } else if (state.route === 'memory') {
        const params = new URLSearchParams();
        if (state.memProject) params.set('project', state.memProject);
        if (state.memQuery.trim()) params.set('query', state.memQuery.trim());
        if (state.memFilter) params.set('status', state.memFilter);
        if (state.memShelf) params.set('shelf', state.memShelf);
        const [reply, distill, evolution] = await Promise.all([
          api('GET', `/api/v1/admin/memories?${params}`), api('GET', '/api/v1/admin/distill'), api('GET', '/api/v1/admin/evolution')]);
        state.memories = reply;
        state.now = reply.now;
        state.distill = distill;
        state.evolution = evolution;
        const ids = reply.memories.map((item) => item.id);
        // A memory reached through a fold link stays open even when the list does not show it.
        const jumped = state.memJump !== null && state.memSelected === state.memJump;
        if (!ids.includes(state.memSelected) && !jumped) state.memSelected = ids.length ? ids[0] : null;
        if (state.memSelected === null) {
          state.memDetail = null;
        } else {
          try {
            state.memDetail = await api('GET', `/api/v1/admin/memories/${state.memSelected}`);
          } catch (error) {
            state.memDetail = null;
          }
        }
      }
      state.loadError = '';
    } catch (error) {
      if (error.status === 401) {
        await loadSession();
      } else if (state.updateFrom && error.status === 0) {
        state.loadError = ''; // the server is restarting into the new version: the update card says so
      } else {
        state.loadError = say(error);
      }
    }
    if (quiet && !state.gate) {
      if (paintKey() === lastPainted) return;
      if (String(window.getSelection() || '')) return;
      // Never rebuild the page under someone who is typing or choosing.
      const active = document.activeElement;
      if (active && ['INPUT', 'SELECT', 'TEXTAREA'].includes(active.tagName)) return;
    }
    render();
  }

  // ---- the official logo, in the page's language --------------------------

  function brandLogo(where) {
    const english = (document.documentElement.lang || 'zh').toLowerCase().startsWith('en');
    return h('div', { class: `brand ${where}` },
      h('img', {
        class: 'brand-logo', src: english ? '/assets/logo-en.png' : '/assets/logo-zh.png',
        alt: english ? 'Time Library' : t('忆凡尘 时间图书馆'), width: '480', height: english ? '376' : '367',
      }),
      h('div', { class: 'brand-sub' }, english ? 'server' : t('服务端')));
  }

  // ---- gate: first visit and sign in ---------------------------------------

  function viewReset() {
    const key = h('input', { id: 'reset-key', type: 'password', autocomplete: 'off', required: true, spellcheck: 'false' });
    const password = h('input', { id: 'reset-password', type: 'password', autocomplete: 'new-password', required: true });
    const again = h('input', { id: 'reset-again', type: 'password', autocomplete: 'new-password', required: true });

    async function submit(event) {
      event.preventDefault();
      if (state.gateBusy) return;
      if (password.value !== again.value) {
        state.gateError = t('两次输入的新密码不一样。');
        render();
        return;
      }
      state.gateBusy = true;
      state.gateError = '';
      try {
        await api('POST', '/api/v1/admin/session/reset', { token: key.value, password: password.value });
        state.gate = null;
        state.gateBusy = false;
        await refresh();
        return;
      } catch (error) {
        state.gateError = say(error);
      }
      state.gateBusy = false;
      render();
    }

    return h('div', { class: 'gate' },
      h('form', { class: 'card gate-card', onsubmit: submit },
        h('div', { class: 'stack' },
          h('h2', {}, t('忘记密码:用服务端钥匙重设')),
          h('p', { class: 'small muted' },
            t('服务端的数据文件夹里有个 admin_token.txt(装在 NAS 上时,就是 time-library 文件夹下的 data 文件夹)。'),
            t('用 NAS 的文件管理把它当文本打开,把里面那一整行复制到下面。能打开那个文件的人,才能重设密码。')),
          h('p', { class: 'small muted' }, t('设好后,所有已登录的浏览器都要用新密码重新登录。'))),
        h('div', { class: 'field' }, h('label', { for: 'reset-key' }, t('服务端钥匙')), key),
        h('div', { class: 'field' }, h('label', { for: 'reset-password' }, t('新密码(至少 8 位)')), password),
        h('div', { class: 'field' }, h('label', { for: 'reset-again' }, t('再输一次')), again),
        state.gateError ? h('div', { class: 'error', role: 'alert' }, state.gateError) : null,
        h('button', { class: 'btn primary', type: 'submit', disabled: state.gateBusy }, t('设新密码并进入')),
        h('button', { class: 'link small', type: 'button', onclick: () => { state.gate = 'login'; state.gateError = ''; render(); } }, t('想起来了,返回登录'))));
  }

  function viewGate() {
    if (state.gate === 'reset') return viewReset();
    const setup = state.gate === 'setup';
    const password = h('input', { id: 'gate-password', type: 'password', autocomplete: setup ? 'new-password' : 'current-password', required: true });
    const again = setup ? h('input', { id: 'gate-again', type: 'password', autocomplete: 'new-password', required: true }) : null;

    async function submit(event) {
      event.preventDefault();
      if (state.gateBusy) return;
      if (setup && password.value !== again.value) {
        state.gateError = t('两次输入的密码不一样。');
        render();
        return;
      }
      state.gateBusy = true;
      state.gateError = '';
      try {
        await api('POST', setup ? '/api/v1/admin/session/setup' : '/api/v1/admin/session/login', { password: password.value });
        state.gate = null;
        state.gateBusy = false;
        await refresh();
        return;
      } catch (error) {
        state.gateError = say(error);
        if (error.code === 'already_set_up') state.gate = 'login';
      }
      state.gateBusy = false;
      render();
    }

    return h('div', { class: 'gate' },
      h('form', { class: 'card gate-card', onsubmit: submit },
        brandLogo('brand-gate'),
        h('div', { class: 'gate-lang' }, languageButton()),
        h('div', { class: 'stack' },
          h('h2', {}, setup ? t('第一次打开:设置管理密码') : t('输入管理密码')),
          h('p', { class: 'small muted' }, setup
            ? t('这个密码只用来打开这个后台。至少 8 位。')
            : t('登录后 30 天内这个浏览器不用再输。'))),
        h('div', { class: 'field' }, h('label', { for: 'gate-password' }, setup ? t('新密码') : t('密码')), password),
        setup ? h('div', { class: 'field' }, h('label', { for: 'gate-again' }, t('再输一次')), again) : null,
        state.gateError ? h('div', { class: 'error', role: 'alert' }, state.gateError) : null,
        h('button', { class: 'btn primary', type: 'submit', disabled: state.gateBusy }, setup ? t('设置并进入') : t('登录')),
        setup ? null : h('button', { class: 'link small', type: 'button', onclick: () => { state.gate = 'reset'; state.gateError = ''; render(); } }, t('忘记密码?'))));
  }

  // ---- shell --------------------------------------------------------------

  const PAGES = [
    ['overview', t('总览')],
    ['devices', t('设备')],
    ['models', t('模型')],
    ['import', t('导入')],
    ['projects', t('项目')],
    ['memory', t('记忆')],
  ];

  function viewShell(content) {
    async function signOut() {
      try { await api('POST', '/api/v1/admin/session/logout', {}); } catch (error) { /* already out */ }
      state.gate = 'login';
      state.devices = null;
      state.overview = null;
      render();
    }
    return h('div', { class: 'shell' },
      h('nav', { class: 'nav', 'aria-label': t('主导航') },
        brandLogo('brand-nav'),
        h('div', { class: 'nav-links' }, PAGES.map(([id, label]) =>
          h('a', { class: 'nav-link', href: `#/${id}`, 'aria-current': state.route === id ? 'page' : null }, icon(id, 20), h('span', {}, label)))),
        h('div', { class: 'nav-foot' },
          h('div', { class: 'nav-status' },
            h('div', { class: 'nav-status-line' }, h('span', { class: 'dot big ok', 'aria-hidden': 'true' }), t('服务运行中')),
            h('span', { class: 'nav-status-sub' }, location.host),
            state.update ? h('span', { class: 'nav-status-sub' }, state.update.available && !state.update.bad.includes(state.update.latest.version)
              ? h('a', { class: 'nav-update', href: '#/overview' }, t('{0} → 有新版 {1}', state.update.version, state.update.latest.version))
              : t('版本 {0}', state.update.version)) : null),
          languageButton(),
          h('button', { class: 'btn quiet', type: 'button', onclick: () => { state.pwDialog = { old: '', next: '', again: '' }; render(); } }, t('改密码')),
          h('button', { class: 'btn quiet', type: 'button', onclick: signOut }, t('退出登录')))),
      h('main', { class: 'main' }, h('div', { class: 'column' },
        state.loadError ? h('div', { class: 'error', role: 'alert' }, state.loadError) : null,
        content)));
  }

  function pageHead(title, text) {
    return h('header', { class: 'page-head' }, h('h1', {}, title), h('p', {}, text));
  }

  // ---- the server's own version, and updating it ---------------------------

  let updateTimer = null;

  function watchUpdate(ms) {
    clearTimeout(updateTimer);
    updateTimer = setTimeout(async () => {
      try { await loadUpdate(); } catch (error) { watchUpdate(2500); } // restarting: look again
      render();
    }, ms);
  }

  async function loadUpdate() {
    const update = await api('GET', '/api/v1/admin/update');
    const before = state.update && state.update.version;
    state.update = update;
    if (before && before !== update.version) {
      // Another version answers now: the page itself is the old one's, so take the new one's.
      location.reload();
      return;
    }
    if (update.busy || update.on_trial) watchUpdate(1500);
    else if (state.updateFrom) {
      state.updateFrom = '';
      state.loadError = '';
    }
    const stale = !update.checked_at || Date.now() / 1000 - update.checked_at > 6 * 3600;
    if (update.supported && stale && !state.updateLooking) lookForUpdate(false);
  }

  async function lookForUpdate(byHand) {
    if (state.updateLooking) return;
    state.updateLooking = true;
    if (byHand) render();
    try {
      state.update = byHand
        ? await api('POST', '/api/v1/admin/update/check', {})
        : await api('GET', '/api/v1/admin/update?look=1');
      state.loadError = '';
    } catch (error) {
      if (byHand) state.loadError = say(error);
    }
    state.updateLooking = false;
    render();
  }

  async function startUpdate() {
    state.updateFrom = state.update.version;
    try {
      state.update = await api('POST', '/api/v1/admin/update/start', {});
    } catch (error) {
      state.updateFrom = '';
      throw error;
    }
    watchUpdate(1000);
  }

  async function goBack() {
    state.updateFrom = state.update.version;
    state.update = await api('POST', '/api/v1/admin/update/back', {});
    watchUpdate(2500);
  }

  // Release notes come in two languages, the Chinese part after a "## 中文" heading.
  function notesIn(notes) {
    const [english, chinese] = String(notes || '').split(/\n## 中文\s*\n/);
    // Plain text: the notes' own HTML (a logo) and title line are left out.
    return (LANG === 'en' || !chinese ? english : chinese).replace(/<[^>]*>/g, '').replace(/^\s*# .*\n/, '').replace(/\n{3,}/g, '\n\n').trim();
  }

  const STEPS = { look: t('在看新版本…'), download: t('在下载…'), check: t('在核对…'), switch: t('在装上…'), restart: t('在重启,一会儿就好…') };

  function viewUpdate() {
    const u = state.update;
    if (!u) return null;
    const latest = u.latest;
    const back = u.previous || u.image_version;
    const tried = Boolean(latest && u.bad.includes(latest.version)); // went back from it already: not offered again
    const lines = [];
    const restarting = state.updateFrom && (u.on_trial || (u.progress && u.progress.step === 'restart'));
    if (u.busy || restarting || u.on_trial) {
      const p = u.progress || {};
      const share = p.step === 'download' && p.total ? Math.round((p.done / p.total) * 100) : null;
      const text = u.on_trial && !u.busy ? t('新版本在试运行,正常才算更新成功…')
        : share !== null ? t('在下载… {0}%', share) : (STEPS[p.step] || t('在更新…'));
      lines.push(h('p', { role: 'status' }, text));
      lines.push(h('div', { class: 'bar', role: 'progressbar', 'aria-label': t('更新进度'), 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(share === null ? 100 : share) },
        h('span', { width: `${share === null ? 100 : share}%` })));
    } else {
      if (u.failure) {
        lines.push(h('p', { class: 'small' }, h('span', { class: 'badge danger' }, t('没更新成')),
          t(' 更新到 {0}:{1}', u.failure.version, u.failure.reason === 'needs_image' ? t('这一版要用新镜像') : tx(u.failure.reason))));
      } else if (u.last && Date.now() / 1000 - u.last.at < 7 * 86400) {
        lines.push(h('p', { class: 'small' }, u.last.by === 'owner'
          ? t('{0} 你从 {1} 退回了现在这一版。', relTime(u.last.at), u.last.version)
          : u.last.ok
          ? t('{0} 更新到了 {1}。', relTime(u.last.at), u.last.version)
          : h('span', {}, h('span', { class: 'badge warn' }, t('已退回')), t(' {0} 更新到 {1} 没成:{2}。', relTime(u.last.at), u.last.version, tx(u.last.note)))));
      }
      if (u.error) lines.push(h('p', { class: 'small' }, h('span', { class: 'badge warn' }, t('检查更新失败')), ` ${tx(u.error)}`));
      if (u.available) {
        const problem = latest.problem;
        lines.push(h('p', {}, h('strong', {}, t('有新版 {0}', latest.version)), tried ? h('span', { class: 'small muted' }, ` ${t('试过、没能正常运行,等下一版。')}`) : null));
        if (problem === 'needs_image') lines.push(h('p', { class: 'small' }, t('这一版换了运行环境,要拉一次新镜像:在 NAS 上服务端的文件夹里运行 '), h('code', {}, 'docker compose pull && docker compose up -d'), t('。数据不受影响,以后的版本又能在这里点更新。')));
        else if (problem) lines.push(h('p', { class: 'small' }, tx(problem)));
        lines.push(h('details', { 'data-key': 'update-notes' }, h('summary', {}, t('这一版改了什么')), h('div', { class: 'notes' }, notesIn(latest.notes) || t('没有说明。'))));
      } else if (u.checked_at && !u.error) {
        lines.push(h('p', { class: 'small muted' }, t('已是最新版({0}检查过)。', relTime(u.checked_at))));
      }
    }
    const idle = !u.busy && !u.on_trial && !restarting;
    return h('section', { class: 'card', 'aria-label': t('版本与更新') },
      h('div', { class: 'card-head' },
        h('h2', {}, t('版本 {0}', u.version)),
        u.supported ? h('div', { class: 'row' },
          u.can_go_back && idle ? h('button', {
            class: 'btn quiet', type: 'button', 'data-key': 'update-back',
            onclick: () => ask(t('退回 {0}?', back), t('服务端会换回上一版并重启,大约一分钟。数据不动。'), t('退回'), goBack),
          }, t('退回 {0}', back)) : null,
          idle ? h('button', { class: 'btn', type: 'button', 'data-key': 'update-check', disabled: state.updateLooking, onclick: () => lookForUpdate(true) }, state.updateLooking ? t('在检查…') : t('检查更新')) : null,
          idle && u.available && !latest.problem && !tried ? h('button', {
            class: 'btn primary', type: 'button', 'data-key': 'update-start',
            onclick: () => ask(t('更新到 {0}?', latest.version),
              t('不用拉镜像:只下载服务端的程序(不到 1 MB),核对无误后重启,大约一分钟。新版起不来会自动退回 {0}。数据不动。', u.version), t('更新'), startUpdate, 'primary'),
          }, t('更新到 {0}', latest.version)) : null) : null),
      u.supported ? lines : h('p', { class: 'small muted' }, t('这台服务端不是由容器启动的,不能在这里更新。Docker 部署拉一次新镜像后就可以了。')));
  }

  // ---- overview -----------------------------------------------------------

  function viewOverview() {
    const data = state.overview;
    if (!data) return [pageHead(t('总览'), t('服务端现在的状态。')), h('div', { class: 'card' }, h('p', { class: 'muted' }, t('正在读取…')))];
    const storage = data.storage;
    const usedShare = storage.total_bytes ? Math.round((1 - storage.free_bytes / storage.total_bytes) * 100) : 0;
    const today = new Date().toLocaleDateString(LOCALE, { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });

    const stat = (label, value, note) => h('section', { class: 'card' },
      h('h2', { class: 'stat-label' }, label), h('span', { class: 'stat-value' }, value), h('span', { class: 'small muted' }, note));

    return [
      pageHead(t('总览'), today),
      viewUpdate(),
      h('div', { class: 'grid' },
        h('section', { class: 'card' },
          h('h2', { class: 'stat-label' }, t('服务')),
          h('span', { class: 'row' }, h('span', { class: 'dot big ok', 'aria-hidden': 'true' }), h('span', { class: 'stat-value' }, t('运行中'))),
          h('span', { class: 'small muted' }, t('累计已存 {0} 段对话', num(data.segments_total)))),
        stat(t('今日采集'), t('{0} 字', num(data.chars_today)), t('{0} 段对话', num(data.segments_today))),
        stat(t('提炼'), distillSummary().title, distillSummary().note),
        stat(t('设备'), t('{0} / {1} 台在线', num(data.devices_online), num(data.devices_total)), t('共 {0} 个 agent', num(data.agents_total)))),
      h('div', { class: 'grid wide' },
        h('section', { class: 'card' },
          h('h2', {}, t('最近动态')),
          data.recent.length
            ? h('ul', { class: 'list' }, data.recent.map((item) => h('li', {},
              h('span', { class: 'when' }, relTime(item.at)),
              h('span', { class: 'grow' }, t('{0} · {1} 上报了新对话', item.device, item.agent)),
              h('span', { class: 'muted' }, t('今天 {0} 段', num(item.today))))))
            : h('p', { class: 'muted' }, t('还没有任何 agent 上报过对话。到「设备」页接入第一个。'))),
        h('section', { class: 'card' },
          h('h2', {}, t('存储')),
          h('div', { class: 'row between' },
            h('span', { class: 'stat-value' }, t('剩余 {0}', bytes(storage.free_bytes))),
            h('span', { class: 'muted' }, t('共 {0}', bytes(storage.total_bytes)))),
          h('div', { class: 'bar', role: 'progressbar', 'aria-label': t('存储已用'), 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(usedShare) },
            h('span', { width: `${usedShare}%` })),
          h('span', { class: 'small muted' }, t('这块硬盘已用 {0}%(含其他文件)。忆凡尘只保存去掉运行过程后的对话,不保存原始会话文件。', usedShare)))),
      h('div', { class: 'grid wide' }, viewCheckup(), viewCompare()),
    ];
  }

  // ---- proof: the nightly checkup, and memory switched on and off --------------

  const MARK = { ok: '✅', warn: '⚠️', bad: '🔴' };

  async function doctorAction(path, body) {
    try { await api('POST', `/api/v1/admin/doctor/${path}`, body || {}); } catch (error) { state.loadError = say(error); }
    await refresh();
  }

  function viewCheckup() {
    const d = state.doctor;
    if (!d) return null;
    const report = d.checkup;
    return h('section', { class: 'card', 'aria-label': t('体检') },
      h('div', { class: 'card-head' },
        h('div', { class: 'stack' },
          h('h2', {}, t('体检')),
          h('span', { class: 'small muted' }, report ? t('{0} · 每晚自动查一次,不花模型钱', relTime(report.at)) : t('每晚自动查一次:原话还在不在、有没有卡住的、召回找得准不准。'))),
        h('button', { class: 'btn', type: 'button', 'data-key': 'doctor-run', disabled: d.checkup_running, onclick: () => doctorAction('run') },
          d.checkup_running ? t('正在体检…') : t('现在体检'))),
      report ? h('ul', { class: 'list checks' }, report.checks.map((check) => h('li', {},
        h('span', { 'aria-hidden': 'true' }, MARK[check.status] || ''),
        h('span', { class: 'grow stack' },
          h('span', { class: 'small' }, tx(check.label)),
          check.detail ? h('span', { class: 'tiny muted' }, tx(check.detail)) : null,
          check.examples.length ? h('span', { class: 'tiny muted' }, t('例如 '),
            check.examples.map((id) => h('button', { class: 'link tiny', type: 'button', onclick: () => openMemory(id) }, `#${id} `))) : null))))
        : h('p', { class: 'empty' }, t('还没体检过。')));
  }

  function viewCompare() {
    const d = state.doctor;
    if (!d) return null;
    const c = d.compare;
    const live = d.compare_live;
    const pct = (n, total) => (total ? Math.round((100 * n) / total) : 0);
    let body;
    if (d.compare_running) {
      body = h('span', { class: 'small muted', role: 'status' }, live ? t('正在作答与判分 · {0} / {1} 题', num(live.done), num(live.total)) : t('正在准备题目…'));
    } else if (c && c.questions) {
      body = h('div', { class: 'stack gap' },
        h('div', { class: 'compare' },
          h('div', { class: 'stack' }, h('span', { class: 'stat-label' }, t('不开记忆')), h('span', { class: 'stat-value' }, `${pct(c.off_right, c.questions)}%`), h('span', { class: 'tiny muted' }, t('答对 {0} / {1}', c.off_right, c.questions))),
          h('div', { class: 'stack' }, h('span', { class: 'stat-label' }, t('开记忆')), h('span', { class: 'stat-value' }, `${pct(c.on_right, c.questions)}%`), h('span', { class: 'tiny muted' }, t('答对 {0} / {1}', c.on_right, c.questions)))),
        h('span', { class: 'small muted' }, t('{0} · 召回在前 5 条里找到依据 {1}% · 用了约 {2} token', relTime(c.started_at), pct(c.found, c.questions), tokensText(c.input_tokens + c.output_tokens))),
        h('details', { 'data-key': 'compare-details' },
          h('summary', { class: 'small link' }, t('看每一题')),
          h('ol', { class: 'thread' }, c.details.map((row) => h('li', {},
            h('span', { class: 'small' }, row.question),
            h('span', { class: 'tiny muted' }, t('不开记忆 {0}:{1}', MARK[row.off_verdict === 'right' ? 'ok' : 'bad'] || '', row.off || '—')),
            h('span', { class: 'tiny muted' }, t('开记忆 {0}:{1}', MARK[row.on_verdict === 'right' ? 'ok' : 'bad'] || '', row.on || '—')))))));
    } else {
      body = h('span', { class: 'small muted' }, c && c.status === 'stopped' ? t('上次没跑完:{0}', c.error) : t('还没跑过。'));
    }
    return h('section', { class: 'card', 'aria-label': t('记忆开关对比') },
      h('div', { class: 'card-head' },
        h('div', { class: 'stack' },
          h('h2', {}, t('记忆开关对比')),
          h('span', { class: 'small muted' }, t('同一批问题让模型答两遍:一遍不给记忆,一遍给召回找到的记忆,再判对错。题目从你的记忆里出,量的是「答案在馆里时,开记忆能多答对多少」。'))),
        h('button', { class: 'btn', type: 'button', 'data-key': 'doctor-compare', disabled: d.compare_running || !d.has_model,
          onclick: () => ask(t('跑一次记忆开关对比?'), t('40 道题,用「日常提炼」的模型作答、「深度归纳」的模型判分,大约花 10 万 token,几分钟跑完。'), t('开始'), () => api('POST', '/api/v1/admin/doctor/compare', { questions: 40 }), 'primary') },
          d.compare_running ? t('正在对比…') : t('跑一次对比'))),
      body);
  }

  // ---- devices ------------------------------------------------------------

  const CAPABILITY_LABELS = { mcp: 'MCP', skill: 'skill', custom_instructions: t('自定义指令'), preflight: t('提问前预检') };
  const SELF_REPORT = t('照 install.md 第 4 步描述你自己:先看你自己的会话记录长什么样、存在哪,写成描述,用 tl.py check 在你自己的文件上试到它说看着对了,再用 report-agent 报上来;MCP、skill、提问前预检照第 6 步接,钩子的规矩和默认不一样就用 --hook-json 说清楚。不写任何脚本,不按产品名去猜;有描述不了的,如实告诉我缺什么。');
  const firstSentence = (token) => t('请把你接入忆凡尘服务端 {0},接入令牌 {1}。先检查本机有没有装忆凡尘客户端:装了就别重装;没装就打开 {2}/client/install.md,照里面的步骤装上。然后{3}', location.origin, token, location.origin, SELF_REPORT);
  const moreSentence = () => t('这台电脑已经装好忆凡尘客户端,别重装。请打开 {0}/client/install.md,{1}', location.origin, SELF_REPORT);

  async function generatePairing() {
    if (state.pairingBusy) return;
    state.pairingBusy = true;
    render();
    try {
      const reply = await api('POST', '/api/v1/admin/pairing-tokens', {});
      state.pairing = { token: reply.pairing_token, expires_at: reply.expires_at };
      state.showToken = false;
      state.copied = '';
      state.loadError = '';
    } catch (error) {
      state.loadError = say(error);
    }
    state.pairingBusy = false;
    render();
  }

  async function copyAs(key, text) {
    state.copied = (await copyText(text)) ? key : 'failed';
    render();
  }

  function ask(title, body, action, run, tone) {
    state.confirm = { title, body, action, run, tone };
    render();
  }

  // What an agent says it supports is its own word; whether its prompt hook really asks was seen here.
  function preflightChip(agent) {
    const seen = agent.preflight || {};
    const label = CAPABILITY_LABELS.preflight;
    if (seen.quiet) {
      return [
        h('span', { class: 'badge warn' }, t('{0} · 没触发', label)),
        h('span', { class: 'tiny muted' }, seen.last_at
          ? t('最近 {0} 句提问都没收到它的预检,上一次是{1}。让它照 install.md 第 6 步查自己的钩子。', seen.quiet, relTime(seen.last_at))
          : t('最近 {0} 句提问都没收到它的预检,一次都没有过。让它照 install.md 第 6 步查自己的钩子。', seen.quiet)),
      ];
    }
    if (!seen.last_at) return [h('span', { class: 'badge mute' }, t('{0} · 自报支持,还没收到过', label))];
    return [h('span', { class: 'badge ok' }, t('{0} · {1}', label, relTime(seen.last_at)))];
  }

  function capabilityChips(agent) {
    const capabilities = agent.capabilities;
    const order = Object.keys(CAPABILITY_LABELS);
    const rank = (key) => (order.includes(key) ? order.indexOf(key) : order.length);
    const keys = Object.keys(capabilities || {}).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
    if (!keys.length) return h('span', { class: 'badge mute' }, t('还没自报'));
    return h('div', { class: 'chips' }, keys.flatMap((key) => {
      const label = CAPABILITY_LABELS[key] || key;
      if (key === 'preflight' && capabilities[key]) return preflightChip(agent);
      return capabilities[key]
        ? h('span', { class: 'badge ok' }, label)
        : h('span', { class: 'badge mute' }, t('{0} · 不支持', label));
    }));
  }

  // Whether anything in the agent's own files never reached the server.
  function verifiedNote(v) {
    if (!v) return null;
    if (v.missing) return h('span', { class: 'tiny warn-text' }, t('和源文件核对:有 {0} 句没收到,数目不寻常,没有自动补。在那台电脑上运行 tl.py verify --repair。', num(v.missing)));
    const said = v.base
      ? t('新收的都和源文件核对过,{0} 句,没有漏收的 · {1}(之前收的 {2} 个文件没有重核)', num(v.segments), relTime(v.at), num(v.base))
      : t('和源文件核对过 {0}/{1} 个文件、{2} 句,没有漏收的 · {3}', num(v.looked), num(v.files), num(v.segments), relTime(v.at));
    return h('span', { class: 'tiny muted' }, said
      + (v.repaired_ever ? t(' · 补收过 {0} 句', num(v.repaired_ever)) : '') + (v.gone ? t(' · {0} 个源文件已被删,服务端存着', num(v.gone)) : ''));
  }

  function viewDevice(device) {
    const agents = device.agents;
    const rows = agents.map((agent) => {
      const lastAt = Math.max(agent.last_ingest_at || 0, agent.last_report_at || 0);
      return h('tr', {},
        h('td', { class: 'name' }, agent.name, agent.disconnected ? h('span', { class: 'badge mute' }, t('已断开')) : null, verifiedNote(agent.verified)),
        h('td', { class: 'muted' }, relTime(lastAt)),
        h('td', { class: 'num' }, t('{0} 段', num(agent.segments_total))),
        h('td', { class: 'num' }, agent.backlog ? t('{0} 段', num(agent.backlog)) : t('0 段')),
        h('td', {}, capabilityChips(agent)),
        h('td', {}, agent.disconnected ? h('span', { class: 'small muted' }, t('重新自报即可恢复')) : h('button', {
          class: 'btn quiet danger', type: 'button', 'data-key': `disconnect-${agent.agent_id}`,
          onclick: () => ask(t('断开 {0}?', agent.name),
            t('{0} 上的 {1} 会停止上传。已经存下的对话保留。它重新自报一次就能恢复。', device.name, agent.name), t('断开'),
            () => api('POST', `/api/v1/admin/agents/${agent.agent_id}/disconnect`, {})),
        }, t('断开'))));
    });

    return h('div', { class: 'device' },
      h('div', { class: 'device-head' },
        h('div', { class: 'row' },
          icon('devices', 18),
          h('span', { class: 'device-name' }, device.name),
          device.os ? h('span', { class: 'small muted' }, device.os) : null,
          device.online
            ? h('span', { class: 'badge ok' }, h('span', { class: 'dot ok', 'aria-hidden': 'true' }), t('客户端在线'))
            : h('span', { class: 'badge mute' }, h('span', { class: 'dot', 'aria-hidden': 'true' }), t('客户端离线 · {0}', relTime(device.last_seen_at)))),
        h('div', { class: 'row' },
          h('button', { class: 'btn', type: 'button', 'data-key': `more-${device.device_id}`, onclick: () => { state.more = state.more === device.device_id ? null : device.device_id; state.copied = ''; render(); } }, t('再接一个 agent')),
          h('button', {
            class: 'btn danger', type: 'button', 'data-key': `revoke-${device.device_id}`,
            onclick: () => ask(t('吊销 {0}?', device.name),
              t('这台电脑上所有 agent 会一起断开,它的令牌立即失效。已经存下的对话保留。要重新接入得再生成一句接入口令。'), t('吊销这台电脑'),
              () => api('POST', `/api/v1/admin/devices/${device.device_id}/revoke`, {})),
          }, t('吊销这台电脑')))),
      state.more === device.device_id ? h('div', { class: 'device-head' }, h('div', { class: 'panel tint grow' },
        h('div', { class: 'row between' },
          h('span', { class: 'small' }, h('strong', {}, t('给 {0} 再接一个 agent:把这句话发给它', device.name))),
          h('div', { class: 'row' },
            h('button', { class: 'btn ink', type: 'button', onclick: () => copyAs('more', moreSentence()) }, icon('copy', 16), state.copied === 'more' ? t('已复制') : t('复制')),
            h('button', { class: 'btn icon', type: 'button', 'aria-label': t('关闭'), onclick: () => { state.more = null; render(); } }, icon('close', 16)))),
        h('p', { class: 'sentence' }, moreSentence()),
        h('span', { class: 'tiny muted' }, t('这句话不带令牌:客户端已经有了,agent 只是接到本机客户端上。')))) : null,
      agents.length
        ? h('div', { class: 'scroll-x' }, h('table', { class: 'agents' },
          h('thead', {}, h('tr', {},
            h('th', { scope: 'col', class: 'c-name' }, t('Agent(自报)')), h('th', { scope: 'col', class: 'c-when' }, t('最后上报')),
            h('th', { scope: 'col', class: 'c-num' }, t('已存对话')), h('th', { scope: 'col', class: 'c-num' }, t('离线积压')),
            h('th', { scope: 'col' }, t('自报的接入方式')), h('th', { scope: 'col', class: 'c-act' }, t('操作')))),
          h('tbody', {}, rows)))
        : h('p', { class: 'empty' }, t('这台电脑已配对,但还没有 agent 自报接入。')));
  }

  function viewDevices() {
    const head = pageHead(t('设备'), t('接入一个 agent 只要一句话:发给它,它自己装客户端、自己报身份接进来。身份 = 哪台电脑 + 哪个 agent,两样都由它自己报。'));
    const pairing = state.pairing;
    const shownToken = pairing ? (state.showToken ? pairing.token : `${pairing.token.slice(0, 4)}••••••••••••`) : '';

    const add = h('section', { class: 'card', 'aria-labelledby': 'add-title' },
      h('div', { class: 'card-head' },
        h('div', { class: 'stack' },
          h('h2', { id: 'add-title' }, t('在新电脑上接入第一个 agent')),
          h('p', { class: 'small muted' }, t('电脑叫什么、自己是哪个 agent,都由它报,这里不用填。同一台电脑再接别的 agent,在下面点「再接一个 agent」。'))),
        h('button', { class: 'btn primary', type: 'button', disabled: state.pairingBusy, onclick: generatePairing }, icon('plus', 18), pairing ? t('重新生成一句') : t('生成接入口令'))),
      pairing ? h('div', { class: 'panel' },
        h('div', { class: 'row between' },
          h('span', { class: 'small' }, h('strong', {}, t('把这句话发给新电脑上要接入的 agent'))),
          h('div', { class: 'row' },
            h('button', { class: 'btn icon', type: 'button', 'aria-label': state.showToken ? t('隐藏令牌') : t('显示令牌'), onclick: () => { state.showToken = !state.showToken; render(); } }, icon(state.showToken ? 'eyeOff' : 'eye', 18)),
            h('button', { class: 'btn ink', type: 'button', onclick: () => copyAs('first', firstSentence(pairing.token)) }, icon('copy', 16), state.copied === 'first' ? t('已复制整句') : t('复制整句')))),
        h('p', { class: 'sentence' },
          t('请把你接入忆凡尘服务端 '), h('code', {}, location.origin), t(',接入令牌 '), h('code', {}, shownToken),
          t('。先检查本机有没有装忆凡尘客户端:装了就别重装;没装就打开 '), h('code', {}, `${location.origin}/client/install.md`), t(',照里面的步骤装上。然后{0}', SELF_REPORT)),
        state.copied === 'failed' ? h('div', { class: 'error', role: 'alert' }, t('浏览器没让复制,请点眼睛显示令牌后手动选中复制。')) : null,
        h('div', { class: 'hints' },
          h('span', {}, t('Mac、Windows、Linux 都是这同一句话')),
          h('span', {}, t('令牌 24 小时内有效,用一次就绑定到那台电脑')),
          h('span', {}, t('丢了不用找,重新生成一句'))),
        null) : null);

    if (!state.devices) return [head, add, h('div', { class: 'card' }, h('p', { class: 'muted' }, t('正在读取…')))];

    const active = state.devices.filter((device) => !device.revoked);
    const revoked = state.devices.filter((device) => device.revoked);
    const agentCount = active.reduce((sum, device) => sum + device.agents.filter((agent) => !agent.disconnected).length, 0);

    const list = h('section', { class: 'card flush', 'aria-labelledby': 'list-title' },
      h('div', { class: 'card-head pad' },
        h('h2', { id: 'list-title' }, t('已接入的 agent')),
        h('span', { class: 'small muted' }, t('{0} 台电脑 · {1} 个 agent', num(active.length), num(agentCount)))),
      active.length ? active.map(viewDevice) : h('p', { class: 'empty' }, t('还没有电脑接入。点上面的「生成接入口令」开始。')),
      h('div', { class: 'foot-note' },
        h('span', {}, t('每个 agent 是哪台电脑、哪个 agent,由它自己报;接入方式也以它自报为准,不按产品名写适配,不支持的如实空着。')),
        h('span', {}, t('电脑离线时,回来会从上次读到的位置接着传,不丢也不重复。'))));

    const gone = revoked.length ? h('section', { class: 'card' },
      h('h2', {}, t('已吊销')),
      h('ul', { class: 'list' }, revoked.map((device) => h('li', {},
        h('span', { class: 'grow' }, h('strong', {}, device.name), ' ', h('span', { class: 'badge mute' }, t('已吊销'))),
        h('span', { class: 'muted' }, t('{0} 吊销 · 这台电脑上所有 agent 一并断开', new Date(device.revoked_at * 1000).toLocaleDateString(LOCALE))))))) : null;

    return [head, add, list, gone];
  }

  // ---- models -------------------------------------------------------------

  const PROTOCOL_LABELS = { responses: 'Responses', messages: 'Messages', chat: t('chat 兜底') };
  const PROTOCOL_HINTS = {
    responses: t('OpenAI 原生协议,推荐'),
    messages: t('Anthropic 原生协议'),
    chat: t('只在来源不支持前两种时用,部分能力会打折'),
  };
  const REASON_SHORT = { auth: t('key 失效'), quota: t('余额不足'), unreachable: t('连不上'), not_found: t('地址或模型不对'), bad_response: t('协议不对'), http: t('被拒绝') };
  const SLOT_INFO = [
    ['import', t('历史导入'), t('把过去攒下的会话一次性提炼。量大,适合快而便宜的模型。')],
    ['daily', t('日常提炼'), t('每晚处理当天的新对话。量小。')],
    ['reflect', t('深度归纳'), t('把零散的记忆合并成长期经验。需要推理强的模型。')],
  ];
  const reasonText = (reason) => MESSAGES[`model_${reason}`] || t('没调通。');
  const seconds = (ms) => t('{0} 秒', (ms / 1000).toFixed(1));

  function openSourceForm(source) {
    state.sourceForm = source
      ? { id: source.id, name: source.name, base_url: source.base_url, protocol: source.protocol, api_key: '', hadKey: source.key_set }
      : { id: null, name: '', base_url: '', protocol: 'responses', api_key: '', hadKey: false };
    state.picker = null;
    render();
  }

  async function saveSourceForm(event) {
    event.preventDefault();
    const form = state.sourceForm;
    const body = { name: form.name, base_url: form.base_url, protocol: form.protocol };
    if (form.api_key || form.id === null) body.api_key = form.api_key;
    try {
      const saved = await api('POST', form.id === null ? '/api/v1/admin/models/sources' : `/api/v1/admin/models/sources/${form.id}`, body);
      state.sourceForm = null;
      delete state.shownKeys[saved.id];
      state.sourceNote[saved.id] = saved.tested_ok ? null : { ok: null, text: saved.model ? t('改动已保存,需要重新测通。') : t('已保存。下一步:点「拉取模型」选一个。') };
      state.loadError = '';
    } catch (error) {
      state.loadError = say(error);
    }
    await refresh();
  }

  async function withSource(id, label, work) {
    state.sourceBusy[id] = label;
    render();
    try {
      await work();
    } catch (error) {
      state.sourceNote[id] = { ok: false, text: say(error) };
    }
    delete state.sourceBusy[id];
    await refresh();
  }

  const pullModels = (source) => withSource(source.id, t('正在拉取模型…'), async () => {
    await api('POST', `/api/v1/admin/models/sources/${source.id}/models`, {});
    state.picker = source.id;
    state.sourceNote[source.id] = null;
  });

  const testSource = (source) => withSource(source.id, t('正在测通…'), async () => {
    const result = await api('POST', `/api/v1/admin/models/sources/${source.id}/test`, {});
    state.sourceNote[source.id] = result.ok
      ? { ok: true, text: t('已用 {0} 协议调通 {1} · {2}', PROTOCOL_LABELS[source.protocol], result.model, seconds(result.latency_ms)) }
      : { ok: false, text: t('没调通:{0}', reasonText(result.reason)) };
  });

  const chooseModel = (source, model) => withSource(source.id, t('正在测通…'), async () => {
    state.picker = null;
    await api('POST', `/api/v1/admin/models/sources/${source.id}`, { model });
    const result = await api('POST', `/api/v1/admin/models/sources/${source.id}/test`, {});
    state.sourceNote[source.id] = result.ok
      ? { ok: true, text: t('已选 {0},并用 {1} 协议调通 · {2}', model, PROTOCOL_LABELS[source.protocol], seconds(result.latency_ms)) }
      : { ok: false, text: t('已选 {0},但没调通:{1}', model, reasonText(result.reason)) };
  });

  async function toggleKey(source) {
    if (state.shownKeys[source.id] !== undefined) {
      delete state.shownKeys[source.id];
    } else {
      try {
        state.shownKeys[source.id] = (await api('GET', `/api/v1/admin/models/sources/${source.id}/key`)).api_key;
      } catch (error) {
        state.loadError = say(error);
      }
    }
    render();
  }

  function viewPicker(source) {
    const manual = h('input', { id: `pick-manual-${source.id}`, type: 'text', placeholder: t('或者手动填写模型名称'), autocomplete: 'off', spellcheck: 'false' });
    const empty = h('p', { class: 'small muted', hidden: true }, t('没有匹配的模型。可以在下面手动填写。'));
    const list = h('div', { class: 'picker-list', role: 'listbox', 'aria-label': t('可选模型'), 'data-scroll-key': `picker-${source.id}` }, source.models.map((name) =>
      h('button', {
        class: 'pick', type: 'button', role: 'option', 'aria-selected': name === source.model ? 'true' : 'false',
        'data-model': name.toLowerCase(), onclick: () => chooseModel(source, name),
      }, h('span', { class: 'grow' }, name), name === source.model ? h('span', { class: 'badge accent' }, t('当前')) : null)));
    const search = h('input', {
      id: `pick-search-${source.id}`, type: 'search', placeholder: t('搜索模型名称'), autocomplete: 'off', spellcheck: 'false',
      oninput: (event) => {
        // Filter in place: rebuilding the page on every keystroke would drop the caret.
        const query = event.target.value.trim().toLowerCase();
        let any = false;
        list.querySelectorAll('.pick').forEach((button) => {
          const hit = !query || button.dataset.model.includes(query);
          button.hidden = !hit;
          any = any || hit;
        });
        empty.hidden = any;
        manual.value = event.target.value.trim();
      },
    });
    return h('div', { class: 'panel' },
      h('div', { class: 'row between' },
        h('strong', { class: 'small' }, t('从这个来源拉取到 {0} 个模型', num(source.models.length))),
        h('button', { class: 'btn icon', type: 'button', 'aria-label': t('关闭模型列表'), onclick: () => { state.picker = null; render(); } }, icon('close', 16))),
      h('div', { class: 'field' }, h('label', { class: 'sr', for: search.id }, t('搜索模型')), search),
      list, empty,
      h('form', { class: 'row', onsubmit: (event) => { event.preventDefault(); if (manual.value.trim()) chooseModel(source, manual.value.trim()); } },
        h('div', { class: 'field grow' }, h('label', { class: 'sr', for: manual.id }, t('手动填写模型名称')), manual),
        h('button', { class: 'btn', type: 'submit' }, t('用这个名称'))),
      h('span', { class: 'tiny muted' }, t('选好后会立刻用所选协议真调一次,通了才算数。')));
  }

  function viewSource(source) {
    const busy = state.sourceBusy[source.id];
    const note = state.sourceNote[source.id];
    const shown = state.shownKeys[source.id];
    const badge = source.tested_ok
      ? h('span', { class: 'badge ok' }, t('已调通'))
      : source.last_error_reason
        ? h('span', { class: 'badge danger' }, t('没调通 · {0}', REASON_SHORT[source.last_error_reason] || t('出错')))
        : h('span', { class: 'badge warn' }, t('待测通'));
    const fact = (label, ...value) => h('div', { class: 'fact' }, h('dt', {}, label), h('dd', {}, ...value));

    return h('section', { class: 'card', 'aria-label': t('模型来源 {0}', source.name) },
      h('div', { class: 'card-head' },
        h('div', { class: 'row' }, h('h2', {}, source.name), badge),
        h('div', { class: 'row' },
          h('button', { class: 'btn quiet', type: 'button', 'data-key': `edit-${source.id}`, onclick: () => openSourceForm(source) }, t('编辑')),
          h('button', {
            class: 'btn quiet danger', type: 'button', 'data-key': `del-${source.id}`,
            onclick: () => ask(t('删除模型来源「{0}」?', source.name), t('它的 key 会一起删掉,正在用它的任务会空出来。'), t('删除'),
              () => api('POST', `/api/v1/admin/models/sources/${source.id}/delete`, {})),
          }, t('删除')))),
      h('dl', { class: 'facts' },
        fact(t('地址'), h('code', { class: 'inline' }, source.base_url)),
        fact(t('协议'), PROTOCOL_LABELS[source.protocol], h('span', { class: 'tiny muted' }, ` · ${PROTOCOL_HINTS[source.protocol]}`)),
        fact('Key', source.key_set
          ? [h('code', { class: 'inline' }, shown !== undefined ? shown : source.key_hint),
            h('button', { class: 'btn icon quiet', type: 'button', 'data-key': `eye-${source.id}`, 'aria-label': shown !== undefined ? t('隐藏 key') : t('显示 key'), onclick: () => toggleKey(source) }, icon(shown !== undefined ? 'eyeOff' : 'eye', 18))]
          : h('span', { class: 'muted' }, t('没有填(本地模型一般不需要)'))),
        fact(t('测通用的模型'), source.model ? h('strong', {}, source.model) : h('span', { class: 'muted' }, t('还没选')),
          h('span', { class: 'tiny muted' }, source.models.length
            ? t(' · 已拉取 {0} 个模型,下面「任务分工」里每项任务可以选其中任意一个', source.models.length)
            : t(' · 拉取模型后,下面「任务分工」里可以选这个来源的任意模型')))),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', 'data-key': `pull-${source.id}`, disabled: Boolean(busy), onclick: () => pullModels(source) }, t('拉取模型')),
        h('button', { class: 'btn', type: 'button', 'data-key': `test-${source.id}`, disabled: Boolean(busy) || !source.model, onclick: () => testSource(source) }, t('测通')),
        busy ? h('span', { class: 'small muted', role: 'status' }, busy) : null),
      note ? h('div', { class: note.ok === false ? 'error' : note.ok ? 'okay' : 'notice', role: 'status' }, note.text) : null,
      state.picker === source.id && source.models.length ? viewPicker(source) : null,
      state.picker === source.id && !source.models.length ? h('div', { class: 'notice' }, t('这个来源没有返回任何模型。可以点「编辑」检查地址和协议。')) : null);
  }

  function viewSourceForm() {
    const form = state.sourceForm;
    const field = (id, label, key, attrs, hint) => h('div', { class: 'field' },
      h('label', { for: id }, label),
      h('input', Object.assign({ id, value: form[key], autocomplete: 'off', spellcheck: 'false', oninput: (event) => { form[key] = event.target.value; } }, attrs)),
      hint ? h('span', { class: 'tiny muted' }, hint) : null);
    return h('form', { class: 'card', onsubmit: saveSourceForm, 'aria-label': form.id === null ? t('添加模型来源') : t('编辑模型来源') },
      h('h2', {}, form.id === null ? t('添加模型来源') : t('编辑模型来源')),
      h('div', { class: 'grid wide' },
        field('src-name', t('名称'), 'name', { type: 'text', required: true, maxlength: '64', placeholder: t('例如:GPT 中转、NAS 本地') }),
        field('src-url', t('地址'), 'base_url', { type: 'url', required: true, placeholder: 'https://…/v1' }, t('填到 /v1 这一层。本地模型和中转只差这个地址。'))),
      h('div', { class: 'grid wide' },
        h('div', { class: 'field' },
          h('span', { id: 'src-proto-label', class: 'label' }, t('协议')),
          h('div', { class: 'seg', role: 'group', 'aria-labelledby': 'src-proto-label' }, Object.keys(PROTOCOL_LABELS).map((id) =>
            h('button', { type: 'button', 'data-key': `proto-${id}`, 'aria-pressed': form.protocol === id ? 'true' : 'false', onclick: () => { form.protocol = id; render(); } }, PROTOCOL_LABELS[id]))),
          h('span', { class: 'tiny muted' }, PROTOCOL_HINTS[form.protocol])),
        field('src-key', 'Key', 'api_key', { type: 'password', autocomplete: 'new-password', placeholder: form.hadKey ? t('不改就留空') : t('本地模型可以不填') }, t('Key 只存在服务端,客户端拿不到。'))),
      h('div', { class: 'row' },
        h('button', { class: 'btn primary', type: 'submit' }, t('保存')),
        h('button', { class: 'btn', type: 'button', onclick: () => { state.sourceForm = null; render(); } }, t('取消'))));
  }

  async function localAction(path, body) {
    try {
      state.localModel = await api('POST', `/api/v1/admin/local-model/${path}`, body || {});
      state.loadError = '';
    } catch (error) {
      state.loadError = say(error);
    }
    await refresh();
  }

  function viewLocalModel() {
    const local = state.localModel;
    if (!local || !local.available) return null;
    const entry = local.catalog.find((item) => item.id === local.model_id) || local.catalog[0];
    const head = (badge) => h('div', { class: 'row' }, h('h2', {}, t('本机模型')), h('span', { class: 'badge accent' }, t('自带')), badge);
    const about = h('p', { class: 'small muted' }, t('跑在这台 NAS 上:不花钱,对话不出门。比中转慢,适合每天的日常提炼。不用另外安装任何东西。'));
    const facts = h('span', { class: 'small' }, t('{0} · 下载 {1} · 运行时约占 {2} 内存', entry.label, bytes(entry.bytes), bytes(entry.ram_bytes)));
    const busy = ['downloading', 'verifying', 'starting'].includes(local.phase);

    if (local.phase === 'ready') {
      const source = state.models.sources.find((item) => item.builtin);
      return h('section', { class: 'card', 'aria-label': t('本机模型') },
        h('div', { class: 'card-head' },
          head(h('span', { class: source && !source.tested_ok ? 'badge warn' : 'badge ok' }, source && !source.tested_ok ? t('已启用 · 上次没调通') : t('已启用'))),
          h('div', { class: 'row' },
            source ? h('button', { class: 'btn', type: 'button', 'data-key': 'local-test', disabled: Boolean(state.sourceBusy[source.id]), onclick: () => testSource(source) }, t('测通')) : null,
            h('button', {
              class: 'btn quiet danger', type: 'button', 'data-key': 'local-remove',
              onclick: () => ask(t('停用本机模型?'), t('模型文件会从 NAS 上删掉,用它的任务会空出来。以后想用可以再下载。'), t('停用并删除'), () => api('POST', '/api/v1/admin/local-model/remove', {})),
            }, t('停用并删除模型')))),
        facts,
        h('p', { class: 'small muted' }, t('用的时候才把模型读进内存,闲置 {0} 分钟后自动释放。它已经出现在下面的「任务分工」里,名字叫「本机模型」。', Math.round(local.idle_seconds / 60))),
        source && state.sourceBusy[source.id] ? h('span', { class: 'small muted', role: 'status' }, t('{0}(第一次要先把模型读进内存,会慢一些)', state.sourceBusy[source.id])) : null,
        source && state.sourceNote[source.id] ? h('div', { class: state.sourceNote[source.id].ok === false ? 'error' : 'okay', role: 'status' }, state.sourceNote[source.id].text) : null);
    }

    if (busy) {
      const share = local.total_bytes ? Math.min(100, Math.round((local.downloaded_bytes / local.total_bytes) * 100)) : 0;
      const label = { downloading: t('正在下载 · {0}%', share), verifying: t('正在校验文件…'), starting: t('正在启动…') }[local.phase];
      return h('section', { class: 'card', 'aria-label': t('本机模型') },
        h('div', { class: 'card-head' },
          head(h('span', { class: 'badge accent' }, label)),
          local.phase === 'downloading' ? h('button', { class: 'btn', type: 'button', 'data-key': 'local-pause', onclick: () => localAction('cancel') }, t('暂停下载')) : null),
        facts,
        h('div', { class: 'bar', role: 'progressbar', 'aria-label': t('下载进度'), 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(share) }, h('span', { width: `${share}%` })),
        h('span', { class: 'small muted' }, local.phase === 'downloading'
          ? t('已下载 {0} / {1} · 每秒 {2}。暂停后已下载的部分会留着。', bytes(local.downloaded_bytes), bytes(local.total_bytes), bytes(local.bytes_per_second))
          : t('下载完成,马上就好。')));
    }

    const resumed = local.downloaded_bytes > 0;
    const lowMemory = local.memory_available_bytes !== null && local.memory_available_bytes < entry.ram_bytes;
    const lowDisk = local.disk_free_bytes !== null && local.disk_free_bytes < entry.bytes * 1.2;
    return h('section', { class: 'card', 'aria-label': t('本机模型') },
      h('div', { class: 'card-head' },
        head(h('span', { class: 'badge mute' }, t('未启用'))),
        h('button', { class: 'btn primary', type: 'button', 'data-key': 'local-enable', onclick: () => localAction('enable', { model_id: entry.id }) }, resumed ? t('继续下载') : t('下载并启用'))),
      about,
      facts,
      resumed ? h('span', { class: 'small muted' }, t('上次下载到 {0} / {1},会接着下。', bytes(local.downloaded_bytes), bytes(entry.bytes))) : null,
      local.phase === 'error' ? h('div', { class: 'error', role: 'alert' }, t('没成功:{0}', local.error)) : null,
      lowMemory ? h('div', { class: 'notice' }, t('这台机器现在可用内存是 {0},比它需要的少,可能跑不动。', bytes(local.memory_available_bytes))) : null,
      lowDisk ? h('div', { class: 'notice' }, t('硬盘剩余空间只有 {0},可能放不下。', bytes(local.disk_free_bytes))) : null);
  }

  async function vectorAction(path) {
    try {
      state.vectors = await api('POST', `/api/v1/admin/vectors/${path}`, {});
      state.loadError = '';
    } catch (error) {
      state.loadError = say(error);
    }
    await refresh();
  }

  function viewVectors() {
    const v = state.vectors;
    if (!v) return null;
    const option = v.model || v.catalog[0];
    const head = (badge) => h('div', { class: 'row' }, h('h2', {}, t('按意思召回')), h('span', { class: 'badge accent' }, t('自带')), badge);
    const about = h('p', { class: 'small muted' }, t('只靠字面,问法和记忆用词不一样就找不到。打开后,服务端用一个小模型理解意思再找,')
      + t('在你自己的记忆上实测:前 10 条里找到对的那条,从 61% 提到 90%。跑在这台 NAS 上,不花钱,记忆不出门。'));
    const facts = option ? h('span', { class: 'small' }, `${option.label} · ${tx(option.note || '')}`) : null;
    if (!v.available) {
      return h('section', { class: 'card', 'aria-label': t('按意思召回') }, head(h('span', { class: 'badge mute' }, t('不可用'))), about,
        h('div', { class: 'notice' }, t('这个服务端镜像里没有向量组件。更新到新版镜像后就能打开。')));
    }
    if (!v.enabled) {
      return h('section', { class: 'card', 'aria-label': t('按意思召回') },
        h('div', { class: 'card-head' }, head(h('span', { class: 'badge mute' }, t('未启用'))),
          h('button', { class: 'btn primary', type: 'button', 'data-key': 'vectors-enable', onclick: () => vectorAction('enable') }, t('下载并启用'))),
        about, facts,
        option ? h('span', { class: 'tiny muted' }, t('第一次要下载约 {0},再给现有记忆逐条算一遍(几万条大约十几分钟);之后新记忆会自动补上。', bytes(option.bytes))) : null);
    }
    const share = v.download_bytes ? Math.min(100, Math.round((v.downloaded / v.download_bytes) * 100)) : 0;
    const indexed = v.active ? Math.min(100, Math.floor((v.indexed / v.active) * 100)) : 0;
    const badge = {
      downloading: [t('正在下载 · {0}%', share), 'accent'], verifying: [t('正在校验文件…'), 'accent'], loading: [t('正在加载…'), 'accent'],
      indexing: [t('正在建索引 · {0}%', indexed), 'accent'], ready: [t('已启用'), 'ok'], error: [t('出错了'), 'warn'], off: [t('准备中…'), 'mute'],
    }[v.phase] || [v.phase, 'mute'];
    return h('section', { class: 'card', 'aria-label': t('按意思召回') },
      h('div', { class: 'card-head' }, head(h('span', { class: `badge ${badge[1]}` }, badge[0])),
        h('button', { class: 'btn quiet danger', type: 'button', 'data-key': 'vectors-disable',
          onclick: () => ask(t('关闭按意思召回?'), t('召回回到只按字面。已经算好的向量留着,再打开时不用重算(换了模型才会重算)。'), t('关闭'), () => api('POST', '/api/v1/admin/vectors/disable', {})) }, t('关闭'))),
      facts,
      v.phase === 'downloading' ? h('div', { class: 'bar', role: 'progressbar', 'aria-label': t('下载进度'), 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(share) }, h('span', { width: `${share}%` })) : null,
      ['indexing', 'ready'].includes(v.phase) ? h('div', { class: 'bar', role: 'progressbar', 'aria-label': t('索引进度'), 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(indexed) }, h('span', { width: `${indexed}%` })) : null,
      h('span', { class: 'small muted' }, v.phase === 'downloading'
        ? t('已下载 {0} / {1}。', bytes(v.downloaded), bytes(v.download_bytes))
        : t('已算好 {0} / {1} 条记忆。', num(v.indexed), num(v.active)) + (v.phase === 'ready' ? t('agent 召回时会同时按字面和按意思找,再精排一遍。') : t('算好之前,召回照常按字面找。'))),
      v.phase === 'error' ? h('div', { class: 'error', role: 'alert' }, t('没成功:{0}', v.error)) : null);
  }

  async function setSlot(slot, role, sourceId, model) {
    const key = `${slot}:${role}`;
    state.slotBusy[key] = true;
    state.slotNote[key] = null;
    render();
    try {
      await api('POST', '/api/v1/admin/models/slots', { slot, role, source_id: sourceId, model: model || undefined });
      state.slotNote[key] = { ok: true, text: sourceId === null ? t('已清空') : t('已调通,已保存') };
    } catch (error) {
      state.slotNote[key] = { ok: false, text: t('没保存:{0}', say(error)) };
    }
    delete state.slotBusy[key];
    await refresh();
  }

  async function setEffort(slot, effort) {
    state.slotBusy[`${slot}:effort`] = true;
    delete state.slotNote[`${slot}:effort`];
    render();
    try {
      await api('POST', '/api/v1/admin/models/slots/effort', { slot, effort });
      state.slotNote[`${slot}:effort`] = { ok: true, text: effort ? t('已用「{0}」真调通并保存', effort) : t('已改回模型默认') };
      if (state.effortCustom) delete state.effortCustom[slot];
    } catch (error) {
      state.slotNote[`${slot}:effort`] = { ok: false, text: say(error) };
    }
    delete state.slotBusy[`${slot}:effort`];
    await refresh();
  }

  // Pick from the levels pulled for the slot's main model: from its endpoint's model
  // list, or from a model catalog an agent reported. Typing is only the fallback.
  function viewEffort(slot, title, current) {
    const main = state.models.slots[slot].main;
    const source = main ? state.models.sources.find((item) => item.id === main.source_id) : null;
    const known = source && source.levels ? source.levels[main.model] : null;
    const levels = known ? known.levels : [];
    const key = `${slot}:effort`;
    const note = state.slotNote[key];
    const inputId = `effort-${slot}`;
    const busy = !main || Boolean(state.slotBusy[key]);
    const custom = state.effortCustom && state.effortCustom[slot];
    const typed = (value) => { const word = value.trim(); if (word !== (current || '')) setEffort(slot, word); };
    let control;
    if (levels.length && !custom && (!current || levels.includes(current))) {
      control = h('select', {
        id: inputId, disabled: busy, 'aria-label': t('{0}的思考档位', title),
        onchange: (event) => {
          if (event.target.value === '__other__') { state.effortCustom = Object.assign({}, state.effortCustom, { [slot]: true }); render(); return; }
          setEffort(slot, event.target.value);
        },
      },
        h('option', { value: '', selected: !current }, known.default ? t('模型默认({0})', known.default) : t('模型默认')),
        levels.map((level) => h('option', { value: level, selected: current === level }, level)),
        h('option', { value: '__other__' }, t('其他写法…')));
    } else {
      control = h('input', {
        id: inputId, type: 'text', value: current || '', placeholder: t('模型默认'), autocomplete: 'off', spellcheck: 'false',
        disabled: busy, 'aria-label': t('{0}的思考档位', title), onchange: (event) => typed(event.target.value),
      });
    }
    const origin = known ? (known.from === 'endpoint' ? t('这个来源的模型列表') : t('{0} 报告的官方模型目录', known.from)) : '';
    return h('div', { class: 'stack' },
      h('label', { class: 'tiny muted', for: inputId }, t('思考档位')),
      control,
      h('span', { class: 'tiny muted' }, !main ? t('先选主用模型') : levels.length
        ? t('档位来自{0}', origin)
        : t('查不到这个模型的档位:照官方写法填,原样发给模型')),
      state.slotBusy[key] ? h('span', { class: 'tiny muted', role: 'status' }, t('正在用这个档位真调一次…')) : null,
      note ? h('span', { class: note.ok ? 'tiny ok-text' : 'tiny bad-text', role: 'status' }, note.text) : null);
  }

  // One choice per job: any model any source has pulled, grouped by source. A relay
  // with many models is added once; each job picks the model it wants from it.
  function viewSlotRole(slot, role, current) {
    const key = `${slot}:${role}`;
    const selectId = `slot-${slot}-${role}`;
    const note = state.slotNote[key];
    const chosen = current ? `${current.source_id}::${current.model}` : '';
    const groups = state.models.sources.map((source) => {
      const names = [...new Set([
        ...(source.models || []),
        ...(source.model ? [source.model] : []),
        ...(current && current.source_id === source.id ? [current.model] : []),
      ])];
      return h('optgroup', { label: source.name }, names.length
        ? names.map((name) => h('option', { value: `${source.id}::${name}`, selected: chosen === `${source.id}::${name}` }, `${source.name} · ${name}`))
        : h('option', { value: `none-${source.id}`, disabled: true }, t('{0}(先在上面拉取模型)', source.name)));
    });
    const select = h('select', {
      id: selectId, disabled: Boolean(state.slotBusy[key]),
      onchange: (event) => {
        const value = event.target.value;
        if (!value) { setSlot(slot, role, null); return; }
        const at = value.indexOf('::');
        setSlot(slot, role, Number(value.slice(0, at)), value.slice(at + 2));
      },
    }, h('option', { value: '', selected: !current }, role === 'backup' ? t('不设备用') : t('还没选')), groups);
    return h('div', { class: 'slot-role' },
      h('div', { class: 'field' }, h('label', { for: selectId }, role === 'main' ? t('主用') : t('备用')), select),
      state.slotBusy[key] ? h('span', { class: 'tiny muted', role: 'status' }, t('正在真调一次…')) : null,
      note ? h('span', { class: note.ok ? 'tiny ok-text' : 'tiny bad-text', role: 'status' }, note.text) : null);
  }

  // ---- what was sent to models, byte for byte ---------------------------------------

  const TASKS = { daily: t('每晚提炼'), import: t('历史导入'), reflect: t('深度归纳'), note: t('会话小结'), answer: t('按记忆作答'), check: t('体检与对比'), organise: t('整理与归纳'), test: t('测通') };
  const SCOPES = { nas: t('这台 NAS'), lan: t('家里局域网'), outside: t('外面') };

  async function openSent(id) {
    if (state.sentOpen && state.sentOpen.id === id) { state.sentOpen = null; render(); return; }
    try { state.sentOpen = await api('GET', `/api/v1/admin/sent/${id}`); } catch (error) { state.loadError = say(error); }
    render();
  }

  // The request as it was sent, easier to read: its strings with their line breaks.
  function readable(body) {
    try {
      const parsed = JSON.parse(body);
      return Object.entries(parsed).map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value, null, 1).replace(/\\n/g, '\n')}`).join('\n\n');
    } catch (error) { return body; }
  }

  function viewSent() {
    const s = state.sent;
    if (!s) return null;
    const outside = s.today.find((row) => row.scope === 'outside');
    const all = s.today.reduce((sum, row) => sum + row.calls, 0);
    const pick = (value, set, options, label) => h('select', { class: 'place-input', 'aria-label': label, onchange: (event) => { set(event.target.value); refresh(); } },
      [h('option', { value: '' }, label), ...options.map(([id, name]) => h('option', { value: id, selected: id === value }, name))]);
    const open = state.sentOpen;
    return h('section', { class: 'card', 'aria-label': t('发给模型的内容') },
      h('div', { class: 'card-head' },
        h('div', { class: 'stack' }, h('h2', {}, t('发给模型的内容')),
          h('span', { class: 'small muted' }, t('每一次都按实际发出去的字节记下,不是事后拼的;点开能看到原样。密钥不在里面。原文留 {0} 天,发了什么、发到哪、多少字节、指纹留一年。', s.retain_days))),
        h('div', { class: 'row' },
          pick(state.sentTask, (value) => { state.sentTask = value; }, s.tasks.map((id) => [id, TASKS[id] || id]), t('全部任务')),
          pick(state.sentScope, (value) => { state.sentScope = value; }, Object.entries(SCOPES), t('发到哪都看')))),
      h('p', { class: 'small' }, all ? t('今天发了 {0} 次', num(all)) + (outside ? t(',其中发到外面 {0} 次、{1}', num(outside.calls), bytes(outside.bytes)) : t(',都没有出家门')) : t('今天还没有发过。')),
      s.missed ? h('p', { class: 'small warn-text' }, t('有 {0} 次没能记上(多半是磁盘写不进去),那几次的内容看不到。', num(s.missed))) : null,
      s.calls.length ? h('ul', { class: 'list' }, s.calls.map((call) => h('li', { class: 'task' },
        h('button', { class: 'link sent-row', type: 'button', 'data-key': `sent-${call.id}`, 'aria-expanded': open && open.id === call.id ? 'true' : 'false', onclick: () => openSent(call.id) },
          `${new Date(call.at * 1000).toLocaleString(LOCALE)} · ${TASKS[call.task] || call.task} · ${call.model}`),
        h('span', { class: 'tiny muted' }, [`${call.source} (${call.host}) · ${SCOPES[call.scope] || call.scope}`, t('发出 {0}', bytes(call.bytes)), call.answer_bytes ? t('收到 {0}', bytes(call.answer_bytes)) : '',
          call.status === 'ok' ? '' : call.status === 'sent' ? t('还没有结果') : call.status === 'error:interrupted' ? t('服务端重启时被打断') : t('没成:{0}', call.status.replace('error:', ''))].filter(Boolean).join(' · ')),
        open && open.id === call.id ? h('div', { class: 'stack gap' },
          open.body === null ? h('span', { class: 'small muted' }, t('原文已过保留期,只剩这一行记录。')) : [
            h('span', { class: 'tiny muted' }, open.intact ? t('原文和记录的指纹一致:sha256 {0}', open.sha256) : t('⚠️ 原文和记录的指纹对不上')),
            h('h3', { class: 'label' }, t('发出去的')), h('pre', { class: 'notes' }, readable(open.body)),
            h('details', { 'data-key': `sent-raw-${open.id}` }, h('summary', { class: 'small' }, t('一个字节都没动过的原样')), h('pre', { class: 'notes' }, open.body))],
          open.answer ? [h('h3', { class: 'label' }, t('收到的')), h('pre', { class: 'notes' }, open.answer)] : null) : null))) : null,
      s.calls.length === 50 ? h('span', { class: 'tiny muted' }, t('只列最近 50 次,一共 {0} 次。用上面的筛选找更早的。', num(s.total))) : null);
  }

  function viewModels() {
    const head = pageHead(t('模型'), t('先接入模型来源,再把每项任务交给其中一个模型。怎么搭配由你决定,随时可改。'));
    if (!state.models) return [head, h('div', { class: 'card' }, h('p', { class: 'muted' }, t('正在读取…')))];
    const { sources, slots } = state.models;
    const adding = state.sourceForm && state.sourceForm.id === null;

    // The built-in model has its own card; the cards below are the sources the owner added.
    const sourceCards = sources.filter((source) => !source.builtin)
      .map((source) => (state.sourceForm && state.sourceForm.id === source.id ? viewSourceForm() : viewSource(source)));
    const addButton = adding ? viewSourceForm() : h('button', { class: 'btn dashed', type: 'button', onclick: () => openSourceForm(null) }, icon('plus', 18), t('添加模型来源'));

    const jobs = h('section', { class: 'card', 'aria-labelledby': 'jobs-title' },
      h('div', { class: 'stack' },
        h('h2', { id: 'jobs-title' }, t('任务分工')),
        h('p', { class: 'small muted' }, t('每项任务选一个主用模型,可再加一个备用。选定时会真调一次,通了才保存。主用连不上(比如余额用完)时自动换到备用,恢复后自动换回。调用一律流式;思考档位用模型自己的写法,填了才发,保存前真调一次。'))),
      sources.length
        ? SLOT_INFO.map(([slot, title, text]) => h('div', { class: 'slot' },
          h('div', { class: 'stack slot-name' }, h('strong', {}, title), h('span', { class: 'small muted' }, text),
            viewEffort(slot, title, slots[slot].effort)),
          viewSlotRole(slot, 'main', slots[slot].main),
          viewSlotRole(slot, 'backup', slots[slot].backup)))
        : h('p', { class: 'muted' }, t('先在上面添加一个模型来源并选好模型,这里才能分配任务。')),
      h('div', { class: 'slot' },
        h('div', { class: 'stack slot-name' }, h('strong', {}, t('向量')), h('span', { class: 'small muted' }, t('把记忆变成可以按意思搜索的索引。'))),
        h('span', { class: 'small muted' }, state.vectors && state.vectors.enabled
          ? t('用自带的 {0},在下面「按意思召回」里管理。', state.vectors.model ? state.vectors.model.label : t('小模型'))
          : t('用自带的小模型,在下面「按意思召回」里打开。'))));

    const outage = h('section', { class: 'card' },
      h('h2', {}, t('断联时怎么办')),
      h('p', { class: 'small muted' }, t('某个来源余额用完、key 失效或连不上时,服务端自己这样处理:')),
      h('ol', { class: 'steps' },
        h('li', {}, t('这个来源标成没调通,并写明原因:余额不足、key 失效,还是连不上')),
        h('li', {}, t('用它的任务换到各自的备用模型;没设备用的停在断点等着,进度不丢')),
        h('li', {}, t('之后每 30 分钟自动再试一次,充值后自己接着整理、换回主用;也可以手动点「测通」'))),
      h('span', { class: 'tiny muted' }, t('偶尔超时或繁忙的单次请求,会先隔一会儿重试两次,不会因此停下。')));

    return [head, h('h2', { class: 'section-title' }, t('模型来源')), viewLocalModel(), sourceCards, addButton, jobs, viewVectors(), outage, viewSent()];
  }

  // ---- distillation and memories ------------------------------------------

  const KIND_LABELS = { decision: t('决定'), preference: t('偏好'), correction: t('纠正'), fact: t('事实'), lesson: t('教训') };
  const RUN_REASONS = Object.assign({ bad_output: t('模型没有按要求的格式回答'), not_configured: t('还没选模型'), internal: t('服务端内部出错') }, REASON_SHORT);

  function distillSummary() {
    const d = state.distill;
    if (!d) return { title: '…', note: '' };
    const last = d.runs[0];
    if (!d.has_model) return { title: t('未选模型'), note: t('到「模型」页给「日常提炼」选一个') };
    if (d.running && d.live.job === 'import') return { title: t('正在整理历史'), note: t('这一轮已读 {0} 段,新增 {1} 条记忆 · 见「导入」页', num(d.live.segments), num(d.live.memories)) };
    if (d.running) return { title: t('正在提炼'), note: t('已读 {0} 段对话,新增 {1} 条记忆', num(d.live.segments), num(d.live.memories)) };
    if (last && last.status === 'stopped') return { title: t('提炼停下了'), note: t('原因:{0}。进度没丢,每 30 分钟自动再试一次', RUN_REASONS[last.error_reason] || t('出错')) };
    if (d.pending.segments) return { title: t('待提炼 {0} 段', num(d.pending.segments)), note: t('约 {0} 字 · 每晚 {1}:00 自动开始', num(d.pending.chars), String(d.nightly_hour).padStart(2, '0')) };
    return { title: t('已提炼完'), note: t('共 {0} 条有效记忆', num(d.memories.active)) };
  }

  async function startDistill() {
    state.distillNote = '';
    try {
      await api('POST', '/api/v1/admin/distill/run', {});
    } catch (error) {
      state.distillNote = say(error);
    }
    await refresh();
  }

  function daysLeft(memory) {
    const kept = state.memories.retention_days;
    return Math.max(0, kept - Math.floor((state.now - memory.expired_at) / 86400));
  }

  function viewDistillStrip() {
    const d = state.distill;
    if (!d) return null;
    const summary = distillSummary();
    const last = d.runs[0];
    const canRun = d.has_model && !(d.lives && d.lives.daily) && d.pending.segments > 0;
    return h('section', { class: 'card', 'aria-label': t('提炼状态') },
      h('div', { class: 'card-head' },
        h('div', { class: 'stack' },
          h('div', { class: 'row' }, h('h2', {}, summary.title), d.running ? h('span', { class: 'badge accent' }, t('进行中')) : null),
          h('span', { class: 'small muted' }, summary.note)),
        h('button', { class: 'btn primary', type: 'button', disabled: !canRun, onclick: startDistill }, t('立即提炼'))),
      state.distillNote ? h('div', { class: 'error', role: 'alert' }, state.distillNote) : null,
      last && last.status === 'done' && !d.running ? h('span', { class: 'tiny muted' },
        t('上一次:{0},读了 {1} 段对话,新增 {2} 条记忆', relTime(last.finished_at), num(last.segments), num(last.memories)) +
        (last.rejected ? t(',另有 {0} 条因为引文在原话里找不到而没有收', num(last.rejected)) : '') +
        (last.skipped ? t(';{0} 个会话模型没按格式回答,留到下次再整理', num(last.skipped)) : '') +
        (last.merged ? t(';{0} 条和已有记忆重复,并进了原来那条', num(last.merged)) : '') +
        t(' · 用 {0}', last.model)) : null);
  }

  const SHELVES = [['', t('全部')], ['zhiyi', t('知意')], ['xingce', t('行策')], ['toolbook', t('工具书')], ['experience', t('经验')], ['errata', t('勘误')]];
  const SHELF_NOTES = {
    zhiyi: t('懂你:你的喜好、习惯,和你纠正过的地方。'),
    xingce: t('办事的方法:定下的做法和踩过的坑。'),
    toolbook: t('稳定的事实:设备、环境、项目在哪。'),
    experience: t('从一个项目的许多记忆里归纳出的经验,先读它们就能少走弯路。'),
    errata: t('被更新的说法取代的,和被 agent 借用后判为误导的。都留着,可以撤销。'),
  };
  const SHELF_NAMES = { zhiyi: t('知意'), xingce: t('行策'), toolbook: t('工具书'), experience: t('经验') };
  const EVOLUTION_STATUS = { done: [t('完成'), 'ok'], paused: [t('你暂停了'), 'mute'], stopped: [t('停下了'), 'warn'], running: [t('进行中'), 'accent'], interrupted: [t('被重启打断'), 'mute'] };

  async function evolutionAction(path) {
    state.distillNote = '';
    try { await api('POST', `/api/v1/admin/evolution/${path}`, {}); } catch (error) { state.distillNote = say(error); }
    await refresh();
  }

  function viewEvolutionStrip() {
    const e = state.evolution;
    if (!e) return null;
    const last = e.runs[0];
    const live = e.live;
    const STEP = { review: t('在比对相近的说法'), judge: t('在看借用评价'), digest: t('在归纳经验') };
    const note = live
      ? t('{0}:已判 {1} 对,取代 {2} 条,归纳了 {3} 个项目、{4} 条经验', STEP[live.step] || t('在整理'), num(live.reviewed), num(live.replaced), num(live.groups), num(live.experiences))
      : !e.has_model ? t('还没给「深度归纳」选模型。选好后每晚提炼完会自动整理一次。')
        : last ? t('上一次 {0}:判了 {1} 对说法,取代 {2} 条、并掉 {3} 条、判误 {4} 条;归纳 {5} 个项目、新增 {6} 条经验', relTime(last.started_at), num(last.reviewed), num(last.replaced), num(last.folded), num(last.judged), num(last.groups), num(last.experiences)) +
          (last.status === 'stopped' && last.error ? t(' · 停下了:{0}', last.error.split(':')[0]) : '')
          : t('每晚提炼完会自动整理一次:比对相近的说法、看借用评价、把项目归纳成经验。');
    return h('section', { class: 'card', 'aria-label': t('整理与归纳') },
      h('div', { class: 'card-head' },
        h('div', { class: 'stack' },
          h('strong', {}, live ? (live.pausing ? t('正在暂停…') : t('正在整理与归纳')) : t('整理与归纳')),
          h('span', { class: 'small muted' }, note),
          h('span', { class: 'tiny muted' }, t('现有经验 {0} 条(来自 {1} 个项目) · 已取代 {2} 条 · 判误 {3} 条', num(e.experiences), num(e.projects), num(e.replaced), num(e.judged)) +
            (e.waiting_pairs ? t(' · 还有 {0} 对相近说法待比对', num(e.waiting_pairs)) : ''))),
        live
          ? h('button', { class: 'btn', type: 'button', disabled: live.pausing, onclick: () => evolutionAction('pause') }, t('暂停'))
          : e.has_model
            ? h('button', { class: 'btn', type: 'button', onclick: () => evolutionAction('run') }, t('现在整理'))
            : h('a', { class: 'btn', href: '#/models' }, t('去选模型'))));
  }

  // ---- asking memory: an answer only from what was said, or "don't know" ---------

  async function askMemory() {
    const question = (state.askText || '').trim();
    if (!question || state.askBusy) return;
    state.askBusy = true;
    state.askResult = null;
    state.askError = '';
    render();
    try {
      state.askResult = await api('POST', '/api/v1/admin/answer', { question });
    } catch (error) {
      state.askError = say(error);
    }
    state.askBusy = false;
    render();
  }

  function viewAsk() {
    const r = state.askResult;
    const meta = r ? t('看过 {0} 条相关记忆', num(r.considered || 0)) + (r.model ? ` · ${r.model}` : '') : '';
    return h('details', { class: 'card', 'data-key': 'ask-card' },
      h('summary', {}, h('strong', {}, t('按记忆问一问')),
        h('span', { class: 'small muted' }, t(' 只凭记忆和原话作答,必须说出依据哪几条;记忆里没说过的就答「不知道」'))),
      h('div', { class: 'row' },
        h('div', { class: 'field grow' },
          h('label', { class: 'sr', for: 'ask-input' }, t('问题')),
          h('input', {
            id: 'ask-input', type: 'text', value: state.askText || '', placeholder: t('例如:服务端装在 NAS 的哪一层?'), autocomplete: 'off',
            oninput: (event) => { state.askText = event.target.value; },
            onkeydown: (event) => { if (event.key === 'Enter') askMemory(); },
          })),
        h('button', { class: 'btn', type: 'button', disabled: !!state.askBusy, onclick: askMemory }, state.askBusy ? t('在查…') : t('问'))),
      state.askError ? h('div', { class: 'error', role: 'alert' }, state.askError) : null,
      !r ? null : r.verdict === 'answered'
        ? h('div', { class: 'stack' },
          h('p', {}, r.answer),
          r.missing ? h('p', { class: 'small muted' }, t('记忆没说到的:{0}', r.missing)) : null,
          h('ul', { class: 'list' }, (r.memories || []).map((memory) => h('li', {},
            h('button', { class: 'link', type: 'button', 'data-key': `ask-open-${memory.id}`, onclick: () => openMemory(memory.id) },
              `#${memory.id} ${memory.statement}`)))),
          h('span', { class: 'tiny muted' }, t('依据 {0} 条 · {1}', r.used.length, meta)))
        : h('div', { class: 'stack' },
          h('p', {}, h('strong', {}, t('不知道')), `:${r.unknown_reason}`),
          meta ? h('span', { class: 'tiny muted' }, meta) : null));
  }

  function linkRow(item, act, label, undoable) {
    return h('li', {},
      h('span', { class: 'grow' },
        h('span', { class: 'tiny muted' }, `${label} `),
        h('button', { class: 'link', type: 'button', 'data-key': `open-${item.id}`, onclick: () => jumpTo(item.id) }, `#${item.id} ${item.statement}`),
        item.reason ? h('span', { class: 'tiny muted' }, ` · ${item.reason}`) : null,
        item.undone_at ? h('span', { class: 'tiny muted' }, t(' · 已撤销')) : null),
      undoable && !item.undone_at ? act(t('撤销'), '', `undo-${item.link_id}`, async () => {
        try { await api('POST', `/api/v1/admin/links/${item.link_id}/undo`, {}); } catch (error) { state.loadError = say(error); }
        await refresh();
      }) : null);
  }

  function viewChain(memory, act) {
    const links = memory.links || {};
    const live = (items) => (items || []).filter((item) => !item.undone_at);
    const rows = [
      ...live(links.replaced_by).map((item) => linkRow(item, act, t('被它取代:'), true)),
      ...live(links.replaces).map((item) => linkRow(item, act, t('取代了:'), true)),
      ...(links.derived_from || []).map((item) => linkRow(item, act, t('归纳自:'), false)),
      ...(links.drawn_into || []).filter((item) => item.status === 'active').map((item) => linkRow(item, act, t('归纳进经验:'), false)),
    ];
    const judged = live(links.judged).filter((item) => item.decided_by === 'returns');
    if (!rows.length && !judged.length) return null;
    return h('div', { class: 'stack gap' },
      h('h3', { class: 'label' }, t('演化')),
      judged.length ? h('span', { class: 'small warn-text' }, t('agent 借用后判为误导:{0}。如果它其实没错,点下面的「恢复为有效」,以后不会再因此被撤下。', judged[0].reason)) : null,
      rows.length ? h('ul', { class: 'list' }, rows) : null,
      memory.kind === 'experience' ? h('span', { class: 'tiny muted' }, t('经验由「深度归纳」模型从这些记忆里归纳;项目又积累了新记忆后会重新归纳,旧的经验被新的取代。')) : null);
  }

  function jumpTo(id) {
    state.memSelected = id;
    state.memJump = id;
    refresh();
  }

  function statusBadge(memory) {
    if (memory.status === 'folded') return h('span', { class: 'badge mute' }, t('已合并'));
    if (memory.status === 'superseded') return h('span', { class: 'badge warn' }, t('已被取代'));
    if (memory.status === 'expired') return h('span', { class: 'badge warn' }, t('已失效'));
    return h('span', { class: 'badge ok' }, t('有效'));
  }

  function viewRestatements(memory, act) {
    if (memory.status === 'folded') {
      return h('div', { class: 'stack gap' },
        h('h3', { class: 'label' }, t('重复说法')),
        h('span', { class: 'small' }, t('这条和 #{0} 说的是同一件事,已经合并进去,不会再被单独召回;它的原话也挂到了那一条上。', memory.folded_into)),
        h('div', { class: 'row' },
          act(t('看 #{0}', memory.folded_into), '', `jump-${memory.folded_into}`, () => jumpTo(memory.folded_into)),
          act(t('拆出来'), '', `unfold-${memory.id}`, async () => {
            try { await api('POST', `/api/v1/admin/memories/${memory.id}/unfold`, {}); } catch (error) { state.loadError = say(error); }
            await refresh();
          })));
    }
    if (!memory.restated) return null;
    return h('div', { class: 'stack gap' },
      h('h3', { class: 'label' }, t('合并进来的重复说法 {0} 条', memory.restated)),
      h('span', { class: 'tiny muted' }, t('别的对话里又说了同一件事,提炼出的重复记忆并到这里,原话一起挂上来。合并错了可以拆出来。')),
      h('ul', { class: 'list' }, memory.restatements.map((item) => h('li', {},
        h('span', { class: 'grow' },
          h('button', { class: 'link', type: 'button', 'data-key': `open-${item.id}`, onclick: () => jumpTo(item.id) }, item.statement),
          h('span', { class: 'tiny muted' }, ` ${new Date(item.created_at * 1000).toLocaleDateString(LOCALE)} · ${item.device} · ${item.agent}` +
            (item.similarity ? t(' · 用词重合 {0}%', Math.round(item.similarity * 100)) : ''))),
        act(t('拆出来'), '', `unfold-${item.id}`, async () => {
          try { await api('POST', `/api/v1/admin/memories/${item.id}/unfold`, {}); } catch (error) { state.loadError = say(error); }
          await refresh();
        })))));
  }

  function viewMemoryDetail() {
    const memory = state.memDetail;
    if (!memory) return h('aside', { class: 'card detail', 'aria-label': t('记忆详情') }, h('p', { class: 'empty' }, t('点左边一条记忆,查看支撑它的原话。')));
    const expired = memory.status === 'expired';
    const folded = memory.status === 'folded';
    const act = (label, cls, key, run) => h('button', { class: `btn ${cls}`, type: 'button', 'data-key': key, onclick: run }, label);
    const change = (path) => async () => {
      try { await api('POST', `/api/v1/admin/memories/${memory.id}/${path}`, {}); } catch (error) { state.loadError = say(error); }
      await refresh();
    };
    return h('aside', { class: 'card detail', 'aria-label': t('记忆详情') },
      h('div', { class: 'stack' },
        h('div', { class: 'row' },
          statusBadge(memory),
          memory.shelf && SHELF_NAMES[memory.shelf] ? h('span', { class: 'badge accent' }, SHELF_NAMES[memory.shelf]) : null,
          memory.kind !== 'experience' ? h('span', { class: 'badge mute' }, KIND_LABELS[memory.kind] || memory.kind) : null,
          memory.note ? h('span', { class: 'badge warn' }, t('助手转述')) : null),
        memory.title ? h('strong', {}, memory.title) : null,
        h('h2', { class: 'detail-title' }, memory.statement),
        memory.when_to_use ? h('span', { class: 'small' }, t('什么时候想起它:{0}', memory.when_to_use)) : null,
        memory.note ? h('span', { class: 'small warn-text' }, t('这条说的是用户的意思,但原话里没有用户自己的话,只有助手的转述。agent 召回时会看到这个提醒。')) : null,
        memory.project || memory.folder ? h('span', { class: 'small' }, memory.project ? t('项目「{0}」', memory.project) : t('文件夹 {0}(还没声明属于哪个项目)', memory.folder)) : null,
        memory.history ? h('span', { class: 'small muted' }, t('履历:') + [
          memory.history.first_said ? t('{0} 第一次说起', memory.history.first_said.slice(0, 10)) : '',
          memory.history.last_said && memory.history.last_said.slice(0, 10) !== (memory.history.first_said || '').slice(0, 10) ? t('最近 {0}', memory.history.last_said.slice(0, 10)) : '',
          memory.history.conversations > 1 ? t('来自 {0} 个对话', memory.history.conversations) : '',
          Object.keys(memory.history.borrowers).length ? t('被 ') + Object.entries(memory.history.borrowers).map(([agent, n]) => t('{0} 借 {1} 次', agent, n)).join(t('、')) : t('还没被借过'),
        ].filter(Boolean).join(' · ')) : null,
        h('span', { class: 'small muted' }, t('{0} 提炼 · {1} · {2}{3} · ', new Date(memory.created_at * 1000).toLocaleDateString(LOCALE), memory.device, memory.agent, memory.surface ? `(${memory.surface})` : '') +
          (memory.recall_count ? t('被 agent 召回 {0} 次,最近一次 {1}', memory.recall_count, relTime(memory.last_recalled_at)) : t('还没被 agent 召回过')))),
      viewChain(memory, act),
      viewRestatements(memory, act),
      h('div', { class: 'stack gap' },
        h('h3', { class: 'label' }, t('支撑它的原话')),
        memory.evidence.map((item) => h('figure', { class: 'quote' },
          h('blockquote', {}, item.quote),
          h('figcaption', {}, `${item.voice === 'relayed' ? t('用户转贴的(不是用户本人的话)') : item.role === 'user' ? t('用户说的') : t('助手说的')}${item.ts ? ` · ${new Date(item.ts).toLocaleString(LOCALE)}` : ''}`))),
        h('span', { class: 'tiny muted' }, t('证据只保存原话片段,并且逐字核对过确实出现在对话里。'))),
      viewLoans(memory),
      folded || memory.status === 'superseded' ? null : h('div', { class: 'stack gap lifecycle' },
        h('h3', { class: 'label' }, t('生命周期')),
        expired
          ? h('span', { class: 'small' }, h('strong', { class: 'warn-text' }, t('{0} 天后自动清除', daysLeft(memory))),
            t(' · 失效原因:{0}。失效的记忆不会再被召回。', memory.expire_reason === 'manual' ? t('你手动标记') : memory.expire_reason || '—'))
          : h('span', { class: 'small muted' }, t('有效。失效后保留 {0} 天,到期自动清除。', state.memories.retention_days)),
        h('div', { class: 'row' },
          expired ? act(t('恢复为有效'), '', `restore-${memory.id}`, change('restore')) : act(t('标记失效'), '', `expire-${memory.id}`, change('expire')),
          act(t('立即清除'), 'danger', `purge-${memory.id}`, () => ask(t('立即清除这条记忆?'),
            t('这条记忆和它的原话证据都会删掉') + (memory.restated ? t(',合并进来的 {0} 条重复说法也一起删掉', memory.restated) : '') + t(',无法恢复。'), t('清除'),
            () => api('POST', `/api/v1/admin/memories/${memory.id}/purge`, {}))))));
  }

  const OUTCOME = { useful: [t('有用'), 'ok'], useless: [t('没用上'), 'mute'], misleading: [t('误导'), 'warn'] };

  function verdictText(returns) {
    const r = returns || {};
    return ['useful', 'useless', 'misleading'].filter((key) => r[key]).map((key) => `${OUTCOME[key][0]} ${r[key]}`).join(' · ');
  }

  function viewLoans(memory) {
    const judged = (memory.loans || []).filter((loan) => loan.outcome);
    const summary = verdictText(memory.returns);
    return h('div', { class: 'stack gap' },
      h('h3', { class: 'label' }, t('借还记录')),
      h('span', { class: 'small' }, (memory.lent ? t('被 agent 借过 {0} 次', memory.lent) : t('还没被 agent 借过')) + (summary ? t(' · 还回时的评价:{0}', summary) : '')),
      judged.length
        ? h('ul', { class: 'list' }, judged.map((loan) => h('li', {},
          h('span', { class: 'when' }, relTime(loan.returned_at)),
          h('span', { class: 'grow' }, `${loan.device || '—'} · ${loan.agent || '—'}` + (loan.note ? `:${loan.note}` : '')),
          h('span', { class: `badge ${OUTCOME[loan.outcome][1]}` }, OUTCOME[loan.outcome][0]))))
        : h('span', { class: 'tiny muted' }, t('agent 用完记忆后,可以把它还回来并评价:有用、没用上,还是误导。这些评价以后用来决定哪些记忆该沉下去、哪些该升级。')));
  }

  let searchTimer = null;

  // ---- the original words: everything that was said -------------------------------

  async function searchWords() {
    if (state.wordsBusy || !state.words.query.trim()) return;
    state.wordsBusy = true;
    state.wordsError = '';
    state.wordsOpen = null;
    render();
    try {
      const params = new URLSearchParams(Object.entries(state.words).filter(([, value]) => value && value.trim()));
      state.wordsResult = await api('GET', `/api/v1/admin/search?${params}`);
    } catch (error) {
      state.wordsError = say(error);
    }
    state.wordsBusy = false;
    render();
  }

  async function openTurn(id) {
    try { state.wordsOpen = await api('GET', `/api/v1/admin/segments/${id}/around`); } catch (error) { state.wordsError = say(error); }
    render();
  }

  // The words found, marked in an excerpt.
  function marked(text, words) {
    const low = text.toLowerCase();
    const spans = [];
    for (const word of words || []) {
      for (let at = low.indexOf(word); at !== -1 && spans.length < 400; at = low.indexOf(word, at + 1)) spans.push([at, at + word.length]);
    }
    spans.sort((a, b) => a[0] - b[0]);
    const out = [];
    let done = 0;
    for (let i = 0; i < spans.length; i += 1) {
      let [from, to] = spans[i];
      while (i + 1 < spans.length && spans[i + 1][0] <= to) { i += 1; to = Math.max(to, spans[i][1]); }
      out.push(text.slice(done, from), h('mark', {}, text.slice(from, to)));
      done = to;
    }
    out.push(text.slice(done));
    return out;
  }

  const VOICES = { user: t('用户说的'), relayed: t('用户转贴的'), assistant: t('助手说的') };

  function viewWords() {
    const w = state.words;
    const r = state.wordsResult;
    const field = (key, label, attrs) => h('div', { class: 'field' }, h('label', { for: `words-${key}` }, label),
      h('input', Object.assign({ id: `words-${key}`, value: w[key], autocomplete: 'off', oninput: (event) => { w[key] = event.target.value; }, onkeydown: (event) => { if (event.key === 'Enter') searchWords(); } }, attrs)));
    const tools = h('div', { class: 'stack gap' },
      h('div', { class: 'row' },
        h('div', { class: 'field grow search' }, h('label', { class: 'sr', for: 'words-query' }, t('搜原话')),
          h('input', {
            id: 'words-query', type: 'search', value: w.query, placeholder: t('想找的字句,照当时可能说的写'), autocomplete: 'off',
            oninput: (event) => { w.query = event.target.value; },
            onkeydown: (event) => { if (event.key === 'Enter') searchWords(); },
          })),
        h('button', { class: 'btn primary', type: 'button', 'data-key': 'words-go', disabled: state.wordsBusy, onclick: searchWords }, state.wordsBusy ? t('在找…') : t('找'))),
      h('div', { class: 'row' },
        h('div', { class: 'seg', role: 'group', 'aria-label': t('谁说的') }, [['', t('谁说的都找')], ['user', t('我说的')], ['assistant', t('助手说的')]].map(([id, label]) =>
          h('button', { type: 'button', 'data-key': `words-who-${id || 'any'}`, 'aria-pressed': w.who === id ? 'true' : 'false', onclick: () => { w.who = id; if (r) searchWords(); else render(); } }, label))),
        field('agent', t('哪个 agent'), { type: 'text', placeholder: t('不限') }),
        field('since', t('从'), { type: 'date' }), field('until', t('到'), { type: 'date' })));
    const index = r && r.index;
    const note = index && !index.ready ? h('p', { class: 'small muted' }, t('原话索引还在建:{0} / {1} 句,从最近的开始。没找到不代表没说过。', num(index.indexed), num(index.total))) : null;
    const list = h('div', { class: 'mem-list' }, !r
      ? h('p', { class: 'empty' }, t('记忆只留下了对话里值得记的一小部分。这里找的是所有电脑、所有 agent 的全部原话。'))
      : r.hits.length ? r.hits.map((hit) => h('button', {
        class: 'mem-card', type: 'button', 'data-key': `turn-${hit.segment}`, 'aria-pressed': state.wordsOpen && state.wordsOpen.segment === hit.segment ? 'true' : 'false',
        onclick: () => openTurn(hit.segment),
      },
        h('span', { class: 'small words-text' }, marked(hit.text, r.words)),
        h('span', { class: 'tiny muted' }, [VOICES[hit.voice] || hit.voice, hit.ts ? new Date(hit.ts).toLocaleString(LOCALE) : '', hit.device,
          hit.agent + (hit.surface ? `(${hit.surface})` : ''), hit.project ? t('项目「{0}」', hit.project) : hit.folder, hit.same ? t('另有 {0} 处相同', hit.same) : ''].filter(Boolean).join(' · '))))
        : h('p', { class: 'empty' }, t('没有找到。换个当时可能的说法再试。')));
    const open = state.wordsOpen;
    const turn = (item, here) => h('figure', { class: here ? 'quote' : 'quote plain' },
      h('blockquote', {}, here ? marked(item.text, r && r.words) : item.text),
      h('figcaption', {}, `${item.role === 'user' ? t('用户') : t('助手')}${item.ts ? ` · ${new Date(item.ts).toLocaleString(LOCALE)}` : ''}`));
    const side = h('aside', { class: 'card detail', 'aria-label': t('前后文') }, !open
      ? h('p', { class: 'empty' }, t('点左边一处,看它前后说了什么。'))
      : [h('span', { class: 'small muted' }, [open.device, open.agent + (open.surface ? `(${open.surface})` : ''), open.folder].filter(Boolean).join(' · ')),
        h('div', { class: 'stack gap' }, open.before.map((item) => turn(item, false)), turn(open.turn, true), open.after.map((item) => turn(item, false)))]);
    return [tools, state.wordsError ? h('div', { class: 'error', role: 'alert' }, state.wordsError) : null, note, h('div', { class: 'mem-layout' }, list, side)];
  }

  function viewMemory() {
    const head = [pageHead(t('记忆'), t('从对话里提炼出的记忆。每条都附着原话作为证据;过时的可以标记失效,保留一段时间后自动清除。')),
      h('div', { class: 'seg', role: 'group', 'aria-label': t('看记忆还是找原话') }, [['', t('记忆')], ['words', t('原话')]].map(([id, label]) =>
        h('button', { type: 'button', 'data-key': `view-${id || 'memories'}`, 'aria-pressed': state.memView === id ? 'true' : 'false', onclick: () => { state.memView = id; render(); } }, label)))];
    if (state.memView === 'words') return [head, viewWords()];
    if (!state.memories) return [head, viewDistillStrip(), h('div', { class: 'card' }, h('p', { class: 'muted' }, t('正在读取…')))];
    const { memories, counts } = state.memories;
    const shelves = state.memories.shelves || {};
    const shelfRow = h('div', { class: 'stack gap' },
      h('div', { class: 'chips', role: 'group', 'aria-label': t('按书架看') }, SHELVES.map(([id, label]) =>
        h('button', {
          class: 'pick', type: 'button', 'data-key': `shelf-${id || 'all'}`, 'aria-pressed': state.memShelf === id ? 'true' : 'false',
          onclick: () => { state.memShelf = id; if (id === 'errata') state.memFilter = ''; refresh(); },
        }, label, h('span', { class: 'pick-note' }, num(id ? shelves[id] || 0 : counts.active))))),
      state.memShelf ? h('span', { class: 'tiny muted' }, SHELF_NOTES[state.memShelf]) : null);
    const filters = [['', t('全部'), counts.active + counts.expired], ['active', t('有效'), counts.active], ['expired', t('已失效'), counts.expired],
      ['folded', t('已合并'), counts.folded || 0]];

    const tools = h('div', { class: 'row' },
      h('div', { class: 'field grow search' },
        h('label', { class: 'sr', for: 'mem-search' }, t('搜索记忆')),
        h('input', {
          id: 'mem-search', type: 'search', value: state.memQuery, placeholder: t('搜记忆和它引用的原话'), autocomplete: 'off',
          oninput: (event) => {
            state.memQuery = event.target.value;
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => refresh(), 300);
          },
        })),
      state.memShelf === 'errata' ? null : h('div', { class: 'seg', role: 'group', 'aria-label': t('按状态筛选') }, filters.map(([id, label, count]) =>
        h('button', { type: 'button', 'data-key': `filter-${id || 'all'}`, 'aria-pressed': state.memFilter === id ? 'true' : 'false', onclick: () => { state.memFilter = id; refresh(); } },
          `${label} ${num(count)}`))));

    const list = h('div', { class: 'mem-list' }, memories.length
      ? memories.map((memory) => h('button', {
        class: 'mem-card', type: 'button', 'data-key': `mem-${memory.id}`, 'aria-pressed': memory.id === state.memSelected ? 'true' : 'false',
        onclick: () => { state.memSelected = memory.id; state.memJump = null; refresh(); },
      },
        h('span', { class: 'row between top' },
          h('strong', {}, memory.title ? `${memory.title}:${memory.statement}` : memory.statement),
          h('span', { class: 'row tight' },
            memory.note ? h('span', { class: 'badge warn' }, t('助手转述')) : null,
            memory.status === 'expired'
              ? h('span', { class: 'badge warn' }, t('已失效 · {0} 天后清除', daysLeft(memory)))
              : statusBadge(memory))),
        memory.first_quote ? h('span', { class: 'small muted clamp' }, t('「{0}」', memory.first_quote)) : null,
        h('span', { class: 'tiny muted' }, t('{0} · {1} · {2}{3} · {4} 段原话', new Date(memory.created_at * 1000).toLocaleDateString(LOCALE), memory.device, memory.agent, memory.surface ? `(${memory.surface})` : '', memory.quotes) +
          (memory.project ? t(' · 项目「{0}」', memory.project) : '') +
          (memory.restated ? t(' · 别的对话里又说过 {0} 次', memory.restated) : '') +
          (memory.status === 'folded' ? t(' · 已并进 #{0}', memory.folded_into) : '') +
          (memory.recall_count ? t(' · 被召回 {0} 次', memory.recall_count) : '') +
          (verdictText(memory.returns) ? ` · ${verdictText(memory.returns)}` : ''))))
      : h('p', { class: 'empty' }, counts.active + counts.expired ? t('没有符合条件的记忆。') : t('还没有记忆。提炼跑过之后,这里会出现带原话的记忆。')));

    const projectChip = state.memProject ? h('div', { class: 'row' },
      h('span', { class: 'badge accent' }, t('只看项目「{0}」', state.memProject)),
      h('button', { class: 'link small', type: 'button', 'data-key': 'mem-project-clear', onclick: () => { state.memProject = ''; refresh(); } }, t('看全部'))) : null;
    return [head, viewDistillStrip(), viewEvolutionStrip(), viewAsk(), shelfRow, projectChip, tools, h('div', { class: 'mem-layout' }, list, viewMemoryDetail())];
  }

  // ---- projects: what each project holds, and its whiteboard -----------------

  const TASK_TONE = { claim: 'ok', progress: 'ok', handoff: 'accent', blocked: 'warn', done: 'mute' };
  const TASK_ORDER = { handoff: 0, blocked: 1, claim: 2, progress: 2, done: 3 };
  const KIND_SHELF = { preference: t('知意'), correction: t('知意'), decision: t('行策'), lesson: t('行策'), fact: t('工具书'), experience: t('经验') };

  function openProjectMemories(name) {
    state.memProject = name;
    state.memShelf = '';
    state.memFilter = '';
    location.hash = '#/memory';
  }

  function openMemory(id) {
    state.memProject = '';
    state.memSelected = id;
    state.memJump = id;
    location.hash = '#/memory';
  }

  function viewTask(task) {
    const latest = task.latest;
    const who = [latest.role, latest.agent].filter(Boolean).join('/');
    return h('li', { class: 'task' },
      h('details', { 'data-key': `task-${task.id}` },
        h('summary', {},
          h('span', { class: 'row tight' },
            h('span', { class: 'mono tiny muted' }, task.id),
            h('strong', {}, task.title),
            h('span', { class: `badge ${TASK_TONE[task.kind] || 'mute'}` }, tx(task.state) + (task.kind === 'handoff' && latest.next_owner ? ` → ${latest.next_owner}` : '')),
            task.stale ? h('span', { class: 'badge mute' }, t('两周没动静')) : null),
          h('span', { class: 'small muted' }, `${who} · ${relTime(task.updated_at)}` + (latest.summary ? `:${latest.summary}` : ''))),
        h('ol', { class: 'thread' }, task.records.map((record) => h('li', {},
          h('span', { class: 'tiny muted' }, `${new Date(record.created_at * 1000).toLocaleString(LOCALE)} · ${[record.role, record.agent].filter(Boolean).join('/')} · ${tx(record.state)}`
            + (record.next_owner ? ` → ${record.next_owner}` : '') + (record.collision_with ? t(' · 和别人撞单了') : '')),
          record.summary ? h('span', { class: 'small' }, record.summary) : null,
          record.memory_ids.length ? h('span', { class: 'tiny muted' }, t('依据记忆 '),
            record.memory_ids.map((id) => h('button', { class: 'link tiny', type: 'button', onclick: () => openMemory(id) }, `#${id} `))) : null)))));
  }

  // ---- going on in a new window: the hand-over notes ------------------------------

  function viewNotes() {
    const n = state.notes;
    if (!n) return null;
    const turn = async () => {
      try { state.notes = await api('POST', '/api/v1/admin/notes/switch', { enabled: !n.enabled }); } catch (error) { state.loadError = say(error); }
      render();
    };
    return h('section', { class: 'card', 'aria-label': t('换窗口接着做') },
      h('div', { class: 'card-head' },
        h('div', { class: 'stack' }, h('h2', {}, t('换窗口接着做')),
          h('span', { class: 'small muted' }, t('在新窗口只说「继续」「下一步」「做到哪了」,agent 就会拿到这个项目上次做到哪:最后几句原话、白板在飞的活、最近定下的事。'))),
        h('button', { class: 'btn', type: 'button', 'data-key': 'notes-switch', onclick: turn }, n.enabled ? t('关掉自动小结') : t('打开自动小结'))),
      h('p', { class: 'small muted' }, !n.enabled
        ? t('自动小结关着。「继续」照样能接上,只是没有整理好的目标、已完成、还剩、下一步。')
        : n.model ? t('一段对话安静 20 分钟后,用日常提炼的模型写一条小结(目标、已完成、还剩、卡在哪、下一步),每一行都逐字引原话,对不上的不留。')
          : t('还没给「日常提炼」选模型,所以不写小结;「继续」照样能接上。')),
      n.notes.length ? h('ul', { class: 'list' }, n.notes.map((note) => h('li', { class: 'task' }, h('details', { 'data-key': `note-${note.id}` },
        h('summary', {}, h('strong', {}, note.project || note.folder || t('没有文件夹')),
          h('span', { class: 'small muted' }, ` · ${[note.device, note.agent + (note.surface ? `(${note.surface})` : ''), relTime(note.at)].join(' · ')}`)),
        h('div', { class: 'stack gap' }, note.lines.length ? note.lines.map((line) => h('div', { class: 'stack' },
          h('span', { class: 'small' }, h('strong', {}, `${tx(line.label)} `), line.text), h('span', { class: 'tiny muted' }, t('「{0}」', line.quote))))
          : h('span', { class: 'small muted' }, t('这段对话里没有能逐字引出来的目标或下一步。')),
        h('div', { class: 'row' }, h('span', { class: 'tiny muted' }, note.model),
          h('button', { class: 'link tiny', type: 'button', 'data-key': `note-del-${note.id}`, onclick: async () => {
            try { state.notes = await api('POST', `/api/v1/admin/notes/${note.id}/delete`, {}); } catch (error) { state.loadError = say(error); }
            render();
          } }, t('删掉这条小结')))))))) : null);
  }

  function viewProjects() {
    const head = pageHead(t('项目'), t('agent 在某个文件夹干活时声明它属于哪个项目,这里就按项目汇总:各 agent 留下的记忆、归纳出的经验、白板上在飞的活。哪个文件夹算哪个项目,你也可以在下面定。'));
    const p = state.projects;
    if (!p) return [head, h('div', { class: 'card' }, h('p', { class: 'muted' }, t('正在读取…')))];
    const pages = (p.pages || []).map((page) => {
      const shelves = {};
      Object.entries(page.kinds).forEach(([kind, count]) => { const shelf = KIND_SHELF[kind] || kind; shelves[shelf] = (shelves[shelf] || 0) + count; });
      const open = page.whiteboard.filter((task) => task.kind !== 'done');
      return h('section', { class: 'card', 'aria-label': page.project },
        h('div', { class: 'card-head' },
          h('div', { class: 'stack' },
            h('h2', {}, page.project),
            h('span', { class: 'small muted' }, (page.series ? t('属于 {0} · ', page.series) : '') + t('{0} 条记忆', num(page.memories)) +
              (Object.keys(shelves).length ? ` · ${[t('知意'), t('行策'), t('工具书'), t('经验')].filter((name) => shelves[name]).map((name) => `${name} ${num(shelves[name])}`).join(' · ')}` : ''))),
          h('button', { class: 'btn', type: 'button', onclick: () => openProjectMemories(page.project) }, t('看这个项目的记忆'))),
        Object.keys(page.lanes).length ? h('div', { class: 'chips', 'aria-label': t('各 agent 的记忆') },
          Object.entries(page.lanes).sort((a, b) => b[1] - a[1]).map(([agent, count]) => h('span', { class: 'badge mute' }, `${agent} ${num(count)}`))) : null,
        h('div', { class: 'stack gap' },
          h('h3', { class: 'label' }, t('白板{0}', open.length ? t(' · 在飞 {0} 件', open.length) : '')),
          page.whiteboard.length
            ? h('ul', { class: 'list tasks' }, page.whiteboard.slice()
              .sort((a, b) => (TASK_ORDER[a.kind] - TASK_ORDER[b.kind]) || (b.updated_at - a.updated_at)).map(viewTask))
            : h('span', { class: 'tiny muted' }, t('agent 在这个项目里开工、交接时会写上白板;新窗口开局就能看到谁在做什么、交给了谁。现在还空着。'))),
        page.experiences.length ? h('div', { class: 'stack gap' },
          h('h3', { class: 'label' }, t('经验')),
          h('ul', { class: 'list' }, page.experiences.map((card) => h('li', {},
            h('button', { class: 'link', type: 'button', onclick: () => openMemory(card.id) }, card.title))))) : null,
        h('div', { class: 'stack gap' },
          h('h3', { class: 'label' }, t('声明的文件夹')),
          h('ul', { class: 'list' }, page.folders.map((folder) => h('li', {},
            h('span', { class: 'grow mono small' }, `${folder.device} · ${folder.folder}`),
            h('span', { class: 'tiny muted' }, t('{0} 声明 · {1}', folder.declared_by || 'agent', relTime(folder.declared_at))),
            h('button', {
              class: 'link tiny', type: 'button', 'data-key': `unplace-${folder.device_id}-${folder.folder}`,
              onclick: () => ask(t('把这个文件夹移出「{0}」?', page.project), t('{0} 里的对话和记忆都还在,只是不再算这个项目的。', folder.folder), t('移出'),
                () => api('POST', '/api/v1/admin/projects/assign', { device_id: folder.device_id, folder: folder.folder, project: '' })),
            }, t('移出')))))));
    });
    const loose = p.undeclared_folders ? h('section', { class: 'card', 'aria-label': t('还没声明的文件夹') },
      h('h2', {}, t('还没声明的文件夹')),
      h('p', { class: 'small muted' }, t('共 {0} 个文件夹、{1} 条记忆还不属于任何项目。归到项目后,在这个项目里干活的 agent 会先想起它们。同一个项目在几台电脑、几个文件夹里,就填同一个名字。agent 在这些文件夹里开窗口时也会自己声明,你不填也行。', num(p.undeclared_folders), num(p.undeclared_memories))),
      h('datalist', { id: 'project-names' }, (p.pages || []).map((page) => h('option', { value: page.project }))),
      h('ul', { class: 'list' }, p.undeclared.map((item) => {
        const key = `${item.device_id}|${item.folder}`;
        const place = async () => {
          const name = (state.placing[key] || '').trim();
          if (!name) return;
          try {
            await api('POST', '/api/v1/admin/projects/assign', { device_id: item.device_id, folder: item.folder, project: name });
            delete state.placing[key];
            state.loadError = '';
          } catch (error) { state.loadError = say(error); }
          await refresh();
        };
        return h('li', { class: 'place-row' },
          h('span', { class: 'grow stack' }, h('span', { class: 'mono small' }, `${item.device} · ${item.folder}`),
            h('span', { class: 'tiny muted' }, t('{0} 条记忆', num(item.memories)) + (item.inside ? t(' · 含 {0} 个子文件夹', num(item.inside)) : ''))),
          h('input', {
            type: 'text', class: 'place-input', list: 'project-names', value: state.placing[key] || '', placeholder: t('项目名'), 'aria-label': t('{0} 属于哪个项目', item.folder),
            autocomplete: 'off', 'data-key': `place-${key}`,
            oninput: (event) => { state.placing[key] = event.target.value; },
            onkeydown: (event) => { if (event.key === 'Enter') place(); },
          }),
          h('button', { class: 'btn', type: 'button', 'data-key': `place-go-${key}`, onclick: place }, t('归进去')));
      }))) : null;
    return [head, ...(pages.length ? pages : [h('div', { class: 'card' }, h('p', { class: 'empty' }, t('还没有 agent 声明过项目。')))]), loose, viewNotes()];
  }

  // ---- import: history brought in after the fact ---------------------------

  function tokensText(value) {
    const n = Number(value || 0);
    if (LANG === 'en') {
      if (n >= 1000000) return `${(n / 1000000).toFixed(n >= 100000000 ? 0 : 1)} M`;
      if (n >= 10000) return `${(n / 1000).toFixed(0)} K`;
      return num(n);
    }
    if (n >= 100000000) return t('{0} 亿', (n / 100000000).toFixed(1));
    if (n >= 10000) return t('{0} 万', (n / 10000).toFixed(n >= 1000000 ? 0 : 1));
    return num(n);
  }

  function durationText(total) {
    const s = Math.max(0, Math.round(total || 0));
    if (s < 3600) return t('{0} 分钟', Math.max(1, Math.round(s / 60)));
    const hours = Math.floor(s / 3600);
    if (hours >= 48) return t('{0} 天', Math.round(hours / 24));
    const minutes = Math.round((s % 3600) / 60);
    return minutes ? t('{0} 小时 {1} 分', hours, minutes) : t('{0} 小时', hours);
  }

  const IMPORT_STATUS = {
    done: [t('完成'), 'ok'],
    paused: [t('你暂停了'), 'mute'],
    yielded: [t('给每晚提炼让路,之后自动继续'), 'accent'],
    interrupted: [t('服务端重启打断,会自动继续'), 'accent'],
    stopped: [t('停下了'), 'warn'],
    running: [t('进行中'), 'accent'],
  };

  async function startImport() {
    state.distillNote = '';
    try {
      const body = { job: 'import' };
      if (state.scopeDraft) body.scope = state.scopeDraft;
      await api('POST', '/api/v1/admin/distill/run', body);
      state.scopeDraft = null;
      state.scopePreview = null;
    } catch (error) {
      state.distillNote = say(error);
    }
    await refresh();
  }

  // ---- the range of history to organise ----------------------------------

  const MONTH_CHOICES = [[0, t('全部')], [1, t('最近 1 个月')], [3, t('最近 3 个月')], [6, t('最近半年')], [12, t('最近一年')]];
  let previewTimer = null;

  function currentScope(held) {
    return state.scopeDraft || held.scope;
  }

  function changeScope(held, change) {
    const next = Object.assign({}, currentScope(held), change);
    state.scopeDraft = next;
    state.scopePreview = null;
    render();
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      try {
        state.scopePreview = await api('POST', '/api/v1/admin/distill/import-scope/preview', { scope: next });
      } catch (error) {
        state.distillNote = say(error);
      }
      render();
    }, 250);
  }

  function groupLabel(group) {
    if (group.project) return t('项目「{0}」', group.label);
    return group.label || t('没记下文件夹的会话');
  }

  function viewScope(held, locked) {
    const scope = currentScope(held);
    const choices = held.choices;
    const pick = (pressed, key, label, note, onclick) => h('button', {
      class: 'pick', type: 'button', 'data-key': key, 'aria-pressed': pressed ? 'true' : 'false', disabled: locked, onclick,
    }, label, note ? h('span', { class: 'pick-note' }, note) : null);

    // Agents: none ticked off means all of them.
    const agentIds = choices.agents.map((a) => a.agent_id);
    const agentOn = (id) => scope.agents === null || scope.agents.includes(id);
    const toggleAgent = (id) => {
      const on = agentIds.filter((other) => (other === id ? !agentOn(id) : agentOn(other)));
      changeScope(held, { agents: on.length === agentIds.length ? null : on });
    };

    // Projects and folders: the largest ones by name, the rest together.
    const listed = choices.groups.map((g) => g.key);
    const groupOn = (key) => scope.groups === null || scope.groups.includes(key);
    const restOn = scope.groups === null || scope.rest;
    const setGroups = (keys, rest) => {
      const all = keys.length === listed.length && (rest || !choices.rest.groups);
      changeScope(held, all ? { groups: null, rest: false, listed: [] } : { groups: keys, rest, listed });
    };
    const toggleGroup = (key) => setGroups(listed.filter((other) => (other === key ? !groupOn(key) : groupOn(other))), restOn);

    const volume = state.scopeDraft ? state.scopePreview : Object.assign({ estimate: held.estimate }, held.scoped);
    const summary = volume
      ? (volume.chars
        ? t('这个范围:{0} 个会话 · {1} 字 · 预计约 {2} token', num(volume.sessions), num(volume.chars), tokensText(volume.estimate.input_tokens + volume.estimate.output_tokens)) +
          (volume.estimate.seconds ? t(' · 约 {0}', durationText(volume.estimate.seconds)) : '')
        : t('这个范围里没有待整理的会话。'))
      : t('正在计算这个范围…');

    return h('section', { class: 'card', 'aria-label': t('整理范围') },
      h('div', { class: 'card-head' },
        h('div', { class: 'stack' },
          h('h2', {}, t('整理范围')),
          h('span', { class: 'small muted' }, locked
            ? t('正在整理。要改范围,先暂停。')
            : t('只整理挑中的部分,其余的继续存着,以后随时可以再整理。三项一起生效:比如「最近 3 个月」里「某个项目」的会话。')))),
      h('div', { class: 'stack gap' },
        h('h3', { class: 'label' }, t('时间')),
        h('div', { class: 'chips' }, MONTH_CHOICES.map(([months, label]) => {
          const found = choices.months.find((m) => m.months === months);
          return pick(scope.months === months, `scope-months-${months}`, label,
            months ? t('{0} 字', tokensText(found ? found.chars : 0)) : t('{0} 字', tokensText(held.chars)),
            () => changeScope(held, { months }));
        }))),
      choices.agents.length > 1 ? h('div', { class: 'stack gap' },
        h('h3', { class: 'label' }, 'agent'),
        h('div', { class: 'chips' }, choices.agents.map((agent) =>
          pick(agentOn(agent.agent_id), `scope-agent-${agent.agent_id}`, `${agent.device} · ${agent.agent}`, t('{0} 字', tokensText(agent.chars)),
            () => toggleAgent(agent.agent_id))))) : null,
      choices.groups.length > 1 ? h('div', { class: 'stack gap' },
        h('div', { class: 'row between' },
          h('h3', { class: 'label' }, t('项目和文件夹')),
          locked ? null : h('span', { class: 'row tight' },
            h('button', { class: 'link small', type: 'button', 'data-key': 'scope-groups-all', onclick: () => setGroups(listed, true) }, t('全选')),
            h('button', { class: 'link small', type: 'button', 'data-key': 'scope-groups-none', onclick: () => setGroups([], false) }, t('全不选')))),
        h('div', { class: 'chips' },
          choices.groups.map((group) => pick(groupOn(group.key), `scope-group-${group.key}`, groupLabel(group), t('{0} 字', tokensText(group.chars)),
            () => toggleGroup(group.key))),
          choices.rest.groups ? pick(restOn, 'scope-group-rest', t('其余 {0} 个文件夹', choices.rest.groups), t('{0} 字', tokensText(choices.rest.chars)),
            () => setGroups(listed.filter(groupOn), !restOn)) : null),
        h('span', { class: 'tiny muted' }, t('声明过项目的文件夹按项目名列出(含子文件夹);没声明的按会话当时所在的文件夹。'))) : null,
      h('div', { class: 'row between' },
        h('strong', { class: 'small' }, summary),
        state.scopeDraft && !locked ? h('button', { class: 'link small', type: 'button', 'data-key': 'scope-reset',
          onclick: () => { state.scopeDraft = null; state.scopePreview = null; render(); } }, t('还原')) : null));
  }

  async function pauseImport() {
    state.distillNote = '';
    try {
      await api('POST', '/api/v1/admin/distill/pause', { job: 'import' });
    } catch (error) {
      state.distillNote = say(error);
    }
    await refresh();
  }

  function viewImport() {
    const head = pageHead(t('导入'), t('装客户端之前就有的历史会话。传上来后先存着,每晚的提炼不会碰它;你决定什么时候整理、用哪个模型。'));
    const d = state.distill;
    if (!d) return [head, h('div', { class: 'card' }, h('p', { class: 'muted' }, t('正在读取…')))];
    const held = d.held;
    if (!held.total_segments) {
      return [head, h('section', { class: 'card' },
        h('h2', {}, t('还没有导入过历史')),
        h('p', { class: 'small muted' }, t('历史由各台电脑上的客户端上传:agent 说明旧会话放在哪,客户端照常去掉工具调用等运行过程、给密钥打码,再传上来。同一段对话只存一份,重复传也没关系。')))];
    }

    const lives = d.lives || {};
    const live = lives.import || null;
    const importing = Boolean(live);
    const last = held.runs[0];
    const doneChars = Math.max(0, held.total_chars - held.chars);
    const share = held.total_chars ? Math.floor((doneChars / held.total_chars) * 100) : 0;

    const volume = h('section', { class: 'card' },
      h('div', { class: 'card-head' },
        h('div', { class: 'stack' },
          h('h2', { class: 'stat-label' }, t('待整理')),
          h('span', { class: 'stat-value' }, held.chars ? t('{0} 字', num(held.chars)) : t('没有了')),
          h('span', { class: 'small muted' }, held.chars ? t('{0} 个会话 · {1} 段对话', num(held.sessions), num(held.segments)) : t('导入的历史都整理过了'))),
        importing ? h('span', { class: 'badge accent' }, t('正在整理')) : null),
      h('div', { class: 'stack' },
        h('div', { class: 'row between' },
          h('span', { class: 'small' }, t('已整理 {0}%', share)),
          h('span', { class: 'small muted' }, t('共导入 {0} 字', num(held.total_chars)))),
        h('div', { class: 'bar', role: 'progressbar', 'aria-label': t('历史整理进度'), 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(share) },
          h('span', { width: `${share}%` }))),
      held.agents.length ? h('ul', { class: 'list' }, held.agents.map((item) => h('li', {},
        h('span', { class: 'grow' }, `${item.device} · ${item.agent}`),
        h('span', { class: 'muted' }, t('{0} 个会话 · {1} 字', num(item.sessions), num(item.chars)))))) : null);

    const scoped = state.scopeDraft ? state.scopePreview : Object.assign({ estimate: held.estimate }, held.scoped);
    const estimate = (scoped && scoped.estimate) || held.estimate;
    const plan = h('section', { class: 'card' },
      h('h2', { class: 'stat-label' }, held.scope.months || held.scope.agents || held.scope.groups || state.scopeDraft ? t('整理范围内的,预计') : t('整理剩下的,预计')),
      h('span', { class: 'stat-value' }, t('约 {0} token', tokensText(estimate.input_tokens + estimate.output_tokens))),
      h('span', { class: 'small muted' }, t('读入约 {0} · 写出约 {1}', tokensText(estimate.input_tokens), tokensText(estimate.output_tokens)) +
        (estimate.seconds ? t(' · 约 {0}', durationText(estimate.seconds)) : '')),
      h('span', { class: 'tiny muted' }, estimate.measured
        ? t('按已经跑过的整理的实际用量和速度估算。')
        : t('粗估。跑过一阵后,会按实际用量和速度重新估算。')),
      h('div', { class: 'row' },
        h('span', { class: 'small' }, t('模型:')),
        held.model
          ? h('span', { class: 'small' }, h('strong', {}, held.model), h('span', { class: 'muted' }, t('(「历史导入」槽)')))
          : h('a', { class: 'small', href: '#/models' }, t('还没给「历史导入」选模型,去「模型」页选'))));

    let control;
    if (importing) {
      control = h('div', { class: 'card-head' },
        h('div', { class: 'stack' },
          h('strong', {}, live.pausing ? t('正在暂停…') : t('正在整理')),
          h('span', { class: 'small muted' }, live.pausing
            ? t('等手上这一段做完就停,做完的部分会保存。')
            : t('这一轮已读 {0} 段({1} 字),新增 {2} 条记忆', num(live.segments), num(live.chars), num(live.memories)))),
        h('button', { class: 'btn', type: 'button', disabled: live.pausing, onclick: pauseImport }, t('暂停')));
    } else {
      const resumed = last && ['paused', 'yielded', 'interrupted', 'stopped'].includes(last.status) && held.chars;
      const canStart = Boolean(scoped && scoped.chars > 0) && Boolean(held.model) && !live;
      const note = !held.model ? t('先给「历史导入」选一个模型。')
          : last && last.status === 'stopped' ? t('上一轮停下了:{0}。进度没丢,每 30 分钟自动再试一次。', RUN_REASONS[last.error_reason] || t('出错'))
            : last && ['yielded', 'interrupted'].includes(last.status) ? t('会自动接着整理。')
              : resumed ? t('上次你暂停了。继续会从断点接着整理,做过的不会重做。')
              : t('开始后可以随时暂停,进度不会丢;同一段不会整理两次。');
      control = h('div', { class: 'card-head' },
        h('div', { class: 'stack' },
          h('strong', {}, held.chars ? (resumed ? t('从上次停下的地方继续') : t('开始整理')) : t('都整理完了')),
          h('span', { class: 'small muted' }, note)),
        held.chars ? h('button', {
          class: 'btn primary', type: 'button', disabled: !canStart,
          onclick: () => ask(resumed ? t('继续整理历史?') : t('开始整理历史?'),
            t('这次整理 {0} 字(共剩 {1} 字),预计约 {2} token,用 {3}。可以随时暂停。', num(scoped ? scoped.chars : 0), num(held.chars), tokensText(scoped ? scoped.estimate.input_tokens + scoped.estimate.output_tokens : 0), held.model),
            resumed ? t('继续') : t('开始'), startImport, 'primary'),
        }, resumed ? t('继续整理') : t('开始整理')) : null);
    }

    const runs = held.runs.length ? h('section', { class: 'card' },
      h('h2', {}, t('整理记录')),
      h('ul', { class: 'list' }, held.runs.map((run) => {
        const [label, tone] = IMPORT_STATUS[run.status] || [run.status, 'mute'];
        return h('li', {},
          h('span', { class: 'when' }, relTime(run.started_at)),
          h('span', { class: 'grow' }, t('读了 {0} 段({1} 字),新增 {2} 条记忆', num(run.segments), num(run.chars), num(run.memories)) +
            (run.input_tokens || run.output_tokens ? t(' · 用了 {0} token', tokensText(run.input_tokens + run.output_tokens)) : '') +
            (run.status === 'stopped' && run.error_reason ? ` · ${RUN_REASONS[run.error_reason] || run.error_reason}` : '')),
          h('span', { class: `badge ${tone}` }, label));
      }))) : null;

    return [
      head,
      h('div', { class: 'grid wide' }, volume, plan),
      held.chars ? viewScope(held, importing) : null,
      h('section', { class: 'card', 'aria-label': t('整理控制') }, control,
        state.distillNote ? h('div', { class: 'error', role: 'alert' }, state.distillNote) : null,
        h('span', { class: 'tiny muted' }, t('历史整理和每晚 {0}:00 的提炼各跑各的,可以同时进行;只有两者都用本机模型时,历史整理才先让开,之后自动接着整理。整理时同时处理 {1} 个会话(本机模型一次一个)。', String(d.nightly_hour).padStart(2, '0'), live ? live.parallel : 4))),
      runs,
    ];
  }

  // ---- confirm dialog -----------------------------------------------------

  function viewConfirm() {
    const confirm = state.confirm;
    async function run() {
      if (state.confirmBusy) return;
      state.confirmBusy = true;
      render();
      try {
        await confirm.run();
        state.loadError = '';
      } catch (error) {
        state.loadError = say(error);
      }
      state.confirm = null;
      state.confirmBusy = false;
      await refresh();
    }
    const cancel = () => { if (!state.confirmBusy) { state.confirm = null; render(); } };
    return h('div', { class: 'scrim', onclick: (event) => { if (event.target === event.currentTarget) cancel(); } },
      h('div', { class: 'dialog', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'confirm-title' },
        h('h3', { id: 'confirm-title' }, confirm.title),
        h('p', {}, confirm.body),
        h('div', { class: 'row' },
          h('button', { class: 'btn', type: 'button', onclick: cancel, id: 'confirm-cancel' }, t('取消')),
          h('button', { class: confirm.tone === 'primary' ? 'btn primary' : 'btn danger-solid', type: 'button', disabled: state.confirmBusy, onclick: run }, confirm.action))));
  }

  // ---- changing the password ----------------------------------------------------

  function viewPasswordDialog() {
    const d = state.pwDialog;
    const close = () => { if (!d.busy) { state.pwDialog = null; render(); } };
    async function save(event) {
      event.preventDefault();
      if (d.busy) return;
      if (d.next !== d.again) {
        d.error = t('两次输入的新密码不一样。');
        render();
        return;
      }
      d.busy = true;
      d.error = '';
      render();
      try {
        await api('POST', '/api/v1/admin/session/password', { old: d.old, password: d.next });
        d.done = true;
        d.old = d.next = d.again = '';
      } catch (error) {
        d.error = say(error);
      }
      d.busy = false;
      render();
    }
    const field = (id, label, key, autocomplete) => h('div', { class: 'field' },
      h('label', { for: id }, label),
      h('input', { id, type: 'password', autocomplete, required: true, value: d[key], oninput: (event) => { d[key] = event.target.value; } }));
    return h('div', { class: 'scrim', onclick: (event) => { if (event.target === event.currentTarget) close(); } },
      d.done
        ? h('div', { class: 'dialog', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'pw-title' },
          h('h3', { id: 'pw-title' }, t('密码已改好')),
          h('p', {}, t('这个浏览器保持登录;其他浏览器下次要用新密码登录。')),
          h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', id: 'pw-close', onclick: close }, t('好'))))
        : h('form', { class: 'dialog', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'pw-title', onsubmit: save },
          h('h3', { id: 'pw-title' }, t('改管理密码')),
          field('pw-old', t('现在的密码'), 'old', 'current-password'),
          field('pw-next', t('新密码(至少 8 位)'), 'next', 'new-password'),
          field('pw-again', t('再输一次'), 'again', 'new-password'),
          d.error ? h('div', { class: 'error', role: 'alert' }, d.error) : null,
          h('div', { class: 'row' },
            h('button', { class: 'btn', type: 'button', onclick: close, id: 'pw-cancel' }, t('取消')),
            h('button', { class: 'btn primary', type: 'submit', disabled: !!d.busy }, d.busy ? t('在改…') : t('改密码')))));
  }

  // ---- render loop --------------------------------------------------------

  function focusKey(element) {
    if (!element || element === document.body || !root.contains(element)) return null;
    return element.getAttribute('data-key') || element.id || `${element.tagName}|${element.getAttribute('aria-label') || element.textContent}`;
  }

  let lastRoute = null;

  function render() {
    const hadDialog = Boolean(root.querySelector('.scrim'));
    const focused = focusKey(document.activeElement);
    lastPainted = paintKey();
    // The page is rebuilt on every paint (the background poll repaints when data
    // changed): keep where the reader was, unless they went to another page.
    const samePage = lastRoute === state.route;
    lastRoute = state.route;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const scrolled = Array.from(root.querySelectorAll('[data-scroll-key]')).map((element) => [element.getAttribute('data-scroll-key'), element.scrollTop]);
    const opened = new Set(Array.from(root.querySelectorAll('details[open][data-key]')).map((element) => element.getAttribute('data-key')));
    let view;
    if (state.gate) {
      const typed = Array.from(root.querySelectorAll('.gate input')).map((input) => input.value);
      view = viewGate();
      view.querySelectorAll('input').forEach((input, index) => { input.value = typed[index] || ''; });
    } else {
      let content;
      if (state.route === 'overview') content = viewOverview();
      else if (state.route === 'devices') content = viewDevices();
      else if (state.route === 'models') content = viewModels();
      else if (state.route === 'memory') content = viewMemory();
      else if (state.route === 'projects') content = viewProjects();
      else content = viewImport();
      view = viewShell(content);
    }
    const dialog = state.gate ? '' : state.confirm ? viewConfirm() : state.pwDialog ? viewPasswordDialog() : '';
    root.replaceChildren(view, dialog);
    if (samePage) {
      root.querySelectorAll('details[data-key]').forEach((element) => { if (opened.has(element.getAttribute('data-key'))) element.open = true; });
      scrolled.forEach(([key, top]) => {
        const element = root.querySelector(`[data-scroll-key="${CSS.escape(key)}"]`);
        if (element) element.scrollTop = top;
      });
    }
    if (state.confirm && !hadDialog) {
      const cancel = document.getElementById('confirm-cancel');
      if (cancel) cancel.focus();
    } else if (state.pwDialog && !hadDialog) {
      const first = document.getElementById('pw-old');
      if (first) first.focus();
    } else if (focused && !state.gate) {
      // The page is rebuilt on every paint: put the keyboard focus back where it was.
      const again = Array.from(root.querySelectorAll('button, a, input, select')).filter((element) => focusKey(element) === focused);
      if (again.length === 1) {
        // Without preventScroll the browser scrolls the page to the focused element (often the nav at the top).
        again[0].focus({ preventScroll: true });
        // A rebuilt text box would put the caret at the start: keep typing at the end.
        if (again[0].tagName === 'INPUT' && ['text', 'search', 'password'].includes(again[0].type)) {
          const end = again[0].value.length;
          try { again[0].setSelectionRange(end, end); } catch (error) { /* not selectable */ }
        }
      }
    }
    if (samePage) window.scrollTo(scrollX, scrollY);
  }

  function readRoute() {
    const id = location.hash.replace(/^#\/?/, '');
    state.route = PAGES.some(([page]) => page === id) ? id : 'overview';
  }

  window.addEventListener('hashchange', () => { readRoute(); render(); refresh(); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.confirm && !state.confirmBusy) { state.confirm = null; render(); }
  });
  setInterval(() => { if (!document.hidden && !state.confirm) refresh(true); }, REFRESH_MS);

  (async () => {
    readRoute();
    await loadSession();
    render();
    await refresh();
  })();
})();
