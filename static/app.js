// SyncInk Radio Dashboard • High-Performance Reactive Client
// Zero-build ES6+ architecture for instant Termux / Docker / Desktop deployment

const state = {
  currentView: 'overview',
  currentUser: null,
  servers: [],
  activeGuildId: null,
  playback: {
    connected: false,
    is_playing: false,
    is_paused: false,
    current_track: null,
    position: 0,
    duration: 0,
    volume: 100,
    repeat_mode: 'off',
    autoplay: false,
    radio_station: null,
    queue: [],
    queue_size: 0
  },
  radioCountries: [],
  activeRadioCountry: 'India',
  ws: null,
  localTicker: null,
  debounceTimer: null
};

// ------------------- INITIALIZATION -------------------
window.addEventListener('DOMContentLoaded', async () => {
  initIcons();
  initRouting();
  await checkAuthStatus();
  await loadServers();
  initWebSocket();
  startLocalPlaybackTicker();
});

function initIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

// ------------------- ROUTING & VIEW NAVIGATION -------------------
function initRouting() {
  const hash = window.location.hash.replace('#', '') || 'overview';
  navigateTo(hash);
  window.addEventListener('hashchange', () => {
    const newHash = window.location.hash.replace('#', '') || 'overview';
    navigateTo(newHash);
  });
}

function navigateTo(viewId) {
  state.currentView = viewId;
  window.location.hash = viewId;

  // Toggle view panels
  document.querySelectorAll('.view-panel').forEach(panel => {
    panel.classList.add('hidden');
  });

  const activePanel = document.getElementById(`view-${viewId}`);
  if (activePanel) {
    activePanel.classList.remove('hidden');
  }

  // Update navigation items active state
  document.querySelectorAll('.nav-item').forEach(item => {
    const isCurrent = item.getAttribute('data-view') === viewId;
    if (isCurrent) {
      item.className = 'nav-item flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all text-white bg-brand-primary/20 border border-brand-primary/30';
    } else {
      item.className = 'nav-item flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all text-[#9E9EAD] hover:text-white hover:bg-brand-surface';
    }
  });

  // Close mobile drawer if open
  closeMobileMenu();

  // Load view-specific data
  if (viewId === 'radio') loadRadioView();
  else if (viewId === 'audia') loadAudiaProfile();
  else if (viewId === 'library') loadLibraryFavorites();
  else if (viewId === 'history') loadListeningHistory();
  else if (viewId === 'analytics') loadAnalytics();
  else if (viewId === 'servers') loadServersView();
  else if (viewId === 'admin') loadAdminDiagnostics();

  initIcons();
}

function toggleMobileMenu() {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.toggle('hidden');
  sidebar.classList.toggle('fixed');
  sidebar.classList.toggle('inset-y-0');
  sidebar.classList.toggle('left-0');
}

function closeMobileMenu() {
  const sidebar = document.getElementById('sidebar');
  if (sidebar.classList.contains('fixed')) {
    sidebar.classList.add('hidden');
    sidebar.classList.remove('fixed', 'inset-y-0', 'left-0');
  }
}

// ------------------- AUTHENTICATION -------------------
async function checkAuthStatus() {
  try {
    const res = await fetch('/api/auth/me');
    const data = await res.json();
    if (data.authenticated && data.user) {
      state.currentUser = data.user;
      document.getElementById('login-btn').classList.add('hidden');
      const pill = document.getElementById('user-profile-pill');
      pill.classList.remove('hidden');
      pill.classList.add('flex');
      document.getElementById('user-avatar').src = data.user.avatar_url;
      document.getElementById('user-username').innerText = data.user.username;
      document.getElementById('user-tag').innerText = `#${data.user.discriminator}`;
    }
  } catch (e) {
    console.warn('Auth check error:', e);
  }
}

async function logout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
    state.currentUser = null;
    window.location.reload();
  } catch (e) {
    console.error('Logout error:', e);
  }
}

