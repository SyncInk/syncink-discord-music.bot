// ================================================================
// SyncInk Radio • High-Performance Reactive Dashboard Client
// Production Single-Page Application • Real-Time WebSocket Gateway
// Target Live-State Synchronization Latency: <1 second
// ================================================================

// Base path detection for mounting at syncink.site/dashboard/radio or localhost:8888/
const BASE_PATH = (window.SYNCINK_BASE_PATH !== undefined)
  ? window.SYNCINK_BASE_PATH
  : (window.location.pathname.startsWith('/dashboard/radio') ? '/dashboard/radio' : '');

// Transparently prefix API calls if running under /dashboard/radio
const _nativeFetch = window.fetch;
window.fetch = function(resource, init) {
  if (typeof resource === 'string' && resource.startsWith('/api/')) {
    resource = `${BASE_PATH}${resource}`;
  }
  return _nativeFetch(resource, init);
};

const switchView = navigateTo;

const state = {
  currentView: 'overview',
  currentUser: null,
  servers: [],
  activeGuildId: null,
  playback: {
    guild_id: null,
    server_name: 'Server',
    server_icon: 'https://files.catbox.moe/74l9su.png',
    connected: false,
    channel_name: null,
    channel_id: null,
    listeners: 0,
    is_playing: false,
    is_paused: false,
    current_track: null,
    position: 0,
    duration: 0,
    volume: 100,
    repeat_mode: 'off',
    autoplay: false,
    is_247: false,
    radio_station: null,
    active_radio_info: null,
    queue: [],
    queue_size: 0,
    autoplay_meta: null,
    prefetched_track: null,
    server_time: Date.now() / 1000
  },
  radioCountries: [],
  activeRadioCountry: 'India',
  activeRadioCategory: 'countries',
  activeRadioGenre: '',
  libraryTab: 'all',
  historyTimeframe: 'all',
  analyticsTimeframe: '7d',
  ws: null,
  wsReconnectAttempts: 0,
  localTicker: null,
  debounceTimer: null,
  mutedBeforeVolume: 100
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
  // Guard admin view
  if (viewId === 'admin' && (!state.currentUser || !state.currentUser.is_admin)) {
    showToast('System Admin section is restricted to authorized SyncInk Administrators.', 'warning');
    viewId = 'overview';
  }

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

  // Update navigation items active state (desktop)
  document.querySelectorAll('#sidebar .nav-item').forEach(item => {
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
  if (viewId === 'overview') loadOverviewData();
  else if (viewId === 'radio') loadRadioView();
  else if (viewId === 'audia') loadAudiaView();
  else if (viewId === 'library') loadLibraryView();
  else if (viewId === 'history') loadListeningHistory();
  else if (viewId === 'analytics') loadAnalytics();
  else if (viewId === 'servers') loadServersView();
  else if (viewId === 'admin') loadAdminDiagnostics();

  initIcons();
}

function toggleMobileMenu() {
  const drawer = document.getElementById('mobile-drawer');
  const backdrop = document.getElementById('mobile-drawer-backdrop');
  drawer.classList.toggle('-translate-x-full');
  backdrop.classList.toggle('hidden');
}

function closeMobileMenu() {
  const drawer = document.getElementById('mobile-drawer');
  const backdrop = document.getElementById('mobile-drawer-backdrop');
  if (drawer) drawer.classList.add('-translate-x-full');
  if (backdrop) backdrop.classList.add('hidden');
}

// ------------------- AUTHENTICATION & PROFILE -------------------
async function checkAuthStatus() {
  try {
    const res = await fetch('/api/auth/me');
    const data = await res.json();
    const demoLabel = document.getElementById('demo-mode-label');

    if (data.authenticated && data.user) {
      state.currentUser = data.user;
      document.getElementById('login-btn').classList.add('hidden');
      const pill = document.getElementById('user-profile-pill');
      pill.classList.remove('hidden');
      pill.classList.add('flex');
      document.getElementById('user-avatar').src = data.user.avatar_url;
      document.getElementById('user-username').innerText = data.user.username;
      document.getElementById('user-tag').innerText = data.user.discriminator !== '0' ? `#${data.user.discriminator}` : '';

      if (demoLabel) {
        demoLabel.innerText = data.user.id === '999888777' ? 'Exit Demo' : 'Demo Mode';
      }

      // Personalized greeting
      const greetingEl = document.getElementById('overview-greeting');
      if (greetingEl) {
        greetingEl.innerText = `Welcome back, ${data.user.username}`;
      }

      // Show Admin navigation if user is authorized
      if (data.user.is_admin) {
        const adminSection = document.getElementById('nav-admin-section');
        if (adminSection) adminSection.classList.remove('hidden');
        const mobileAdmin = document.getElementById('mobile-nav-admin');
        if (mobileAdmin) mobileAdmin.classList.remove('hidden');
      }
    } else {
      state.currentUser = null;
      const loginBtn = document.getElementById('login-btn');
      if (loginBtn) {
        loginBtn.classList.remove('hidden');
        loginBtn.href = `${BASE_PATH}/api/auth/discord/login`;
      }
      const pill = document.getElementById('user-profile-pill');
      pill.classList.add('hidden');
      pill.classList.remove('flex');
      if (demoLabel) demoLabel.innerText = 'Demo Mode';
    }
  } catch (e) {
    console.warn('Auth check error:', e);
  }
}

async function toggleDemoMode() {
  try {
    const res = await fetch('/api/auth/demo', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(data.message || 'Demo mode updated', 'success');
      await checkAuthStatus();
      await loadServers();
      switchView('overview');
    }
  } catch (err) {
    showToast('Failed to toggle demo mode', 'error');
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

// ------------------- REAL-TIME WEBSOCKET GATEWAY (<1s LATENCY) -------------------
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}${BASE_PATH}/ws`;

  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      state.wsReconnectAttempts = 0;
      const dot = document.getElementById('gateway-dot');
      const status = document.getElementById('gateway-status');
      if (dot) dot.className = 'w-2 h-2 rounded-full bg-emerald-500 animate-pulse';
      if (status) status.innerText = 'Live Gateway';

      // Resubscribe to currently selected server
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
        console.warn('[WS Parse Error]', err);
      }
    };

    state.ws.onclose = () => {
      const dot = document.getElementById('gateway-dot');
      const status = document.getElementById('gateway-status');
      if (dot) dot.className = 'w-2 h-2 rounded-full bg-amber-500';
      if (status) status.innerText = 'Reconnecting...';

      const delay = Math.min(8000, 1000 * Math.pow(1.5, state.wsReconnectAttempts++));
      setTimeout(initWebSocket, delay);
    };

    state.ws.onerror = () => {
      if (state.ws) state.ws.close();
    };
  } catch (e) {
    console.warn('[WS Init Failed]', e);
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

// ------------------- PLAYBACK TIMELINE & TICKER -------------------
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
  renderSpotlightCard();
  renderQueueDrawer();
  initIcons();
}

function renderTimelineOnly() {
  const currentEl = document.getElementById('player-current-time');
  const totalEl = document.getElementById('player-total-time');
  const barEl = document.getElementById('player-progress-bar');

  if (currentEl) currentEl.innerText = formatDuration(state.playback.position);
  if (totalEl) totalEl.innerText = state.playback.duration > 0 ? formatDuration(state.playback.duration) : 'LIVE';

  if (barEl) {
    if (state.playback.duration > 0) {
      const pct = Math.min(100, Math.max(0, (state.playback.position / state.playback.duration) * 100));
      barEl.style.width = `${pct}%`;
    } else {
      barEl.style.width = state.playback.is_playing ? '100%' : '0%';
    }
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
  const serverLabel = document.getElementById('player-server-label');

  if (track) {
    if (titleEl) titleEl.innerText = track.title;
    if (artistEl) artistEl.innerText = track.author || (track.is_radio ? 'Live Radio Stream' : 'SyncInk Platform');
    if (imgEl) imgEl.src = track.thumbnail || 'https://files.catbox.moe/74l9su.png';
  } else if (state.playback.radio_station) {
    if (titleEl) titleEl.innerText = state.playback.radio_station;
    if (artistEl) artistEl.innerText = '24/7 Continuous Live Radio';
    if (imgEl) imgEl.src = (state.playback.active_radio_info && state.playback.active_radio_info.favicon) || 'https://files.catbox.moe/74l9su.png';
  } else {
    if (titleEl) titleEl.innerText = 'Nothing is playing';
    if (artistEl) artistEl.innerText = 'Select a server or start with /play';
    if (imgEl) imgEl.src = 'https://files.catbox.moe/74l9su.png';
  }

  // Play/Pause icon toggle
  if (playPauseIcon) {
    if (state.playback.is_playing && !state.playback.is_paused) {
      playPauseIcon.setAttribute('data-lucide', 'pause');
    } else {
      playPauseIcon.setAttribute('data-lucide', 'play');
    }
  }

  if (volumeSlider) volumeSlider.value = state.playback.volume;
  if (queueBadge) queueBadge.innerText = `Queue (${state.playback.queue_size || state.playback.queue.length})`;
  if (serverLabel) serverLabel.innerText = state.playback.server_name || 'Server';

  // Loop button styling
  const loopBtn = document.getElementById('player-btn-loop');
  if (loopBtn) {
    if (state.playback.repeat_mode !== 'off') {
      loopBtn.className = 'text-brand-secondary p-1 font-bold';
    } else {
      loopBtn.className = 'text-[#9E9EAD] hover:text-white p-1';
    }
  }

  // Autoplay toggle button state
  const apBtn = document.getElementById('audia-autoplay-toggle-btn');
  if (apBtn) {
    if (state.playback.autoplay) {
      apBtn.className = 'px-5 py-2 rounded-xl text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30 transition-all';
      apBtn.innerText = 'AutoPlay Active ✓';
    } else {
      apBtn.className = 'px-5 py-2 rounded-xl text-xs font-bold bg-brand-primary text-white hover:bg-purple-600 transition-all';
      apBtn.innerText = 'Enable AutoPlay';
    }
  }

  renderTimelineOnly();
}

function renderSpotlightCard() {
  const titleEl = document.getElementById('spotlight-track-title');
  const artistEl = document.getElementById('spotlight-track-artist');
  const imgEl = document.getElementById('spotlight-track-img');
  const playBtnText = document.getElementById('spotlight-play-btn-text');
  const statusLabel = document.getElementById('spotlight-status-label');

  const track = state.playback.current_track;
  if (track) {
    if (titleEl) titleEl.innerText = track.title;
    if (artistEl) artistEl.innerText = `${track.author || 'Artist'} • ${state.playback.channel_name || 'Voice Channel'}`;
    if (imgEl) imgEl.src = track.thumbnail || 'https://files.catbox.moe/74l9su.png';
    if (statusLabel) statusLabel.innerText = state.playback.is_paused ? 'Paused' : 'Live On Discord';
    if (playBtnText) playBtnText.innerText = state.playback.is_paused ? 'Resume' : 'Pause';
  } else if (state.playback.radio_station) {
    if (titleEl) titleEl.innerText = state.playback.radio_station;
    if (artistEl) artistEl.innerText = `Live Worldwide Radio • ${state.playback.channel_name || 'Voice Channel'}`;
    if (imgEl) imgEl.src = (state.playback.active_radio_info && state.playback.active_radio_info.favicon) || 'https://files.catbox.moe/74l9su.png';
    if (statusLabel) statusLabel.innerText = '24/7 Live Radio';
    if (playBtnText) playBtnText.innerText = state.playback.is_paused ? 'Resume' : 'Pause';
  } else {
    if (titleEl) titleEl.innerText = 'Music is currently idle';
    if (artistEl) artistEl.innerText = 'Select a station or enter any song name above to start listening';
    if (imgEl) imgEl.src = 'https://files.catbox.moe/74l9su.png';
    if (statusLabel) statusLabel.innerText = 'Ready';
    if (playBtnText) playBtnText.innerText = 'Play Lo-Fi';
  }
}

function renderQueueDrawer() {
  const listEl = document.getElementById('queue-drawer-list');
  if (!listEl) return;
  listEl.innerHTML = '';

  // Current playing header card in drawer
  if (state.playback.current_track) {
    const curr = state.playback.current_track;
    const currDiv = document.createElement('div');
    currDiv.className = 'p-3 rounded-2xl bg-brand-primary/10 border border-brand-primary/30 mb-2';
    currDiv.innerHTML = `
      <div class="flex items-center gap-3">
        <img src="${curr.thumbnail || 'https://files.catbox.moe/74l9su.png'}" class="w-10 h-10 rounded-xl object-cover shrink-0">
        <div class="min-w-0 flex-1">
          <span class="text-[10px] font-bold text-brand-secondary uppercase tracking-wider">Now Playing</span>
          <p class="font-bold text-xs text-white truncate">${escapeHtml(curr.title)}</p>
          <p class="text-[11px] text-[#9E9EAD] truncate">${escapeHtml(curr.author || 'Artist')}</p>
        </div>
      </div>
    `;
    listEl.appendChild(currDiv);
  }

  // AutoPlay Up Next Prediction Card
  if (state.playback.autoplay && (state.playback.prefetched_track || state.playback.autoplay_meta)) {
    const pref = state.playback.prefetched_track;
    const meta = state.playback.autoplay_meta;
    const apDiv = document.createElement('div');
    apDiv.className = 'p-3 rounded-2xl bg-[#1b1926] border border-amber-500/30 mb-2';
    apDiv.innerHTML = `
      <div class="flex items-center gap-2 mb-1.5">
        <i data-lucide="sparkles" class="w-3.5 h-3.5 text-amber-400"></i>
        <span class="text-[10px] font-bold text-amber-300 uppercase tracking-wider">Audia AI AutoPlay Up Next</span>
      </div>
      <p class="font-bold text-xs text-white truncate">${pref ? escapeHtml(pref.title) : 'Smart Selection'}</p>
      <p class="text-[11px] text-[#9E9EAD] truncate">${pref ? escapeHtml(pref.author) : 'Diverse Match'}</p>
      ${meta && meta.reason ? `<p class="text-[10px] text-amber-200/80 mt-1 italic leading-tight">"${escapeHtml(meta.reason)}"</p>` : ''}
    `;
    listEl.appendChild(apDiv);
  }

  // Queue tracks
  if (!state.playback.queue || state.playback.queue.length === 0) {
    if (!state.playback.current_track) {
      listEl.innerHTML += '<div class="text-center py-10 text-[#6B6A78] text-xs">No upcoming tracks in queue.<br>Use <code>/play</code> in Discord or search above.</div>';
    }
    return;
  }

  state.playback.queue.forEach((t, i) => {
    const div = document.createElement('div');
    div.className = 'flex items-center gap-3 p-2.5 rounded-xl bg-brand-surface/70 border border-brand-border/30 hover:border-brand-primary/50 text-xs transition-colors';
    div.innerHTML = `
      <span class="font-mono text-[#6B6A78] w-4 text-center shrink-0">${i + 1}</span>
      <img src="${t.thumbnail || 'https://files.catbox.moe/74l9su.png'}" class="w-9 h-9 rounded-lg object-cover shrink-0">
      <div class="min-w-0 flex-1">
        <p class="font-semibold text-white truncate">${escapeHtml(t.title)}</p>
        <p class="text-[11px] text-[#9E9EAD] truncate">${escapeHtml(t.author || 'Artist')}</p>
      </div>
      <span class="font-mono text-[11px] text-[#6B6A78] shrink-0">${t.formatted_duration || ''}</span>
      <button onclick="removeQueueTrack(${i})" class="text-[#9E9EAD] hover:text-rose-400 p-1" title="Remove">
        <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
      </button>
    `;
    listEl.appendChild(div);
  });
}

function toggleQueueDrawer() {
  const drawer = document.getElementById('queue-drawer');
  if (drawer) drawer.classList.toggle('translate-x-full');
  initIcons();
}

// ------------------- PLAYER CONTROLS & COMMANDS -------------------
async function sendControlAction(action, payload = {}) {
  if (!state.activeGuildId) {
    showToast('Please select a Discord server first in the top bar!', 'warning');
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
  } else if (state.playback.is_paused) {
    sendControlAction('resume');
  } else {
    // If idle, quick start lo-fi
    tunePresetRadio('lofi');
  }
}

function controlPlayer(action) {
  sendControlAction(action);
}

function removeQueueTrack(index) {
  sendControlAction('remove_track', { index });
}

function handleSeek(e) {
  if (state.playback.duration <= 0) return;
  const bar = e.currentTarget;
  const rect = bar.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const pct = Math.max(0, Math.min(1, clickX / rect.width));
  const targetSec = Math.floor(pct * state.playback.duration);
  state.playback.position = targetSec;
  renderTimelineOnly();
}

function changeVolume(val) {
  clearTimeout(state.debounceTimer);
  state.debounceTimer = setTimeout(() => {
    sendControlAction('volume', { volume: parseInt(val) });
  }, 100);
}

function toggleMute() {
  const volumeSlider = document.getElementById('player-volume-slider');
  const iconVolume = document.getElementById('icon-volume');
  if (state.playback.volume > 0) {
    state.mutedBeforeVolume = state.playback.volume;
    changeVolume(0);
    if (volumeSlider) volumeSlider.value = 0;
    if (iconVolume) iconVolume.setAttribute('data-lucide', 'volume-x');
  } else {
    const restore = state.mutedBeforeVolume || 100;
    changeVolume(restore);
    if (volumeSlider) volumeSlider.value = restore;
    if (iconVolume) iconVolume.setAttribute('data-lucide', 'volume-2');
  }
  initIcons();
}

function cycleLoopMode() {
  const modes = ['off', 'track', 'queue'];
  const next = modes[(modes.indexOf(state.playback.repeat_mode) + 1) % modes.length];
  sendControlAction('loop', { mode: next });
  showToast(`Repeat mode: ${next.toUpperCase()}`, 'info');
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

function toggleServerAutoplay() {
  sendControlAction('autoplay', { enabled: !state.playback.autoplay });
}

async function toggleLikeCurrentTrack() {
  const track = state.playback.current_track;
  if (!track) {
    showToast('Nothing is currently playing to favorite!', 'warning');
    return;
  }
  try {
    await fetch('/api/library/favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_type: 'song',
        item_id: track.url || track.title,
        title: track.title,
        subtitle: track.author || 'Artist',
        image_url: track.thumbnail,
        url: track.url
      })
    });
    // Send feedback to Audia AI engine
    await fetch('/api/audia/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'like',
        artist: track.author,
        track_title: track.title
      })
    });
    showToast(`Added "${track.title}" to My Library!`, 'success');
  } catch (err) {
    showToast('Failed to save favorite: ' + err, 'error');
  }
}

// ------------------- SERVER SELECTOR & SERVERS VIEW -------------------
async function loadServers() {
  try {
    const res = await fetch('/api/servers');
    const data = await res.json();
    state.servers = data.servers || [];

    const dropdownList = document.getElementById('server-dropdown-list');
    if (dropdownList) dropdownList.innerHTML = '';

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
        if (dropdownList) dropdownList.appendChild(item);
      });

      const active = state.servers.find(s => s.id === state.activeGuildId) || state.servers[0];
      selectServer(active.id, false);
    } else {
      const activeName = document.getElementById('active-server-name');
      if (activeName) activeName.innerText = 'No Servers';
    }

    // Update Overview Stats
    const statGuilds = document.getElementById('stat-guilds');
    if (statGuilds) statGuilds.innerText = state.servers.length;
    let totalListeners = state.servers.reduce((acc, s) => acc + (s.listeners || 0), 0);
    const statListeners = document.getElementById('stat-listeners');
    if (statListeners) statListeners.innerText = totalListeners;

    const statRadio = document.getElementById('stat-radio');
    if (statRadio) {
      let activeRadioCount = state.servers.filter(s => s.radio_station).length;
      statRadio.innerText = activeRadioCount;
    }
  } catch (err) {
    console.warn('Servers load error:', err);
  }
}

function toggleServerDropdown() {
  const dd = document.getElementById('server-dropdown');
  if (dd) dd.classList.toggle('hidden');
}

function selectServer(guildId, fetchNow = true) {
  state.activeGuildId = guildId;
  const s = state.servers.find(srv => srv.id === guildId);
  if (s) {
    const activeName = document.getElementById('active-server-name');
    const activeIcon = document.getElementById('active-server-icon');
    if (activeName) activeName.innerText = s.name;
    if (activeIcon) activeIcon.src = s.icon;
  }
  const dd = document.getElementById('server-dropdown');
  if (dd) dd.classList.add('hidden');
  subscribeToGuild(guildId);
}

function loadServersView() {
  const container = document.getElementById('servers-full-list');
  if (!container) return;
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
            <span class="font-semibold ${s.connected ? 'text-emerald-400' : 'text-[#6B6A78]'}">${s.connected ? 'Streaming in ' + (s.voice_channel || 'Voice') : 'Idle'}</span>
          </p>
          <p class="flex items-center justify-between">
            <span>Listeners:</span>
            <span class="font-semibold text-white">${s.listeners || 0}</span>
          </p>
          ${s.current_track ? `<p class="truncate text-[11px] text-brand-secondary"><i data-lucide="music" class="w-3 h-3 inline"></i> ${escapeHtml(s.current_track)}</p>` : ''}
          ${s.radio_station ? `<p class="truncate text-[11px] text-purple-400"><i data-lucide="radio" class="w-3 h-3 inline"></i> ${escapeHtml(s.radio_station)}</p>` : ''}
        </div>
      </div>
      <div class="flex items-center gap-2 pt-2 border-t border-brand-border/20">
        <button onclick="selectServer('${s.id}')" class="flex-1 py-2 rounded-xl text-xs font-bold bg-brand-primary/20 text-brand-secondary hover:bg-brand-primary hover:text-white transition-all">
          Connect Dashboard
        </button>
        ${s.can_manage ? `
          <button onclick="openServerSettings('${s.id}')" class="p-2 rounded-xl bg-brand-surface border border-brand-border/40 hover:text-white text-[#9E9EAD]" title="Server Settings">
            <i data-lucide="settings" class="w-4 h-4"></i>
          </button>
        ` : ''}
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
    if (!card) return;
    card.classList.remove('hidden');

    const s = state.servers.find(srv => srv.id === guildId);
    document.getElementById('settings-server-name').innerText = `${s ? s.name : 'Server'} Settings`;

    const chanSelect = document.getElementById('setting-music-channel');
    chanSelect.innerHTML = '<option value="">All Channels Allowed</option>';
    (data.available_channels || []).forEach(c => {
      chanSelect.innerHTML += `<option value="${c.id}" ${data.music_channel_id === c.id ? 'selected' : ''}>#${escapeHtml(c.name)}</option>`;
    });

    const voiceSelect = document.getElementById('setting-voice-channel');
    voiceSelect.innerHTML = '<option value="">Auto-Detect Non-Empty Voice</option>';
    (data.available_voice_channels || []).forEach(vc => {
      voiceSelect.innerHTML += `<option value="${vc.id}" ${data.default_voice_channel_id === vc.id ? 'selected' : ''}>🔊 ${escapeHtml(vc.name)}</option>`;
    });

    const roleSelect = document.getElementById('setting-dj-role');
    roleSelect.innerHTML = '<option value="">No DJ Role Restriction</option>';
    (data.available_roles || []).forEach(r => {
      roleSelect.innerHTML += `<option value="${r.id}" ${data.dj_role_id === r.id ? 'selected' : ''}>@${escapeHtml(r.name)}</option>`;
    });

    document.getElementById('setting-max-volume').value = data.max_volume || 100;
    document.getElementById('setting-max-vol-val').innerText = (data.max_volume || 100) + '%';
    document.getElementById('setting-autoplay').checked = Boolean(data.autoplay_enabled);
    document.getElementById('setting-247').checked = Boolean(data.is_247);
    document.getElementById('setting-announcements').checked = Boolean(data.announcements_enabled);
    document.getElementById('setting-playback-notifs').checked = Boolean(data.playback_notifications);

    card.scrollIntoView({ behavior: 'smooth' });
  } catch (err) {
    showToast('Failed to load settings: ' + err, 'error');
  }
}

