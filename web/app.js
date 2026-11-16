'use strict';

(() => {
  const $ = id => document.getElementById(id);
  const officialUrl = 'https://www.smartplay.lcsd.gov.hk/website/tc/';
  const defaultWatchVenues = ['BRTC', 'HKTC'];
  const dayLabels = ['一', '二', '三', '四', '五', '六', '日'];
  const hkDate = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Hong_Kong', year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });
  const hkClock = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Hong_Kong', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const shortDate = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Hong_Kong', month: 'numeric', day: 'numeric', weekday: 'short' });
  const fullTimestamp = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Hong_Kong', month: '2-digit', day: '2-digit', hour12: false, hour: '2-digit', minute: '2-digit' });
  let state = null;
  let clockOffset = 0;
  let configured = false;
  let configDirty = false;
  let watchDirty = false;
  let saving = false;
  let stateRequest = 0;
  let loading = false;
  let chosenCandidate = null;
  let seenAlerts = null;
  let venueOrder = [];
  let toastTimer = null;
  let watchConfigSignature = null;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function validDate(value) { if (value === undefined || value === null || value === '') return null; const date = new Date(value); return Number.isFinite(date.getTime()) ? date : null; }
  function dateOnly(value) { return validDate(`${value}T12:00:00+08:00`); }
  function safeText(value) { return typeof value === 'string' ? value : String(value ?? ''); }
  function asMessage(value) { return typeof value === 'string' ? value : (value && typeof value.message === 'string' ? value.message : '操作未完成，请稍后重试。'); }
  function toast(message, error = false) {
    clearTimeout(toastTimer);
    $('toast').textContent = message;
    $('toast').classList.toggle('error', error);
    $('toast').hidden = false;
    toastTimer = setTimeout(() => { $('toast').hidden = true; }, error ? 7000 : 4000);
  }
  async function api(path, options = {}) {
    const headers = { Accept: 'application/json', ...options.headers };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = state?.csrf_token || '';
    const response = await fetch(path, { ...options, headers, credentials: 'same-origin', cache: 'no-store' });
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch { throw new Error('本地服务返回了无法识别的内容。'); }
    if (!response.ok) throw new Error(asMessage(data.error || data.message || `请求失败 (${response.status})`));
    return data;
  }
  async function mutate(path, body, method = 'POST') {
    if (!state?.csrf_token) throw new Error('本地连接尚未就绪，请稍后重试。');
    return api(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
  }
  function sourceAge(value) {
    const date = validDate(value);
    if (!date) return '尚未获取';
    const minutes = Math.max(0, Math.floor((Date.now() + clockOffset - date.getTime()) / 60000));
    return minutes < 1 ? '刚刚获取' : `${minutes} 分钟前获取`;
  }
  function renderFeed() {
    if (!state) return;
    const feed = state.feed || {};
    const demo = state.mode === 'demo' || feed.status === 'demo';
    const labels = { live: '官方开放数据 · 非实时锁场', imported: '手动导入快照 · 非自动更新', stale: '旧数据 · 请先刷新并在官方复核', unavailable: '官方数据暂不可用', demo: '演示模式 · 合成时段' };
    $('source-label').textContent = demo ? labels.demo : (labels[feed.status] || '等待获取官方数据');
    $('source-dot').className = `status-dot ${demo || feed.status === 'imported' ? 'demo' : feed.status === 'live' ? 'live' : 'error'}`;
    const parts = [];
    if (!demo && feed.fetched_at) parts.push(`${sourceAge(feed.fetched_at)} (${fullTimestamp.format(validDate(feed.fetched_at))} HKT)`);
    if (!demo && feed.source_updated_at && validDate(feed.source_updated_at)) parts.push(`来源更新时间 ${fullTimestamp.format(validDate(feed.source_updated_at))}`);
    if (demo) parts.push('下方场次为合成示例。空位监测的开关独立设置。');
    else if (feed.status === 'imported') parts.push('手动快照不会自行更新；请重新下载导入以获取新空位。');
    else if (feed.error) parts.push(`获取失败：${safeText(feed.error)}`);
    else parts.push('每五分钟更新；官方付款完成后才确认预订。');
    if (!demo && Number.isFinite(feed.row_count)) parts.push(`原始记录 ${feed.row_count} 条`);
    $('source-detail').textContent = parts.join(' · ');
    $('demo-notice').hidden = !demo;
    $('mode-button').textContent = demo ? '切换官方数据' : '进入演示';
    const retry = validDate(feed.next_retry_at);
    const wait = retry ? Math.ceil((retry.getTime() - Date.now() - clockOffset) / 1000) : 0;
    $('refresh-button').disabled = loading || (wait > 0 && !demo);
    $('refresh-button').textContent = loading ? '正在刷新…' : wait > 0 && !demo ? `${Math.floor(wait / 60)}:${String(wait % 60).padStart(2, '0')} 后可刷新` : '刷新数据';
  }
  function countdown(value) {
    const date = validDate(value);
    if (!date) return '等待时间表';
    const seconds = Math.floor((date.getTime() - Date.now() - clockOffset) / 1000);
    if (seconds <= 0) return '已到开放时间';
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor(seconds % 86400 / 3600);
    const minutes = Math.floor(seconds % 3600 / 60);
    return `还有 ${days ? `${days}天 ` : ''}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  }
  function tick() {
    const now = new Date(Date.now() + clockOffset);
    $('hk-clock').textContent = hkClock.format(now);
    $('hk-date').textContent = hkDate.format(now);
    if (!state) return;
    $('app-countdown').textContent = countdown(state.release?.app_at);
    $('web-countdown').textContent = countdown(state.release?.web_at);
    renderFeed();
  }
  function renderRelease() {
    const release = state.release || {};
    const appAt = validDate(release.app_at);
    const webAt = validDate(release.web_at);
    $('app-release-date').textContent = appAt ? `${shortDate.format(appAt)} · 请在官方 App 操作` : '等待本地时间表';
    $('web-release-date').textContent = webAt ? `${shortDate.format(webAt)} · 官方网页可开始预订` : '等待本地时间表';
    const newPlay = dateOnly(release.new_play_date);
    $('new-play-date').textContent = newPlay ? shortDate.format(newPlay) : '—';
  }
  function venueNotes(venue) { return Array.isArray(venue.notes) ? venue.notes.join('；') : safeText(venue.notes); }
  function renderVenues() {
    const selected = new Set([...document.querySelectorAll('.venue-checkbox:checked')].map(input => input.value));
    const initial = !configured;
    const active = initial ? new Set(state.config.venue_ids || []) : selected;
    const venues = new Map((state.venues || []).map(venue => [venue.id, venue]));
    venueOrder = [...venueOrder.filter(id => venues.has(id)), ...[...venues.keys()].filter(id => !venueOrder.includes(id))];
    const container = $('venue-options');
    container.replaceChildren();
    venueOrder.forEach((id, index) => {
      const venue = venues.get(id);
      const row = el('div', 'venue-row');
      const label = el('label', 'venue-choice');
      const checkbox = el('input', 'venue-checkbox'); checkbox.type = 'checkbox'; checkbox.value = id; checkbox.checked = active.has(id);
      const name = el('span'); name.append(el('strong', '', venue.name || id), el('small', '', `${venue.district || '分区待核'} · 优先 ${index + 1}`));
      label.append(checkbox, name); label.title = venueNotes(venue);
      const controls = el('div', 'order-buttons');
      [-1, 1].forEach(direction => {
        const button = el('button', '', direction === -1 ? '↑' : '↓'); button.type = 'button'; button.disabled = index + direction < 0 || index + direction >= venueOrder.length; button.setAttribute('aria-label', `${venue.name || id}${direction === -1 ? '提高' : '降低'}优先级`);
        button.addEventListener('click', () => { [venueOrder[index], venueOrder[index + direction]] = [venueOrder[index + direction], venueOrder[index]]; configDirty = true; renderVenues(); });
        controls.append(button);
      });
      row.append(label, controls); container.append(row);
    });
  }
  function renderConfig() {
    if (configured && configDirty) return;
    const config = state.config || {};
    venueOrder = [...(config.venue_priority || config.venue_ids || [])];
    configured = false;
    renderVenues();
    $('start-time').value = config.start_time || '06:00'; $('end-time').value = config.end_time || '23:00';
    $('duration').value = String(config.duration_hours || 2); $('play-type').value = config.play_type || 'singles';
    $('fallback').checked = config.allow_one_hour_fallback !== false; $('budget').value = config.max_hourly_hkd || 0;
    const days = new Set(config.weekdays || [0, 1, 2, 3, 4, 5, 6]);
    $('weekday-options').replaceChildren();
    dayLabels.forEach((day, index) => { const label = el('label'); const input = el('input'); input.type = 'checkbox'; input.value = index; input.checked = days.has(index); input.setAttribute('aria-label', `星期${day}`); label.append(input, el('span', '', day)); $('weekday-options').append(label); });
    configured = true;
  }

  function renderWatchConfig() {
    if (watchDirty) return;
    const venueIds = state.config?.watch_venue_ids ?? defaultWatchVenues;
    const enabled = !!state.config?.monitor_enabled;
    const venues = state.venues ?? [];
    const signature = JSON.stringify([venueIds, enabled, venues.map(venue => venue.id)]);
    if (signature === watchConfigSignature) return;
    watchConfigSignature = signature;
    const selected = new Set(venueIds);
    const container = $('watch-venues');
    container.replaceChildren();
    for (const venue of venues) {
      const label = el('label', 'watch-venue');
      const input = el('input', 'watch-venue-checkbox');
      input.type = 'checkbox';
      input.value = venue.id;
      input.checked = selected.has(venue.id);
      label.append(input, el('span', '', venue.name || venue.id));
      container.append(label);
    }
    $('monitor-enabled').checked = enabled;
  }

  function renderWatchStatus() {
    const { config = {}, monitor = {}, feed = {} } = state;
    const selected = monitor.venue_ids ?? config.watch_venue_ids ?? defaultWatchVenues;
    const covered = monitor.covered_venue_ids;
    const status = $('watch-status');
    let label = '等待官方数据';
    let active = false;
    if (!config.monitor_enabled) label = '已暂停';
    else if (!selected.length) label = '未选择场地';
    else if (state.mode === 'demo') label = '演示模式';
    else if (monitor.ready && feed.status === 'live') {
      label = '监测中';
      active = true;
    } else if (feed.error) {
      label = '暂未取得可用数据';
    }
    if (status.textContent !== label) status.textContent = label;
    status.classList.toggle('active', active);
    const checkedAt = validDate(monitor.last_checked_at);
    const dataAt = validDate(feed.source_updated_at);
    $('watch-checked-at').textContent = checkedAt ? `${fullTimestamp.format(checkedAt)} HKT` : '尚未成功检查';
    $('watch-data-at').textContent = dataAt ? `${fullTimestamp.format(dataAt)} HKT` : '未提供';
    $('watch-slot-count').textContent = active && Number.isInteger(monitor.available_slots) ? `${monitor.available_slots} 个一小时时段` : '—';
    const coverage = $('watch-coverage');
    const partial = active && Array.isArray(covered) && covered.length < selected.length;
    coverage.hidden = !partial;
    if (partial) {
      const missing = (state.venues ?? []).filter(venue => selected.includes(venue.id) && !covered.includes(venue.id));
      coverage.textContent = `本次数据未覆盖：${missing.map(venue => venue.name).join('、')}。`;
    }
    const nativeStatus = $('watch-native-status');
    nativeStatus.hidden = monitor.native_delivery !== 'windows';
    nativeStatus.textContent = monitor.native_delivery === 'windows' ? '已配置 Windows 提醒。请在 Windows 通知设置内允许通知。' : '';
  }
  function renderDateFilter() {
    const current = $('date-filter').value;
    const values = [...new Set((state.candidates || []).map(candidate => candidate.date))].sort();
    $('date-filter').replaceChildren(el('option', '', '全部日期'));
    $('date-filter').firstElementChild.value = '';
    values.forEach(value => { const option = el('option', '', dateOnly(value) ? shortDate.format(dateOnly(value)) : value); option.value = value; $('date-filter').append(option); });
    if (values.includes(current)) $('date-filter').value = current;
  }
  function canRecord() { return state?.mode !== 'demo' && ['live', 'imported', 'stale'].includes(state?.feed?.status); }
  function candidateText(candidate) { return `${candidate.venue_name} · ${candidate.date} ${candidate.start}–${candidate.end} · ${candidate.duration_hours} 小时`; }
  async function copyPlan(candidate) {
    const text = `${candidateText(candidate)}\n数据只供参考；${candidate.continuity === 'verified' ? '同场连续性来自数据，仍请在官方复核' : '同一片场地的连续性须在官方复核'}。\n${officialUrl}`;
    try { await navigator.clipboard.writeText(text); toast('场次资料已复制。'); } catch { toast('无法访问剪贴板，请手动复制场次资料。', true); }
  }
  function openRecord(candidate) {
    if (!canRecord()) { toast('请切换至可用的官方数据，并先在官方完成付款。', true); return; }
    chosenCandidate = candidate;
    $('record-form').reset(); $('record-candidate').textContent = candidateText(candidate);
    $('record-amount').value = Number.isFinite(candidate.estimated_cost_hkd) ? candidate.estimated_cost_hkd : '';
    $('record-dialog').showModal();
  }
  function renderCandidates() {
    const candidates = state.candidates || [];
    const filter = $('date-filter').value;
    const filtered = filter ? candidates.filter(candidate => candidate.date === filter) : candidates;
    $('candidate-count').textContent = filtered.length;
    const container = $('candidates'); container.replaceChildren();
    if (!filtered.length) {
      const empty = el('div', 'empty-state'); empty.append(el('div', 'empty-ball', '○'));
      const unavailable = state.feed?.status === 'unavailable' || !state.feed?.status;
      empty.append(el('h3', '', unavailable ? '等待可用的官方数据' : '当前没有匹配的场次'), el('p', '', unavailable ? '当前接口尚未读取成功。可稍后刷新、手动导入官方 JSON，或进入演示体验排场。' : '可以调整场地、日期及时间范围。空位可能随其他用户的预订变化，请以官方页面为准。'));
      container.append(empty); return;
    }
    filtered.forEach((candidate, index) => {
      const card = el('article', 'candidate-card');
      const body = el('div', 'candidate-body'); const tile = el('div', 'date-tile');
      const day = dateOnly(candidate.date); const dateParts = safeText(candidate.date).split('-');
      tile.append(el('span', 'month', `${Number(dateParts[1]) || '—'} 月`), el('span', 'day', String(Number(dateParts[2]) || '—')), el('span', 'weekday', day ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Hong_Kong', weekday: 'short' }).format(day) : '—'));
      const content = el('div', 'candidate-content'); const heading = el('div', 'candidate-title');
      heading.append(el('h3', '', candidate.venue_name || candidate.venue_id), el('span', 'rank-tag', `${index + 1}`));
      const time = el('div', 'candidate-time', `${candidate.start} — ${candidate.end}`); time.append(el('small', '', `${candidate.duration_hours} 小时`));
      const meta = el('div', 'candidate-meta');
      const venue = (state.venues || []).find(item => item.id === candidate.venue_id);
      meta.append(el('span', '', venue?.district || '分区待核'), el('span', '', `${candidate.available_courts ?? '—'} 片空场（各时段下限）`), el('span', '', Number.isFinite(candidate.estimated_cost_hkd) ? `约 HK$${candidate.estimated_cost_hkd} / 总额` : '费用以官方付款页为准'));
      const verified = ['verified', 'verified_from_feed'].includes(candidate.continuity);
      content.append(heading, time, meta, el('span', verified ? 'continuity verified' : 'continuity', verified ? '数据可验证同场连续 · 官方仍须复核' : '同一片球场连续性待官方复核'));
      if (candidate.warning) content.append(el('p', 'candidate-warning', Array.isArray(candidate.warning) ? candidate.warning.join('；') : candidate.warning));
      body.append(tile, content);
      const footer = el('div', 'candidate-footer'); footer.append(el('span', '', state.mode === 'demo' ? '合成场次 · 不可订场' : '仅为排场建议，尚未锁场'));
      const actions = el('div', 'candidate-actions');
      const copy = el('button', 'button ghost', '复制场次'); copy.type = 'button'; copy.addEventListener('click', () => copyPlan(candidate));
      const official = el('a', 'button subtle', '去官方选场 ↗'); official.href = officialUrl; official.target = '_blank'; official.rel = 'noopener noreferrer';
      const record = el('button', 'button ghost', '已付款后录入'); record.type = 'button'; record.disabled = !canRecord(); record.title = canRecord() ? '仅按本人已付款收据登记；不证明旧空位仍可订。' : '演示数据不能录入真实预订。'; record.addEventListener('click', () => openRecord(candidate));
      actions.append(copy, official, record); footer.append(actions); card.append(body, footer); container.append(card);
    });
  }
  function renderWarnings() {
    $('warnings').replaceChildren();
    (state.warnings || []).forEach(warning => $('warnings').append(el('div', 'warning-item', asMessage(warning))));
  }
  function renderBookings() {
    $('bookings').replaceChildren();
    const bookings = state.bookings || [];
    if (!bookings.length) { $('bookings').append(el('p', 'muted-text', '还没有录入已付款记录。')); return; }
    bookings.forEach(booking => {
      const venue = (state.venues || []).find(item => item.id === booking.venue_id);
      const row = el('div', 'booking-row'); const details = el('div');
      details.append(el('h3', '', booking.venue_name || venue?.name || booking.venue_id || '场地'), el('p', '', `${booking.date} ${booking.start}–${booking.end} · 本人录入已付款`), el('p', '', `编号 ${booking.reference || '—'}${Number.isFinite(booking.amount_hkd) ? ` · HK$${booking.amount_hkd}` : ''}`));
      const remove = el('button', 'delete-button', '移除记录'); remove.type = 'button';
      remove.addEventListener('click', async () => {
        if (!window.confirm('仅移除助手中的行程记录，不会取消官方预订。继续移除？')) return;
        remove.disabled = true;
        try { await mutate(`/api/bookings/${encodeURIComponent(booking.id)}`, undefined, 'DELETE'); await loadState(); toast('本地记录已移除；官方预订未变更。'); } catch (error) { toast(error.message, true); } finally { remove.disabled = false; }
      });
      row.append(details, remove); $('bookings').append(row);
    });
  }
  function displayAlerts(containerId, alerts) {
    const list = $(containerId);
    list.replaceChildren();
    for (const alert of alerts.slice(0, 4)) {
      const item = el('div', 'alert-item');
      const occurred = validDate(alert.created_at ?? alert.time);
      item.append(el('strong', '', alert.title));
      if (occurred) {
        const time = el('time', 'alert-time', `${fullTimestamp.format(occurred)} HKT`);
        time.dateTime = occurred.toISOString();
        item.append(time);
      }
      item.append(el('p', '', alert.body));
      list.append(item);
    }
  }

  function renderAlerts() {
    const alerts = state.alerts || [];
    const availability = alerts.filter(alert => alert.kind === 'availability');
    displayAlerts('watch-alerts', availability);
    displayAlerts('alerts', alerts.filter(alert => alert.kind !== 'availability'));
    if (seenAlerts && 'Notification' in window && Notification.permission === 'granted') {
      for (const alert of alerts.filter(alert => !seenAlerts.has(alert.id))) {
        try {
          new Notification(safeText(alert.title), { body: safeText(alert.body), tag: safeText(alert.id) });
        } catch {
          // The alert is still visible in its list.
        }
      }
    }
    seenAlerts = new Set(alerts.map(alert => alert.id));
  }
  async function loadState() {
    const request = ++stateRequest;
    try {
      const data = await api('/api/state');
      if (request !== stateRequest) return;
      state = data;
      const serverNow = validDate(state.now); if (serverNow) clockOffset = serverNow.getTime() - Date.now();
      $('connection-error').hidden = true;
      renderConfig(); renderWatchConfig(); renderWatchStatus(); renderRelease(); renderDateFilter(); renderCandidates(); renderWarnings(); renderBookings(); renderAlerts(); tick();
    } catch (error) {
      if (request !== stateRequest) return;
      $('connection-error').textContent = `无法连接本地助手：${error.message} 请确认启动窗口仍在运行。`;
      $('connection-error').hidden = false;
      if (state) { state.feed = { ...(state.feed || {}), status: 'stale', error: '本地服务连接中断，当前显示的是旧数据。' }; renderFeed(); renderWatchStatus(); renderCandidates(); }
    }
  }
  $('settings-form').addEventListener('input', () => { configDirty = true; });
  $('settings-form').addEventListener('change', () => { configDirty = true; });
  $('settings-form').addEventListener('submit', async event => {
    event.preventDefault(); if (saving || !state) return;
    const venueIds = [...document.querySelectorAll('.venue-checkbox:checked')].map(input => input.value);
    const weekdays = [...$('weekday-options').querySelectorAll('input:checked')].map(input => Number(input.value));
    if (!venueIds.length || !weekdays.length) { toast('请至少选择一个场地及一天。', true); return; }
    if ($('start-time').value >= $('end-time').value) { toast('最晚结束时间须晚于最早开始时间。', true); return; }
    const config = { ...state.config, venue_ids: venueIds, venue_priority: [...venueOrder], weekdays, start_time: $('start-time').value, end_time: $('end-time').value, duration_hours: Number($('duration').value), play_type: $('play-type').value, allow_one_hour_fallback: $('fallback').checked, max_hourly_hkd: Number($('budget').value) };
    saving = true; $('save-button').disabled = true; $('save-button').textContent = '正在保存…';
    try { await mutate('/api/config', config); configDirty = false; await loadState(); toast('排场偏好已保存。'); } catch (error) { toast(error.message, true); } finally { saving = false; $('save-button').disabled = false; $('save-button').textContent = '保存偏好'; }
  });
  $('watch-form').addEventListener('change', () => { watchDirty = true; });
  $('watch-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (saving || !state) return;
    const venueIds = Array.from($('watch-venues').querySelectorAll('input:checked'), input => input.value);
    const enabled = $('monitor-enabled').checked;
    if (enabled && !venueIds.length) {
      toast('请先选择至少一个关注场地。', true);
      return;
    }
    const button = $('save-watch');
    saving = true;
    button.disabled = true;
    try {
      await mutate('/api/config', { ...state.config, watch_venue_ids: venueIds, monitor_enabled: enabled });
      watchDirty = false;
      await loadState();
      toast('监测设置已保存。');
    } catch (error) {
      toast(error.message, true);
    } finally {
      saving = false;
      button.disabled = false;
    }
  });
  $('refresh-button').addEventListener('click', async () => {
    loading = true; renderFeed();
    try { await mutate('/api/refresh', {}); await loadState(); toast(state.feed?.status === 'live' ? '已获取官方数据；空位仍须在官方复核。' : state.mode === 'demo' ? '演示场次已更新。' : '刷新请求已完成，请查看数据状态。'); } catch (error) { toast(error.message, true); await loadState(); } finally { loading = false; renderFeed(); }
  });
  $('mode-button').addEventListener('click', async () => {
    if (!state) return;
    $('mode-button').disabled = true;
    try { await mutate('/api/mode', { mode: state.mode === 'demo' ? 'live' : 'demo' }); await loadState(); toast(state.mode === 'demo' ? '已进入演示，所有时段均为合成示例。' : '已切换官方数据，请查看接口状态。'); } catch (error) { toast(error.message, true); } finally { $('mode-button').disabled = false; }
  });
  $('date-filter').addEventListener('change', () => { if (state) renderCandidates(); });
  function renderNotificationStatus() {
    const supported = 'Notification' in window;
    const permission = supported ? Notification.permission : 'unsupported';
    const messages = {
      unsupported: '此浏览器不支持提醒。',
      denied: '浏览器已阻止提醒。可在此网站的浏览器权限中开启通知。',
      granted: '浏览器提醒已获授权。请保持此页面打开。',
      default: '启用浏览器提醒后，请保持此页面打开。',
    };
    $('notification-status').textContent = messages[permission] || messages.default;
    $('notification-button').disabled = !supported || permission === 'granted' || permission === 'denied';
    $('test-notification').disabled = !supported || permission === 'denied';
  }

  async function requestBrowserNotification(test) {
    if (!('Notification' in window)) return;
    try {
      if (Notification.permission === 'default') await Notification.requestPermission();
      renderNotificationStatus();
      if (Notification.permission !== 'granted') return;
      if (test) {
        new Notification('SmartPLAY 空位提醒测试', { body: '这条测试来自浏览器。发现新增可订时段会在此处提醒。', tag: 'smartplay-browser-test' });
        toast('浏览器已发出测试。请检查系统通知。');
      } else {
        toast('已启用浏览器提醒。');
      }
    } catch {
      toast('无法发出浏览器提醒。请检查浏览器和系统通知权限。', true);
    }
  }

  $('notification-button').addEventListener('click', () => requestBrowserNotification(false));
  $('test-notification').addEventListener('click', () => requestBrowserNotification(true));
  $('close-dialog').addEventListener('click', () => $('record-dialog').close());
  $('record-form').addEventListener('submit', async event => {
    event.preventDefault(); if (!chosenCandidate || !$('paid-attestation').checked) return;
    const reference = $('record-reference').value.trim(); const amount = Number($('record-amount').value);
    if (!reference || !Number.isFinite(amount) || amount < 0) { toast('请填写官方预订编号及有效金额。', true); return; }
    $('record-submit').disabled = true;
    try { await mutate('/api/bookings', { candidate_id: chosenCandidate.id, reference, amount_hkd: amount, attested_paid: true }); $('record-dialog').close(); await loadState(); toast('已保存你录入的已付款记录；助手未核验官方付款。'); } catch (error) { toast(error.message, true); } finally { $('record-submit').disabled = false; }
  });
  $('import-button').addEventListener('click', async () => {
    const raw = $('import-data').value.trim(); let data;
    try { data = JSON.parse(raw); } catch { toast('JSON 格式无效，请粘贴完整的官方原始数据。', true); return; }
    $('import-button').disabled = true;
    try { await mutate('/api/import', { data }); $('import-data').value = ''; await loadState(); toast('导入已校验，请核对数据时间及空位状态。'); } catch (error) { toast(error.message, true); } finally { $('import-button').disabled = false; }
  });
  $('import-file').addEventListener('change', async () => {
    const file = $('import-file').files[0];
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) { toast('文件超过 8MB，请选择官方原始 JSON。', true); $('import-file').value = ''; return; }
    $('import-button').disabled = true;
    try {
      let data;
      try { data = JSON.parse(await file.text()); } catch { throw new Error('文件不是有效 JSON，请选择完整的官方数据文件。'); }
      await mutate('/api/import', { data });
      await loadState();
      toast('已导入手动快照，请核对来源更新时间。');
    } catch (error) { toast(error.message, true); } finally { $('import-button').disabled = false; $('import-file').value = ''; }
  });
  tick();
  renderNotificationStatus();
  loadState();
  setInterval(tick, 1000);
  setInterval(loadState, 30000);
})();