// ------------------- REAL-TIME WEBSOCKET GATEWAY -------------------
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      document.getElementById('gateway-dot').className = 'w-2 h-2 rounded-full bg-emerald-500 animate-pulse';
      document.getElementById('gateway-status').innerText = 'Live Gateway';
      if (state.activeGuildId) {
        state.ws.send(JSON.stringify({ type: 'subscribe', guild_id: state.activeGuildId }));
      }
    };

    state.ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event === 'playback_update') {
          if (!state.activeGuildId || state.activeGuildId === payload.guild_id) {
            updatePlaybackState(payload.data);
          }
        }
      } catch (err) {
        console.warn('WS message parse error:', err);
      }
    };

    state.ws.onclose = () => {
      document.getElementById('gateway-dot').className = 'w-2 h-2 rounded-full bg-amber-500';
      document.getElementById('gateway-status').innerText = 'Reconnecting...';
      setTimeout(initWebSocket, 4000);
    };

    state.ws.onerror = () => {
      state.ws.close();
    };
  } catch (e) {
    console.warn('WebSocket init failed:', e);
  }
}

function subscribeToGuild(guildId) {
  state.activeGuildId = guildId;
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: 'subscribe', guild_id: guildId }));
  }
  fetchGuildSnapshot(guildId);
}

async function fetchGuildSnapshot(guildId) {
  try {
    const res = await fetch(`/api/servers/${guildId}`);
    if (res.ok) {
      const data = await res.json();
      updatePlaybackState(data);
    }
  } catch (e) {
    console.warn('Snapshot fetch error:', e);
  }
}

// ------------------- PLAYBACK TIMELINE & SYNC -------------------
function startLocalPlaybackTicker() {
  if (state.localTicker) clearInterval(state.localTicker);
  state.localTicker = setInterval(() => {
    if (state.playback.is_playing && !state.playback.is_paused) {
      state.playback.position += 1;
      if (state.playback.duration > 0 && state.playback.position > state.playback.duration) {
        state.playback.position = state.playback.duration;
      }
      renderTimelineOnly();
    }
  }, 1000);
}

function updatePlaybackState(data) {
  state.playback = Object.assign({}, state.playback, data);
  renderBottomPlayer();
  renderQueueDrawer();
  initIcons();
}

function renderTimelineOnly() {
  const currentEl = document.getElementById('player-current-time');
  const totalEl = document.getElementById('player-total-time');
  const barEl = document.getElementById('player-progress-bar');

  currentEl.innerText = formatDuration(state.playback.position);
  totalEl.innerText = state.playback.duration > 0 ? formatDuration(state.playback.duration) : 'LIVE';

  if (state.playback.duration > 0) {
    const pct = Math.min(100, Math.max(0, (state.playback.position / state.playback.duration) * 100));
    barEl.style.width = `${pct}%`;
  } else {
    barEl.style.width = state.playback.is_playing ? '100%' : '0%';
  }
}

function renderBottomPlayer() {
  const track = state.playback.current_track;
  const titleEl = document.getElementById('player-track-title');
  const artistEl = document.getElementById('player-track-artist');
  const imgEl = document.getElementById('player-track-img');
  const playPauseIcon = document.getElementById('icon-playpause');
  const volumeSlider = document.getElementById('player-volume-slider');
  const queueBadge = document.getElementById('player-queue-badge');

  if (track) {
    titleEl.innerText = track.title;
    artistEl.innerText = track.author || (track.is_radio ? 'Live Radio Stream' : 'SyncInk Platform');
    imgEl.src = track.thumbnail || 'https://files.catbox.moe/74l9su.png';
  } else if (state.playback.radio_station) {
    titleEl.innerText = state.playback.radio_station;
    artistEl.innerText = '24/7 Continuous Live Radio';
    imgEl.src = 'https://files.catbox.moe/74l9su.png';
  } else {
    titleEl.innerText = 'Nothing is playing';
    artistEl.innerText = 'Select a server or start with /play';
    imgEl.src = 'https://files.catbox.moe/74l9su.png';
  }

  // Play/Pause button icon
  if (state.playback.is_playing && !state.playback.is_paused) {
    playPauseIcon.setAttribute('data-lucide', 'pause');
  } else {
    playPauseIcon.setAttribute('data-lucide', 'play');
  }

  volumeSlider.value = state.playback.volume;
  queueBadge.innerText = `Queue (${state.playback.queue_size || state.playback.queue.length})`;

  // Loop button styling
  const loopBtn = document.getElementById('player-btn-loop');
  if (state.playback.repeat_mode !== 'off') {
    loopBtn.className = 'text-brand-secondary p-1 font-bold';
  } else {
    loopBtn.className = 'text-[#9E9EAD] hover:text-white p-1';
  }

  renderTimelineOnly();
}