function closeServerSettings() {
  const card = document.getElementById('server-settings-card');
  if (card) card.classList.add('hidden');
}

async function saveServerSettings() {
  if (!state.activeGuildId) return;
  const music_channel_id = document.getElementById('setting-music-channel').value;
  const default_voice_channel_id = document.getElementById('setting-voice-channel').value;
  const dj_role_id = document.getElementById('setting-dj-role').value;
  const max_volume = parseInt(document.getElementById('setting-max-volume').value);
  const autoplay_enabled = document.getElementById('setting-autoplay').checked;
  const is_247 = document.getElementById('setting-247').checked;
  const announcements_enabled = document.getElementById('setting-announcements').checked;
  const playback_notifications = document.getElementById('setting-playback-notifs').checked;

  try {
    const res = await fetch(`/api/servers/${state.activeGuildId}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        music_channel_id,
        default_voice_channel_id,
        dj_role_id,
        max_volume,
        autoplay_enabled,
        is_247,
        announcements_enabled,
        playback_notifications
      })
    });
    if (res.ok) {
      showToast('Server settings successfully updated!', 'success');
      closeServerSettings();
      loadServers();
    } else {
      const err = await res.json();
      showToast(err.error || 'Permission denied', 'error');
    }
  } catch (err) {
    showToast('Failed to save settings: ' + err, 'error');
  }
}

// ------------------- VIEW 1: OVERVIEW DATA -------------------
async function loadOverviewData() {
  // Load AI recommendations
  try {
    const res = await fetch('/api/audia/recommendations');
    const data = await res.json();
    const container = document.getElementById('overview-recs-grid');
    if (container) {
      container.innerHTML = '';
      (data.recommendations || []).slice(0, 6).forEach(rec => {
        const card = document.createElement('div');
        card.className = 'glass-card-interactive p-4 flex flex-col justify-between';
        card.innerHTML = `
          <div>
            <div class="flex items-center justify-between mb-2">
              <span class="text-[10px] font-bold px-2 py-0.5 rounded-full badge-violet uppercase">${escapeHtml(rec.genre || 'Pop')}</span>
              <span class="text-[10px] text-amber-400 font-semibold flex items-center gap-1">
                <i data-lucide="sparkles" class="w-3 h-3"></i> ${Math.round((rec.confidence || 0.9) * 100)}% match
              </span>
            </div>
            <h4 class="font-bold text-sm text-white truncate">${escapeHtml(rec.title)}</h4>
            <p class="text-[11px] text-[#9E9EAD] truncate">${escapeHtml(rec.artist)}</p>
            <p class="text-[10px] text-[#6B6A78] mt-2 line-clamp-2 italic">"${escapeHtml(rec.reason)}"</p>
          </div>
          <div class="flex items-center gap-2 mt-3 pt-2.5 border-t border-brand-border/20">
            <button onclick="sendControlAction('play', { query: '${escapeHtml(rec.artist + ' - ' + rec.title)}' })" class="flex-1 py-1.5 rounded-lg text-xs font-bold bg-brand-primary/20 text-brand-secondary hover:bg-brand-primary hover:text-white transition-all flex items-center justify-center gap-1">
              <i data-lucide="play" class="w-3 h-3 fill-current"></i> Play
            </button>
            <button onclick="bookmarkSong('${escapeHtml(rec.title)}', '${escapeHtml(rec.artist)}')" class="p-1.5 rounded-lg bg-brand-surface border border-brand-border/30 text-[#9E9EAD] hover:text-rose-400" title="Favorite">
              <i data-lucide="heart" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        `;
        container.appendChild(card);
      });
    }
  } catch (e) {
    console.warn('Overview recs error:', e);
  }

  // Load recently played tracks
  try {
    const res = await fetch('/api/history?limit=4');
    const data = await res.json();
    const container = document.getElementById('overview-recent-tracks');
    if (container) {
      container.innerHTML = '';
      (data.history || []).forEach(h => {
        const card = document.createElement('div');
        card.className = 'glass-card-interactive p-3.5 flex items-center gap-3';
        card.innerHTML = `
          <img src="${h.thumbnail_url || 'https://files.catbox.moe/74l9su.png'}" class="w-11 h-11 rounded-xl object-cover shrink-0">
          <div class="min-w-0 flex-1">
            <h4 class="font-bold text-xs text-white truncate">${escapeHtml(h.track_title)}</h4>
            <p class="text-[11px] text-[#9E9EAD] truncate">${escapeHtml(h.track_author || 'Artist')}</p>
          </div>
          <button onclick="sendControlAction('play', { query: '${escapeHtml(h.track_title)}' })" class="p-2 rounded-xl bg-brand-primary/20 text-brand-secondary hover:bg-brand-primary hover:text-white" title="Replay">
            <i data-lucide="play" class="w-3.5 h-3.5 fill-current"></i>
          </button>
        `;
        container.appendChild(card);
      });
    }
  } catch (e) {
    console.warn('Overview history error:', e);
  }
}

// ------------------- VIEW 2: RADIO & DISCOVER -------------------
async function loadRadioView() {
  await loadRadioCountries();
  await loadRadioGenres();
  await loadRadioStations(state.activeRadioCountry);
}

function switchRadioTab(tab) {
  state.activeRadioCategory = tab;
  ['countries', 'popular', 'trending'].forEach(t => {
    const el = document.getElementById(`rtab-${t}`);
    if (el) {
      if (t === tab) {
        el.className = 'px-4 py-1.5 rounded-xl text-xs font-bold bg-brand-primary text-white';
      } else {
        el.className = 'px-4 py-1.5 rounded-xl text-xs font-semibold bg-brand-surface text-[#9E9EAD] hover:text-white';
      }
    }
  });

  const countriesBar = document.getElementById('radio-countries-bar');
  if (tab === 'countries') {
    if (countriesBar) countriesBar.classList.remove('hidden');
    loadRadioStations(state.activeRadioCountry);
  } else if (tab === 'popular') {
    if (countriesBar) countriesBar.classList.add('hidden');
    loadPopularRadio();
  } else if (tab === 'trending') {
    if (countriesBar) countriesBar.classList.add('hidden');
    loadTrendingRadio();
  }
}

async function loadRadioCountries() {
  try {
    const res = await fetch('/api/radio/countries');
    const data = await res.json();
    state.radioCountries = data.countries || [];

    const bar = document.getElementById('radio-countries-bar');
    if (!bar) return;
    bar.innerHTML = '';

    state.radioCountries.slice(0, 30).forEach(c => {
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

async function loadRadioGenres() {
  try {
    const res = await fetch('/api/radio/genres');
    const data = await res.json();
    const bar = document.getElementById('radio-genres-bar');
    if (!bar) return;
    bar.innerHTML = '';

    const allBtn = document.createElement('button');
    allBtn.className = !state.activeRadioGenre
      ? 'px-3 py-1 rounded-lg text-xs font-bold bg-brand-primary/30 text-brand-secondary border border-brand-primary/50 shrink-0'
      : 'px-3 py-1 rounded-lg text-xs font-semibold bg-brand-surface text-[#9E9EAD] hover:text-white border border-brand-border/40 shrink-0';
    allBtn.innerText = 'All Genres';
    allBtn.onclick = () => {
      state.activeRadioGenre = '';
      loadRadioGenres();
      loadRadioStations(state.activeRadioCountry);
    };
    bar.appendChild(allBtn);

    (data.genres || []).slice(0, 15).forEach(g => {
      const btn = document.createElement('button');
      const isSelected = g.name.toLowerCase() === state.activeRadioGenre.toLowerCase();
      btn.className = isSelected
        ? 'px-3 py-1 rounded-lg text-xs font-bold bg-brand-primary/30 text-brand-secondary border border-brand-primary/50 shrink-0'
        : 'px-3 py-1 rounded-lg text-xs font-semibold bg-brand-surface text-[#9E9EAD] hover:text-white border border-brand-border/40 shrink-0';
      btn.innerText = `#${g.name}`;
      btn.onclick = () => {
        state.activeRadioGenre = g.name;
        loadRadioGenres();
        loadRadioStations(state.activeRadioCountry, g.name);
      };
      bar.appendChild(btn);
    });
  } catch (e) {
    console.warn('Genres error:', e);
  }
}