function renderQueueDrawer() {
  const listEl = document.getElementById('queue-drawer-list');
  listEl.innerHTML = '';

  if (!state.playback.queue || state.playback.queue.length === 0) {
    listEl.innerHTML = '<div class="text-center py-10 text-[#6B6A78] text-xs">No upcoming tracks in queue.<br>Use <code>/play</code> in Discord or search above.</div>';
    return;
  }

  state.playback.queue.forEach((t, i) => {
    const div = document.createElement('div');
    div.className = 'flex items-center gap-3 p-2.5 rounded-xl bg-brand-surface/70 border border-brand-border/30 hover:border-brand-primary/50 text-xs';
    div.innerHTML = `
      <span class="font-mono text-[#6B6A78] w-4 text-center">${i + 1}</span>
      <img src="${t.thumbnail || 'https://files.catbox.moe/74l9su.png'}" class="w-9 h-9 rounded-lg object-cover">
      <div class="min-w-0 flex-1">
        <p class="font-semibold text-white truncate">${escapeHtml(t.title)}</p>
        <p class="text-[11px] text-[#9E9EAD] truncate">${escapeHtml(t.author || 'Artist')}</p>
      </div>
      <span class="font-mono text-[11px] text-[#6B6A78]">${t.formatted_duration || ''}</span>
    `;
    listEl.appendChild(div);
  });
}

function toggleQueueDrawer() {
  const drawer = document.getElementById('queue-drawer');
  drawer.classList.toggle('translate-x-full');
}