async function loadRadioStations(country, genre = state.activeRadioGenre, query = '') {
  try {
    const sort = document.getElementById('radio-sort-select') ? document.getElementById('radio-sort-select').value : 'votes';
    const url = `/api/radio/stations?country=${encodeURIComponent(country)}&genre=${encodeURIComponent(genre)}&query=${encodeURIComponent(query)}&sort=${sort}&limit=60`;
    const res = await fetch(url);
    const data = await res.json();
    renderRadioCards(data.stations || []);
  } catch (err) {
    console.error('Radio stations load error:', err);
  }
}

async function loadPopularRadio() {
  try {
    const res = await fetch('/api/radio/popular');
    const data = await res.json();
    renderRadioCards(data.stations || []);
  } catch (err) {
    console.error('Popular radio error:', err);
  }
}

async function loadTrendingRadio() {
  try {
    const res = await fetch('/api/radio/trending');
    const data = await res.json();
    renderRadioCards(data.stations || []);
  } catch (err) {
    console.error('Trending radio error:', err);
  }
}

function renderRadioCards(stations) {
  const grid = document.getElementById('radio-stations-grid');
  if (!grid) return;
  grid.innerHTML = '';

  if (stations.length === 0) {
    grid.innerHTML = '<div class="col-span-full py-16 text-center text-[#6B6A78] text-xs">No radio stations matched your filters.</div>';
    return;
  }

  stations.forEach(st => {
    const card = document.createElement('div');
    card.className = 'glass-card-interactive p-4 flex flex-col justify-between';
    card.innerHTML = `
      <div>
        <div class="flex items-center gap-3 mb-2.5">
          <img src="${st.favicon}" class="w-10 h-10 rounded-xl object-cover border border-brand-border/40 shrink-0 bg-[#101014]">
          <div class="min-w-0 flex-1">
            <h4 class="font-bold text-sm truncate text-white">${escapeHtml(st.name)}</h4>
            <p class="text-[11px] text-[#9E9EAD] truncate">${escapeHtml(st.country || 'Global')} • ${escapeHtml(st.tags || 'Live')}</p>
          </div>
        </div>
        <div class="flex items-center gap-2 text-[10px] text-[#6B6A78] mb-3 font-mono">
          <span class="px-1.5 py-0.5 rounded bg-brand-surface border border-brand-border/30 text-white">${st.bitrate || 128} kbps</span>
          <span class="px-1.5 py-0.5 rounded bg-brand-surface border border-brand-border/30">${st.codec || 'MP3'}</span>
          <span class="ml-auto text-brand-secondary font-semibold"><i data-lucide="thumbs-up" class="w-3 h-3 inline"></i> ${st.votes || 0}</span>
        </div>
      </div>
      <div class="flex items-center gap-2 pt-2.5 border-t border-brand-border/20">
        <button onclick="tuneStation(${JSON.stringify(st).replace(/"/g, '&quot;')})" class="flex-1 py-1.5 rounded-lg text-xs font-bold bg-brand-primary/20 text-brand-secondary hover:bg-brand-primary hover:text-white transition-all flex items-center justify-center gap-1.5">
          <i data-lucide="radio" class="w-3.5 h-3.5"></i> Tune In
        </button>
        <button onclick="bookmarkStation(${JSON.stringify(st).replace(/"/g, '&quot;')})" class="p-1.5 rounded-lg bg-brand-surface border border-brand-border/30 text-[#9E9EAD] hover:text-rose-400" title="Bookmark">
          <i data-lucide="heart" class="w-3.5 h-3.5"></i>
        </button>
      </div>
    `;
    grid.appendChild(card);
  });
  initIcons();
}

function debounceRadioSearch() {
  clearTimeout(state.debounceTimer);
  state.debounceTimer = setTimeout(() => {
    const q = document.getElementById('radio-search-input').value.trim();
    loadRadioStations(state.activeRadioCountry, state.activeRadioGenre, q);
  }, 300);
}

async function tuneStation(st) {
  if (!state.activeGuildId) {
    showToast('Please select a Discord server first in the top bar!', 'warning');
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
    showToast(`Saved "${st.name}" to My Library!`, 'success');
  } catch (err) {
    showToast('Failed to save favorite: ' + err, 'error');
  }
}

async function bookmarkSong(title, artist) {
  try {
    await fetch('/api/library/favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_type: 'song',
        item_id: `${artist} - ${title}`,
        title: title,
        subtitle: artist,
        image_url: 'https://files.catbox.moe/74l9su.png',
        url: `https://www.youtube.com/results?search_query=${encodeURIComponent(artist + ' ' + title)}`
      })
    });
    showToast(`Added "${title}" to My Library!`, 'success');
  } catch (err) {
    showToast('Failed to save favorite: ' + err, 'error');
  }
}

// ------------------- VIEW 3: AUDIA AI STUDIO -------------------
async function loadAudiaView() {
  await loadAudiaProfile();
  await loadAudiaStudioRecommendations();
}