// ------------------- PLAYER CONTROLS & API ACTIONS -------------------
async function sendControlAction(action, payload = {}) {
  if (!state.activeGuildId) {
    showToast('Please select a Discord server first!', 'warning');
    return;
  }

  try {
    const res = await fetch(`/api/servers/${state.activeGuildId}/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ action }, payload))
    });
    const data = await res.json();
    if (data.success && data.state) {
      updatePlaybackState(data.state);
    }
  } catch (err) {
    console.error('Player action failed:', err);
    showToast('Failed to execute command: ' + err, 'error');
  }
}

function togglePlayPause() {
  if (state.playback.is_playing && !state.playback.is_paused) {
    sendControlAction('pause');
  } else {
    sendControlAction('resume');
  }
}

function controlPlayer(action) {
  sendControlAction(action);
}

function changeVolume(val) {
  clearTimeout(state.debounceTimer);
  state.debounceTimer = setTimeout(() => {
    sendControlAction('volume', { volume: parseInt(val) });
  }, 100);
}

function cycleLoopMode() {
  const modes = ['off', 'track', 'queue'];
  const next = modes[(modes.indexOf(state.playback.repeat_mode) + 1) % modes.length];
  sendControlAction('loop', { mode: next });
}

function triggerQuickPlay() {
  const input = document.getElementById('overview-quick-play-input');
  const query = input.value.trim();
  if (!query) return;
  sendControlAction('play', { query });
  input.value = '';
  showToast(`Enqueuing "${query}"...`, 'info');
}

function tunePresetRadio(stationId) {
  sendControlAction('play', { query: `radio:${stationId}` });
  showToast(`Tuning into ${stationId.toUpperCase()} Radio...`, 'info');
}

// ------------------- SERVER SELECTOR & SERVERS VIEW -------------------
async function loadServers() {
  try {
    const res = await fetch('/api/servers');
    const data = await res.json();
    state.servers = data.servers || [];

    const dropdownList = document.getElementById('server-dropdown-list');
    dropdownList.innerHTML = '';

    if (state.servers.length > 0) {
      if (!state.activeGuildId) {
        state.activeGuildId = state.servers[0].id;
      }

      state.servers.forEach(s => {
        const item = document.createElement('div');
        item.className = 'flex items-center gap-2.5 p-2 rounded-xl hover:bg-brand-surface-elevated cursor-pointer text-xs font-medium';
        item.onclick = () => selectServer(s.id);
        item.innerHTML = `
          <img src="${s.icon}" class="w-6 h-6 rounded-lg object-cover">
          <span class="truncate flex-1">${escapeHtml(s.name)}</span>
          ${s.connected ? '<span class="w-2 h-2 rounded-full bg-emerald-500"></span>' : ''}
        `;
        dropdownList.appendChild(item);
      });

      const active = state.servers.find(s => s.id === state.activeGuildId) || state.servers[0];
      selectServer(active.id, false);
    } else {
      document.getElementById('active-server-name').innerText = 'No Servers';
    }

    // Update Overview Stats
    document.getElementById('stat-guilds').innerText = state.servers.length;
    let totalListeners = state.servers.reduce((acc, s) => acc + (s.listeners || 0), 0);
    document.getElementById('stat-listeners').innerText = totalListeners;
  } catch (err) {
    console.warn('Servers load error:', err);
  }
}

function toggleServerDropdown() {
  document.getElementById('server-dropdown').classList.toggle('hidden');
}

function selectServer(guildId, fetchNow = true) {
  state.activeGuildId = guildId;
  const s = state.servers.find(srv => srv.id === guildId);
  if (s) {
    document.getElementById('active-server-name').innerText = s.name;
    document.getElementById('active-server-icon').src = s.icon;
  }
  document.getElementById('server-dropdown').classList.add('hidden');
  subscribeToGuild(guildId);
}

function loadServersView() {
  const container = document.getElementById('servers-full-list');
  container.innerHTML = '';

  state.servers.forEach(s => {
    const card = document.createElement('div');
    card.className = 'glass-panel p-5 rounded-2xl flex flex-col justify-between';
    card.innerHTML = `
      <div>
        <div class="flex items-center gap-3.5 mb-3">
          <img src="${s.icon}" class="w-12 h-12 rounded-2xl border border-brand-border/40 object-cover">
          <div class="min-w-0 flex-1">
            <h4 class="font-bold text-sm truncate">${escapeHtml(s.name)}</h4>
            <span class="inline-block mt-0.5 text-[10px] font-bold px-2 py-0.5 rounded-full badge-violet uppercase">${s.permission}</span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-[#9E9EAD] mb-4">
          <p class="flex items-center justify-between">
            <span>Voice Status:</span>
            <span class="font-semibold ${s.connected ? 'text-emerald-400' : 'text-[#6B6A78]'}">${s.connected ? 'Active in ' + (s.voice_channel || 'VC') : 'Idle'}</span>
          </p>
          <p class="flex items-center justify-between">
            <span>Active Listeners:</span>
            <span class="font-semibold text-white">${s.listeners || 0}</span>
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2 pt-2 border-t border-brand-border/20">
        <button onclick="selectServer('${s.id}')" class="flex-1 py-2 rounded-xl text-xs font-bold bg-brand-primary/20 text-brand-secondary hover:bg-brand-primary hover:text-white transition-all">
          Connect Dashboard
        </button>
        <button onclick="openServerSettings('${s.id}')" class="p-2 rounded-xl bg-brand-surface border border-brand-border/40 hover:text-white text-[#9E9EAD]" title="Server Settings">
          <i data-lucide="settings" class="w-4 h-4"></i>
        </button>
      </div>
    `;
    container.appendChild(card);
  });
  initIcons();
}

async function openServerSettings(guildId) {
  try {
    const res = await fetch(`/api/servers/${guildId}/settings`);
    const data = await res.json();
    const card = document.getElementById('server-settings-card');
    card.classList.remove('hidden');

    const s = state.servers.find(srv => srv.id === guildId);
    document.getElementById('settings-server-name').innerText = `${s ? s.name : 'Server'} Settings`;

    const chanSelect = document.getElementById('setting-music-channel');
    chanSelect.innerHTML = '<option value="">All Channels Allowed</option>';
    (data.available_channels || []).forEach(c => {
      chanSelect.innerHTML += `<option value="${c.id}" ${data.music_channel_id === c.id ? 'selected' : ''}>#${escapeHtml(c.name)}</option>`;
    });

    const roleSelect = document.getElementById('setting-dj-role');
    roleSelect.innerHTML = '<option value="">No DJ Role Restriction</option>';
    (data.available_roles || []).forEach(r => {
      roleSelect.innerHTML += `<option value="${r.id}" ${data.dj_role_id === r.id ? 'selected' : ''}>@${escapeHtml(r.name)}</option>`;
    });

    card.scrollIntoView({ behavior: 'smooth' });
  } catch (err) {
    showToast('Failed to load settings: ' + err, 'error');
  }
}