async function loadAudiaProfile() {
  try {
    const res = await fetch('/api/audia/profile');
    const data = await res.json();

    const dm = document.getElementById('audia-discovery-mode');
    if (dm) dm.value = data.discovery_mode || 'balanced';

    const gm = document.getElementById('audia-genre-mood');
    if (gm) gm.value = data.manual_mood ? `${data.manual_mood}|${data.manual_genre}` : '';

    const lang = document.getElementById('audia-language');
    if (lang) lang.value = data.manual_language || '';

    const artistsList = document.getElementById('audia-artists-list');
    if (artistsList) {
      artistsList.innerHTML = '';
      if (!data.top_artists || data.top_artists.length === 0) {
        artistsList.innerHTML = '<span class="text-xs text-[#6B6A78]">No learned artists yet. Stream songs in voice channels to continuously train Audia AI!</span>';
      } else {
        data.top_artists.forEach(a => {
          const badge = document.createElement('span');
          badge.className = 'inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-brand-surface border border-brand-border/40 text-xs font-medium text-white';
          badge.innerHTML = `
            <span>${escapeHtml(a.artist)}</span>
            <span class="text-[10px] font-bold text-brand-secondary bg-brand-primary/20 px-1.5 py-0.5 rounded-md font-mono">${a.affinity}</span>
            <button onclick="blockArtist('${escapeHtml(a.artist)}')" class="text-[#6B6A78] hover:text-rose-400" title="Block Artist">
              <i data-lucide="ban" class="w-3 h-3"></i>
            </button>
          `;
          artistsList.appendChild(badge);
        });
      }
    }
    initIcons();
  } catch (err) {
    console.warn('Audia load error:', err);
  }
}

async function loadAudiaStudioRecommendations() {
  try {
    const res = await fetch('/api/audia/recommendations');
    const data = await res.json();
    const container = document.getElementById('audia-recommendations-list');
    if (!container) return;
    container.innerHTML = '';

    (data.recommendations || []).forEach(r => {
      const card = document.createElement('div');
      card.className = 'glass-card-interactive p-4 flex flex-col justify-between';
      card.innerHTML = `
        <div>
          <div class="flex items-center justify-between mb-2">
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full badge-violet uppercase">${escapeHtml(r.genre || 'Smart')}</span>
            <span class="text-[11px] text-amber-400 font-semibold flex items-center gap-1 font-mono">
              <i data-lucide="sparkles" class="w-3 h-3"></i> ${Math.round((r.confidence || 0.92) * 100)}%
            </span>
          </div>
          <h4 class="font-bold text-sm text-white truncate">${escapeHtml(r.title)}</h4>
          <p class="text-xs text-[#9E9EAD] truncate">${escapeHtml(r.artist)}</p>
          <div class="p-2.5 rounded-xl bg-[#14131a] border border-brand-border/30 mt-3">
            <p class="text-[11px] text-brand-secondary leading-snug italic">"${escapeHtml(r.reason)}"</p>
          </div>
        </div>
        <div class="flex items-center gap-2 mt-4 pt-2.5 border-t border-brand-border/20">
          <button onclick="sendControlAction('play', { query: '${escapeHtml(r.artist + ' - ' + r.title)}' })" class="flex-1 py-1.5 rounded-lg text-xs font-bold bg-brand-primary text-white hover:bg-purple-600 transition-all flex items-center justify-center gap-1.5">
            <i data-lucide="play" class="w-3.5 h-3.5 fill-current"></i> Play Now
          </button>
          <button onclick="bookmarkSong('${escapeHtml(r.title)}', '${escapeHtml(r.artist)}')" class="p-2 rounded-lg bg-brand-surface border border-brand-border/30 text-[#9E9EAD] hover:text-rose-400" title="Favorite">
            <i data-lucide="heart" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      `;
      container.appendChild(card);
    });
    initIcons();
  } catch (e) {
    console.warn('Studio recs error:', e);
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
    showToast('Audia AI preferences updated!', 'success');
    loadAudiaStudioRecommendations();
  } catch (err) {
    showToast('Failed to update Audia settings: ' + err, 'error');
  }
}

async function blockArtist(artist) {
  try {
    await fetch('/api/audia/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'block', artist })
    });
    showToast(`Blocked "${artist}" from AI recommendations`, 'info');
    loadAudiaProfile();
  } catch (e) {
    console.error('Block artist error:', e);
  }
}

// ------------------- VIEW 4: MY LIBRARY & PLAYLISTS -------------------
async function loadLibraryView() {
  if (state.libraryTab === 'playlists') {
    document.getElementById('library-favorites-list').classList.add('hidden');
    document.getElementById('library-playlists-section').classList.remove('hidden');
    loadCustomPlaylists();
  } else {
    document.getElementById('library-favorites-list').classList.remove('hidden');
    document.getElementById('library-playlists-section').classList.add('hidden');
    loadLibraryFavorites();
  }
}

function switchLibraryTab(tab) {
  state.libraryTab = tab;
  ['all', 'song', 'radio', 'playlists'].forEach(t => {
    const el = document.getElementById(`lib-tab-${t}`);
    if (el) {
      if (t === tab) {
        el.className = 'px-4 py-1.5 rounded-xl text-xs font-bold bg-brand-primary text-white';
      } else {
        el.className = 'px-4 py-1.5 rounded-xl text-xs font-semibold bg-brand-surface text-[#9E9EAD] hover:text-white';
      }
    }
  });
  loadLibraryView();
}