function closeServerSettings() {
  document.getElementById('server-settings-card').classList.add('hidden');
}

async function saveServerSettings() {
  if (!state.activeGuildId) return;
  const music_channel_id = document.getElementById('setting-music-channel').value;
  const dj_role_id = document.getElementById('setting-dj-role').value;

  try {
    const res = await fetch(`/api/servers/${state.activeGuildId}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ music_channel_id, dj_role_id })
    });
    if (res.ok) {
      showToast('Server settings successfully updated!', 'success');
      closeServerSettings();
    }
  } catch (err) {
    showToast('Failed to save settings: ' + err, 'error');
  }
}

// ------------------- GLOBAL RADIO DIRECTORY -------------------
async function loadRadioView() {
  await loadRadioCountries();
  await loadRadioStations(state.activeRadioCountry);
}

async function loadRadioCountries() {
  try {
    const res = await fetch('/api/radio/countries');
    const data = await res.json();
    state.radioCountries = data.countries || [];

    const bar = document.getElementById('radio-countries-bar');
    bar.innerHTML = '';

    state.radioCountries.forEach(c => {
      const btn = document.createElement('button');
      const isSelected = c.name === state.activeRadioCountry;
      btn.className = isSelected
        ? 'px-3.5 py-1.5 rounded-xl text-xs font-bold whitespace-nowrap bg-brand-primary text-white shadow-md shadow-brand-primary/30 shrink-0'
        : 'px-3.5 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap bg-brand-surface text-[#9E9EAD] hover:text-white border border-brand-border/40 shrink-0';
      btn.innerText = `${c.flag || '🌐'} ${c.name} (${c.stationcount || 0})`;
      btn.onclick = () => {
        state.activeRadioCountry = c.name;
        loadRadioCountries();
        loadRadioStations(c.name);
      };
      bar.appendChild(btn);
    });
  } catch (e) {
    console.warn('Countries error:', e);
  }
}

async function loadRadioStations(country, genre = '', query = '') {
  try {
    const url = `/api/radio/stations?country=${encodeURIComponent(country)}&genre=${encodeURIComponent(genre)}&query=${encodeURIComponent(query)}&limit=60`;
    const res = await fetch(url);
    const data = await res.json();

    const grid = document.getElementById('radio-stations-grid');
    grid.innerHTML = '';

    if (!data.stations || data.stations.length === 0) {
      grid.innerHTML = '<div class="col-span-full py-12 text-center text-[#6B6A78] text-xs">No radio stations matched your filter.</div>';
      return;
    }

    data.stations.forEach(st => {
      const card = document.createElement('div');
      card.className = 'glass-card-interactive p-4 flex flex-col justify-between';
      card.innerHTML = `
        <div>
          <div class="flex items-center gap-3 mb-2.5">
            <img src="${st.favicon}" class="w-10 h-10 rounded-xl object-cover border border-brand-border/40 shrink-0 bg-[#101014]">
            <div class="min-w-0 flex-1">
              <h4 class="font-bold text-sm truncate text-white">${escapeHtml(st.name)}</h4>
              <p class="text-[11px] text-[#9E9EAD] truncate">${escapeHtml(st.tags || st.country)}</p>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-2 mt-3 pt-2.5 border-t border-brand-border/20">
          <button onclick="tuneStation(${JSON.stringify(st).replace(/"/g, '&quot;')})" class="flex-1 py-1.5 rounded-lg text-xs font-bold bg-brand-primary/20 text-brand-secondary hover:bg-brand-primary hover:text-white transition-all flex items-center justify-center gap-1.5">
            <i data-lucide="radio" class="w-3.5 h-3.5"></i> Tune In
          </button>
          <button onclick="bookmarkStation(${JSON.stringify(st).replace(/"/g, '&quot;')})" class="p-1.5 rounded-lg bg-brand-surface border border-brand-border/30 text-[#9E9EAD] hover:text-rose-400" title="Favorite">
            <i data-lucide="heart" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      `;
      grid.appendChild(card);
    });
    initIcons();
  } catch (err) {
    console.error('Radio stations load error:', err);
  }
}

function debounceRadioSearch() {
  clearTimeout(state.debounceTimer);
  state.debounceTimer = setTimeout(() => {
    const q = document.getElementById('radio-search-input').value.trim();
    loadRadioStations(state.activeRadioCountry, '', q);
  }, 300);
}

async function tuneStation(st) {
  if (!state.activeGuildId) {
    showToast('Please select a server first in the top bar!', 'warning');
    return;
  }

  try {
    const res = await fetch('/api/radio/tune', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        guild_id: state.activeGuildId,
        station_name: st.name,
        country: st.country,
        url: st.url,
        favicon: st.favicon
      })
    });
    if (res.ok) {
      showToast(`Tuned into ${st.name}!`, 'success');
    }
  } catch (err) {
    showToast('Failed to tune station: ' + err, 'error');
  }
}

async function bookmarkStation(st) {
  try {
    await fetch('/api/library/favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_type: 'radio',
        item_id: st.stationuuid || st.name,
        title: st.name,
        subtitle: st.country,
        image_url: st.favicon,
        url: st.url
      })
    });
    showToast(`Added ${st.name} to My Library!`, 'success');
  } catch (err) {
    showToast('Failed to add favorite: ' + err, 'error');
  }
}

// ------------------- AUDIA AI STUDIO -------------------
async function loadAudiaProfile() {
  try {
    const res = await fetch('/api/audia/profile');
    const data = await res.json();

    document.getElementById('audia-discovery-mode').value = data.discovery_mode || 'balanced';
    document.getElementById('audia-genre-mood').value = data.manual_mood ? `${data.manual_mood}|${data.manual_genre}` : '';
    document.getElementById('audia-language').value = data.manual_language || '';

    const artistsList = document.getElementById('audia-artists-list');
    artistsList.innerHTML = '';

    if (!data.top_artists || data.top_artists.length === 0) {
      artistsList.innerHTML = '<span class="text-xs text-[#6B6A78]">No learned artists yet. Start playing songs in voice channels to build your musical taste profile!</span>';
      return;
    }

    data.top_artists.forEach(a => {
      const badge = document.createElement('span');
      badge.className = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-brand-surface border border-brand-border/40 text-xs font-medium text-white';
      badge.innerHTML = `
        <span>${escapeHtml(a.artist)}</span>
        <span class="text-[10px] font-bold text-brand-secondary bg-brand-primary/20 px-1.5 py-0.5 rounded-md">${a.affinity}</span>
      `;
      artistsList.appendChild(badge);
    });
  } catch (err) {
    console.warn('Audia load error:', err);
  }
}

async function updateAudiaSettings() {
  const discovery_mode = document.getElementById('audia-discovery-mode').value;
  const genreMoodRaw = document.getElementById('audia-genre-mood').value;
  const manual_language = document.getElementById('audia-language').value;

  let manual_mood = '';
  let manual_genre = '';
  if (genreMoodRaw.includes('|')) {
    const parts = genreMoodRaw.split('|');
    manual_mood = parts[0];
    manual_genre = parts[1];
  }

  try {
    await fetch('/api/audia/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ discovery_mode, manual_mood, manual_genre, manual_language })
    });
    showToast('Audia AI taste preferences updated!', 'success');
  } catch (err) {
    showToast('Failed to update Audia settings: ' + err, 'error');
  }
}

// ------------------- MY LIBRARY & FAVORITES -------------------
async function loadLibraryFavorites() {
  try {
    const res = await fetch('/api/library/favorites');
    const data = await res.json();
    const container = document.getElementById('library-favorites-list');
    container.innerHTML = '';

    if (!data.favorites || data.favorites.length === 0) {
      container.innerHTML = '<div class="col-span-full py-16 text-center text-[#6B6A78] text-xs">Your library is empty.<br>Click the heart icon on any track or radio station to bookmark it!</div>';
      return;
    }

    data.favorites.forEach(f => {
      const card = document.createElement('div');
      card.className = 'glass-panel p-4 rounded-2xl flex items-center justify-between';
      card.innerHTML = `
        <div class="flex items-center gap-3 min-w-0">
          <img src="${f.image_url || 'https://files.catbox.moe/74l9su.png'}" class="w-12 h-12 rounded-xl object-cover border border-brand-border/40 shrink-0">
          <div class="min-w-0">
            <h4 class="font-bold text-sm truncate">${escapeHtml(f.title)}</h4>
            <p class="text-[11px] text-[#9E9EAD] truncate">${escapeHtml(f.subtitle || f.item_type)}</p>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button onclick="sendControlAction('play', { query: '${escapeHtml(f.title)}' })" class="p-2 rounded-xl bg-brand-primary/20 text-brand-secondary hover:bg-brand-primary hover:text-white" title="Play">
            <i data-lucide="play" class="w-4 h-4 fill-current"></i>
          </button>
          <button onclick="removeFavorite(${f.id})" class="p-2 rounded-xl text-[#9E9EAD] hover:text-rose-400" title="Remove">
            <i data-lucide="trash-2" class="w-4 h-4"></i>
          </button>
        </div>
      `;
      container.appendChild(card);
    });
    initIcons();
  } catch (e) {
    console.warn('Library error:', e);
  }
}

async function removeFavorite(id) {
  try {
    await fetch(`/api/library/favorites/${id}`, { method: 'DELETE' });
    loadLibraryFavorites();
    showToast('Removed from library', 'info');
  } catch (e) {
    console.error('Remove favorite error:', e);
  }
}

// ------------------- LISTENING HISTORY -------------------
async function loadListeningHistory() {
  try {
    const res = await fetch('/api/history?limit=40');
    const data = await res.json();
    const tbody = document.getElementById('history-table-body');
    tbody.innerHTML = '';

    if (!data.history || data.history.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="py-10 text-center text-[#6B6A78]">No listening history recorded yet.</td></tr>';
      return;
    }

    data.history.forEach(h => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-brand-surface/40 transition-colors';
      tr.innerHTML = `
        <td class="px-4 py-3 flex items-center gap-3">
          <img src="${h.thumbnail_url || 'https://files.catbox.moe/74l9su.png'}" class="w-8 h-8 rounded-lg object-cover">
          <span class="font-medium text-white truncate max-w-xs">${escapeHtml(h.track_title)}</span>
        </td>
        <td class="px-4 py-3 text-[#9E9EAD] hidden sm:table-cell truncate max-w-xs">${escapeHtml(h.track_author || 'Artist')}</td>
        <td class="px-4 py-3 text-[#9E9EAD] hidden md:table-cell uppercase font-semibold text-[10px]">${escapeHtml(h.platform || 'audio')}</td>
        <td class="px-4 py-3 font-mono text-[#9E9EAD]">${formatDuration(h.duration)}</td>
        <td class="px-4 py-3 text-right text-[#6B6A78]">${h.played_at ? new Date(h.played_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.warn('History load error:', err);
  }
}

// ------------------- ANALYTICS -------------------
async function loadAnalytics() {
  try {
    const res = await fetch('/api/analytics');
    const data = await res.json();

    document.getElementById('analytics-total-hours').innerText = `${data.total_hours || 0} hrs`;
    document.getElementById('analytics-total-tracks').innerText = data.total_tracks || 0;

    const artistsContainer = document.getElementById('analytics-top-artists');
    artistsContainer.innerHTML = '';
    (data.top_artists || []).forEach((a, i) => {
      const div = document.createElement('div');
      div.className = 'flex items-center justify-between p-3 rounded-xl bg-brand-surface/70 border border-brand-border/30 text-xs';
      div.innerHTML = `
        <div class="flex items-center gap-2.5">
          <span class="font-mono text-[#6B6A78] w-4">${i + 1}</span>
          <span class="font-bold text-white">${escapeHtml(a.track_author)}</span>
        </div>
        <span class="font-semibold text-brand-secondary">${a.play_count} plays</span>
      `;
      artistsContainer.appendChild(div);
    });

    const tracksContainer = document.getElementById('analytics-top-tracks');
    tracksContainer.innerHTML = '';
    (data.top_tracks || []).forEach((t, i) => {
      const div = document.createElement('div');
      div.className = 'flex items-center justify-between p-3 rounded-xl bg-brand-surface/70 border border-brand-border/30 text-xs';
      div.innerHTML = `
        <div class="flex items-center gap-2.5 min-w-0">
          <span class="font-mono text-[#6B6A78] w-4">${i + 1}</span>
          <img src="${t.thumbnail_url || 'https://files.catbox.moe/74l9su.png'}" class="w-7 h-7 rounded-lg object-cover">
          <span class="font-bold text-white truncate max-w-xs">${escapeHtml(t.track_title)}</span>
        </div>
        <span class="font-semibold text-brand-secondary shrink-0">${t.play_count} plays</span>
      `;
      tracksContainer.appendChild(div);
    });
  } catch (err) {
    console.warn('Analytics error:', err);
  }
}

// ------------------- SYSTEM ADMIN DIAGNOSTICS -------------------
async function loadAdminDiagnostics() {
  try {
    const res = await fetch('/api/admin/status');
    const data = await res.json();
    const container = document.getElementById('admin-details-grid');
    container.innerHTML = `
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD]">Bot Online Status</p>
        <p class="text-2xl font-bold text-emerald-400 mt-1">${data.status.toUpperCase()}</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">${data.bot_name}</p>
      </div>
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD]">Voice Latency</p>
        <p class="text-2xl font-bold text-brand-secondary mt-1">${data.latency_ms} ms</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">Discord WebSocket Heartbeat</p>
      </div>
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD]">Active Voice Sessions</p>
        <p class="text-2xl font-bold text-white mt-1">${data.active_voice_sessions}</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">Concurrently streaming audio</p>
      </div>
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD]">Connected Web Clients</p>
        <p class="text-2xl font-bold text-purple-400 mt-1">${data.web_clients}</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">Real-time WebSocket /ws subscribers</p>
      </div>
    `;
  } catch (err) {
    console.warn('Admin status error:', err);
  }
}

// ------------------- UTILITIES & TOAST NOTIFICATIONS -------------------
function formatDuration(seconds) {
  if (!seconds || isNaN(seconds)) return '00:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins < 10 ? '0' : ''}${mins}:${secs < 10 ? '0' : ''}${secs}`;
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `
    <i data-lucide="${type === 'success' ? 'check-circle' : type === 'warning' ? 'alert-triangle' : 'info'}" class="w-4 h-4 text-brand-secondary"></i>
    <span>${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);
  initIcons();
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}