async function loadLibraryFavorites() {
  try {
    const typeParam = state.libraryTab !== 'all' ? `?item_type=${state.libraryTab}` : '';
    const res = await fetch(`/api/library/favorites${typeParam}`);
    const data = await res.json();
    const container = document.getElementById('library-favorites-list');
    if (!container) return;
    container.innerHTML = '';

    if (!data.favorites || data.favorites.length === 0) {
      container.innerHTML = '<div class="col-span-full py-16 text-center text-[#6B6A78] text-xs">Your library is currently empty.<br>Click the heart icon on any song or radio station to bookmark it!</div>';
      return;
    }

    data.favorites.forEach(f => {
      const card = document.createElement('div');
      card.className = 'glass-panel p-4 rounded-2xl flex items-center justify-between gap-3';
      card.innerHTML = `
        <div class="flex items-center gap-3 min-w-0">
          <img src="${f.image_url || 'https://files.catbox.moe/74l9su.png'}" class="w-12 h-12 rounded-xl object-cover border border-brand-border/40 shrink-0">
          <div class="min-w-0">
            <h4 class="font-bold text-sm text-white truncate">${escapeHtml(f.title)}</h4>
            <p class="text-[11px] text-[#9E9EAD] truncate">${escapeHtml(f.subtitle || f.item_type)}</p>
          </div>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
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

async function loadCustomPlaylists() {
  try {
    const res = await fetch('/api/playlists');
    const data = await res.json();
    const container = document.getElementById('library-playlists-grid');
    if (!container) return;
    container.innerHTML = '';

    if (!data.playlists || data.playlists.length === 0) {
      container.innerHTML = '<div class="col-span-full py-16 text-center text-[#6B6A78] text-xs">No custom playlists created yet.<br>Click "+ New Playlist" above to start building a collection!</div>';
      return;
    }

    data.playlists.forEach(p => {
      const card = document.createElement('div');
      card.className = 'glass-panel p-5 rounded-2xl flex flex-col justify-between';
      card.innerHTML = `
        <div>
          <div class="w-12 h-12 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400 mb-3">
            <i data-lucide="list-music" class="w-6 h-6"></i>
          </div>
          <h4 class="font-bold text-base text-white truncate">${escapeHtml(p.name)}</h4>
          <p class="text-xs text-[#9E9EAD] mt-1 line-clamp-2">${escapeHtml(p.description || 'Custom Playlist')}</p>
          <p class="text-[11px] text-[#6B6A78] mt-2 font-mono">${p.track_count || 0} tracks</p>
        </div>
        <div class="flex items-center gap-2 mt-4 pt-3 border-t border-brand-border/20">
          <button onclick="deletePlaylist(${p.id})" class="p-2 rounded-xl text-[#9E9EAD] hover:text-rose-400" title="Delete Playlist">
            <i data-lucide="trash-2" class="w-4 h-4"></i>
          </button>
        </div>
      `;
      container.appendChild(card);
    });
    initIcons();
  } catch (e) {
    console.warn('Playlists error:', e);
  }
}

function openCreatePlaylistModal() {
  const modal = document.getElementById('modal-create-playlist');
  if (modal) modal.classList.remove('hidden');
}

function closeCreatePlaylistModal() {
  const modal = document.getElementById('modal-create-playlist');
  if (modal) modal.classList.add('hidden');
}

async function submitCreatePlaylist() {
  const name = document.getElementById('new-playlist-name').value.trim();
  const desc = document.getElementById('new-playlist-desc').value.trim();
  if (!name) {
    showToast('Please enter a playlist name!', 'warning');
    return;
  }
  try {
    const res = await fetch('/api/playlists', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description: desc })
    });
    if (res.ok) {
      showToast(`Created playlist "${name}"!`, 'success');
      closeCreatePlaylistModal();
      document.getElementById('new-playlist-name').value = '';
      document.getElementById('new-playlist-desc').value = '';
      loadCustomPlaylists();
    }
  } catch (err) {
    showToast('Failed to create playlist: ' + err, 'error');
  }
}

async function deletePlaylist(id) {
  try {
    await fetch(`/api/playlists/${id}`, { method: 'DELETE' });
    showToast('Playlist deleted', 'info');
    loadCustomPlaylists();
  } catch (e) {
    console.error('Delete playlist error:', e);
  }
}

// ------------------- VIEW 5: LISTENING HISTORY -------------------
async function loadListeningHistory() {
  try {
    const q = document.getElementById('history-search-input') ? document.getElementById('history-search-input').value.trim() : '';
    const res = await fetch(`/api/history?timeframe=${state.historyTimeframe}&query=${encodeURIComponent(q)}&limit=60`);
    const data = await res.json();
    const tbody = document.getElementById('history-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!data.history || data.history.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="py-12 text-center text-[#6B6A78]">No listening history recorded for this period.</td></tr>';
      return;
    }

    data.history.forEach(h => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-brand-surface/40 transition-colors';
      tr.innerHTML = `
        <td class="px-4 py-3 flex items-center gap-3">
          <img src="${h.thumbnail_url || 'https://files.catbox.moe/74l9su.png'}" class="w-8 h-8 rounded-lg object-cover shrink-0">
          <span class="font-medium text-white truncate max-w-xs">${escapeHtml(h.track_title)}</span>
        </td>
        <td class="px-4 py-3 text-[#9E9EAD] hidden sm:table-cell truncate max-w-xs">${escapeHtml(h.track_author || 'Artist')}</td>
        <td class="px-4 py-3 text-[#9E9EAD] hidden md:table-cell uppercase font-semibold text-[10px]">${escapeHtml(h.platform || 'audio')}</td>
        <td class="px-4 py-3 font-mono text-[#9E9EAD]">${formatDuration(h.duration)}</td>
        <td class="px-4 py-3 text-right text-[#6B6A78]">${h.played_at ? formatRelativeTime(h.played_at) : ''}</td>
        <td class="px-4 py-3 text-right">
          <button onclick="sendControlAction('play', { query: '${escapeHtml(h.track_title)}' })" class="text-brand-secondary hover:text-white p-1" title="Replay">
            <i data-lucide="play" class="w-3.5 h-3.5 fill-current"></i>
          </button>
          <button onclick="deleteHistoryItem(${h.id})" class="text-[#6B6A78] hover:text-rose-400 p-1" title="Delete">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
    initIcons();
  } catch (err) {
    console.warn('History load error:', err);
  }
}

function switchHistoryTimeframe(tf) {
  state.historyTimeframe = tf;
  ['all', '24h', '7d', '30d'].forEach(t => {
    const el = document.getElementById(`hist-tf-${t}`);
    if (el) {
      if (t === tf) {
        el.className = 'px-3.5 py-1.5 rounded-xl text-xs font-bold bg-brand-primary text-white';
      } else {
        el.className = 'px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-brand-surface text-[#9E9EAD] hover:text-white';
      }
    }
  });
  loadListeningHistory();
}

function debounceHistorySearch() {
  clearTimeout(state.debounceTimer);
  state.debounceTimer = setTimeout(loadListeningHistory, 300);
}

async function deleteHistoryItem(id) {
  try {
    await fetch(`/api/history/${id}`, { method: 'DELETE' });
    loadListeningHistory();
    showToast('Entry deleted', 'info');
  } catch (e) {
    console.error('Delete history error:', e);
  }
}

async function confirmClearHistory() {
  if (!confirm('Are you sure you want to clear your entire listening history? This cannot be undone.')) return;
  try {
    await fetch('/api/history/clear', { method: 'POST' });
    loadListeningHistory();
    showToast('Listening history cleared', 'info');
  } catch (e) {
    console.error('Clear history error:', e);
  }
}

// ------------------- VIEW 6: ANALYTICS -------------------
async function loadAnalytics() {
  try {
    const res = await fetch(`/api/analytics?timeframe=${state.analyticsTimeframe}`);
    const data = await res.json();

    document.getElementById('analytics-total-hours').innerText = `${data.total_hours || 0} hrs`;
    document.getElementById('analytics-total-tracks').innerText = data.total_tracks || 0;
    document.getElementById('analytics-peak-hour').innerText = data.peak_listening_hour || '--';

    // Render Hourly Distribution Bar Chart
    const chartContainer = document.getElementById('analytics-hourly-chart');
    if (chartContainer) {
      chartContainer.innerHTML = '';
      const distribution = data.hourly_distribution || new Array(24).fill(0);
      const maxVal = Math.max(...distribution, 1);

      distribution.forEach((count, hour) => {
        const heightPct = Math.max(8, Math.round((count / maxVal) * 100));
        const bar = document.createElement('div');
        bar.className = 'flex-1 rounded-t-md transition-all duration-300 hover:opacity-80 group relative cursor-pointer';
        bar.style.height = `${heightPct}%`;
        bar.style.backgroundColor = count > 0 ? (heightPct > 65 ? '#8055D9' : '#B9A2F2') : 'rgba(128, 85, 217, 0.15)';
        bar.innerHTML = `
          <div class="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2 py-1 bg-[#191820] border border-brand-border rounded-lg text-[10px] font-mono whitespace-nowrap z-30 shadow-xl">
            ${hour}:00 • ${count} plays
          </div>
        `;
        chartContainer.appendChild(bar);
      });
    }

    // Top Artists
    const artistsContainer = document.getElementById('analytics-top-artists');
    if (artistsContainer) {
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
    }

    // Top Tracks
    const tracksContainer = document.getElementById('analytics-top-tracks');
    if (tracksContainer) {
      tracksContainer.innerHTML = '';
      (data.top_tracks || []).forEach((t, i) => {
        const div = document.createElement('div');
        div.className = 'flex items-center justify-between p-3 rounded-xl bg-brand-surface/70 border border-brand-border/30 text-xs';
        div.innerHTML = `
          <div class="flex items-center gap-2.5 min-w-0">
            <span class="font-mono text-[#6B6A78] w-4">${i + 1}</span>
            <img src="${t.thumbnail_url || 'https://files.catbox.moe/74l9su.png'}" class="w-7 h-7 rounded-lg object-cover shrink-0">
            <span class="font-bold text-white truncate max-w-xs">${escapeHtml(t.track_title)}</span>
          </div>
          <span class="font-semibold text-brand-secondary shrink-0">${t.play_count} plays</span>
        `;
        tracksContainer.appendChild(div);
      });
    }
  } catch (err) {
    console.warn('Analytics error:', err);
  }
}

function switchAnalyticsTimeframe(tf) {
  state.analyticsTimeframe = tf;
  ['24h', '7d', '30d', '90d', 'all'].forEach(t => {
    const el = document.getElementById(`an-tf-${t}`);
    if (el) {
      if (t === tf) {
        el.className = 'px-3 py-1 rounded-lg font-bold bg-brand-primary text-white';
      } else {
        el.className = 'px-3 py-1 rounded-lg font-semibold text-[#9E9EAD] hover:text-white';
      }
    }
  });
  loadAnalytics();
}

// ------------------- VIEW 8: SYSTEM ADMIN -------------------
async function loadAdminDiagnostics() {
  try {
    const res = await fetch('/api/admin/status');
    if (!res.ok) {
      showToast('System Admin access restricted.', 'error');
      navigateTo('overview');
      return;
    }
    const data = await res.json();
    const container = document.getElementById('admin-details-grid');
    if (!container) return;

    container.innerHTML = `
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD] font-medium">Bot Gateway Status</p>
        <p class="text-2xl font-extrabold text-emerald-400 mt-1">${data.status.toUpperCase()}</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">${data.bot_name}</p>
      </div>
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD] font-medium">Gateway Latency</p>
        <p class="text-2xl font-extrabold text-brand-secondary mt-1">${data.latency_ms} ms</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">Discord WebSocket Heartbeat</p>
      </div>
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD] font-medium">Connected Discord Guilds</p>
        <p class="text-2xl font-extrabold text-white mt-1">${data.guilds}</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">Ecosystem servers</p>
      </div>
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD] font-medium">Active Voice Sessions</p>
        <p class="text-2xl font-extrabold text-purple-400 mt-1">${data.active_voice_sessions}</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">${data.total_voice_listeners || 0} active listeners</p>
      </div>
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD] font-medium">Active Radio Streams</p>
        <p class="text-2xl font-extrabold text-amber-400 mt-1">${data.active_radio_streams}</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">24/7 continuous audio</p>
      </div>
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD] font-medium">Web Clients (/ws)</p>
        <p class="text-2xl font-extrabold text-sky-400 mt-1">${data.web_clients}</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">Subscribed dashboard sockets</p>
      </div>
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD] font-medium">Host Platform</p>
        <p class="text-base font-bold text-white mt-1 truncate">${data.os || 'Windows'}</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">Python ${data.python_version || '3.11'}</p>
      </div>
      <div class="glass-panel p-5 rounded-2xl">
        <p class="text-xs text-[#9E9EAD] font-medium">RAM Utilization</p>
        <p class="text-2xl font-extrabold text-rose-400 mt-1">${data.memory ? data.memory.percent : 42}%</p>
        <p class="text-[11px] text-[#6B6A78] mt-1">${data.memory ? data.memory.used_mb : 512} MB used</p>
      </div>
    `;
  } catch (err) {
    console.warn('Admin status error:', err);
  }
}

// ------------------- USER PREFERENCES MODAL -------------------
function openPreferencesModal() {
  const modal = document.getElementById('modal-preferences');
  if (modal) modal.classList.remove('hidden');
  if (state.currentUser && state.currentUser.preferences) {
    const p = state.currentUser.preferences;
    if (document.getElementById('pref-timezone')) document.getElementById('pref-timezone').value = p.timezone || 'UTC';
    if (document.getElementById('pref-language')) document.getElementById('pref-language').value = p.language || 'en';
    if (document.getElementById('pref-private-listening')) document.getElementById('pref-private-listening').checked = Boolean(p.private_listening);
  }
}

function closePreferencesModal() {
  const modal = document.getElementById('modal-preferences');
  if (modal) modal.classList.add('hidden');
}

async function saveUserPreferences() {
  const timezone = document.getElementById('pref-timezone').value;
  const language = document.getElementById('pref-language').value;
  const private_listening = document.getElementById('pref-private-listening').checked;

  try {
    const res = await fetch('/api/user/preferences', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ timezone, language, private_listening })
    });
    if (res.ok) {
      showToast('Preferences updated successfully!', 'success');
      closePreferencesModal();
      if (state.currentUser) {
        state.currentUser.preferences = { timezone, language, private_listening };
      }
    }
  } catch (e) {
    showToast('Failed to save preferences: ' + e, 'error');
  }
}

// ------------------- UTILITIES & TOAST NOTIFICATIONS -------------------
function formatDuration(seconds) {
  if (!seconds || isNaN(seconds) || seconds < 0) return '00:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  const hrs = Math.floor(mins / 60);
  if (hrs > 0) {
    const remMins = mins % 60;
    return `${hrs}:${remMins < 10 ? '0' : ''}${remMins}:${secs < 10 ? '0' : ''}${secs}`;
  }
  return `${mins < 10 ? '0' : ''}${mins}:${secs < 10 ? '0' : ''}${secs}`;
}

function formatRelativeTime(dateStr) {
  try {
    const d = new Date(dateStr);
    const now = new Date();
    const diffSec = Math.floor((now - d) / 1000);
    if (diffSec < 60) return 'Just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch (e) {
    return dateStr;
  }
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast';
  
  let iconName = 'info';
  if (type === 'success') iconName = 'check-circle';
  else if (type === 'warning') iconName = 'alert-triangle';
  else if (type === 'error') iconName = 'alert-octagon';

  toast.innerHTML = `
    <i data-lucide="${iconName}" class="w-4 h-4 text-brand-secondary shrink-0"></i>
    <span class="truncate max-w-sm">${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);
  initIcons();

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}
