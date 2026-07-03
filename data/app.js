(function () {
  'use strict';

  const HISTORY_KEY = 'samovarHistoryV2';
  const HISTORY_LIMIT = 500;
  const COMMAND_TOKENS = {
    OK: { ok: true, level: 2, text: 'Команда принята.' },
    BUSY: { ok: false, level: 1, text: 'Устройство занято. Команда не принята.' },
    IGNORED: { ok: false, level: 1, text: 'Команда проигнорирована.' },
    POWER_OFF: { ok: false, level: 1, text: 'Нагрев выключен. Команда не принята.' },
    BAD_REQUEST: { ok: false, level: 0, text: 'Неверная команда.' }
  };

  let offlineCounter = 0;
  let offlineThreshold = 3;
  let isOffline = false;
  let messages = [];
  let historyShown = false;
  let soundEnabled = true;
  let soundPlaying = false;
  let audioBlockedNotified = false;
  let alarmActive = false;
  let sound = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function escapeHtml(value) {
    if (value === undefined || value === null) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function applyTheme(theme) {
    const root = document.documentElement;
    const toggle = byId('themeToggle');
    if (theme === 'dark') {
      root.setAttribute('data-theme', 'dark');
      if (toggle) toggle.textContent = '☼';
    } else {
      root.setAttribute('data-theme', 'light');
      if (toggle) toggle.textContent = '☾';
    }
  }

  function initTheme() {
    const saved = localStorage.getItem('theme');
    if (saved === 'dark' || saved === 'light') {
      applyTheme(saved);
      return;
    }
    applyTheme(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', next);
    applyTheme(next);
  }

  function openTab(evt, tabName) {
    const tabcontent = document.getElementsByClassName('tabcontent');
    for (let i = 0; i < tabcontent.length; i++) {
      tabcontent[i].style.display = 'none';
    }
    const tablinks = document.getElementsByClassName('tablinks');
    for (let i = 0; i < tablinks.length; i++) {
      tablinks[i].className = tablinks[i].className.replace(' active', '');
    }
    const tab = byId(tabName);
    if (tab) tab.style.display = 'block';
    if (evt && evt.currentTarget) evt.currentTarget.className += ' active';
  }

  function setConnectionIcon(fileName) {
    const indicator = byId('connection_indicator');
    if (!indicator) return;
    indicator.innerHTML = '<img src="' + fileName + '" style="margin: 0 !important; width: 20px">';
  }

  function initConnection(options) {
    offlineThreshold = options && options.threshold ? options.threshold : 3;
    setConnectionIcon('Green.png');
  }

  function setConnectionError() {
    if (offlineCounter < offlineThreshold) {
      offlineCounter++;
      return;
    }
    setConnectionIcon('Red_light.gif');
    addMessage('Обрыв связи!', 0);
    setTimeout(function () {
      isOffline = true;
      offlineCounter++;
    }, 100);
  }

  function setConnectionOk() {
    setConnectionIcon('Green.png');
    isOffline = false;
    if (offlineCounter >= offlineThreshold) playSound(false);
    offlineCounter = 0;
  }

  function getHistory() {
    try {
      const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
      return Array.isArray(parsed) ? parsed.slice(-HISTORY_LIMIT) : [];
    } catch (err) {
      console.log('History parse error:', err);
      return [];
    }
  }

  function saveHistory(entry) {
    const saved = getHistory();
    saved.push(entry);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(saved.slice(-HISTORY_LIMIT)));
  }

  function renderHistoryEntry(entry) {
    return '<div align="left" class="' + escapeHtml(entry.cssClass) + '" style="margin-top: 0">' +
      '<span style="text-decoration: underline">' + escapeHtml(entry.time) + '</span> ' +
      escapeHtml(entry.msg) + '</div>';
  }

  function showHistory() {
    const box = byId('historyBox');
    const list = byId('historyList');
    if (!box || !list) return;
    if (historyShown) {
      box.style.display = 'none';
      historyShown = false;
      return;
    }
    list.innerHTML = getHistory().map(renderHistoryEntry).join('');
    box.style.display = 'block';
    box.scrollTop = box.scrollHeight;
    historyShown = true;
  }

  function clearHistory() {
    localStorage.setItem(HISTORY_KEY, JSON.stringify([]));
    historyShown = false;
    showHistory();
  }

  function messageClass(level) {
    if (level === 1) return 'message_1';
    if (level === 2) return 'message_2';
    return 'message_0';
  }

  function renderMessage(entry, index) {
    const attrs = index === messages.length - 1 ? ' onclick="SamovarApp.removeLastMessage()" style="cursor: pointer;"' : '';
    return '<div align="left" class="' + escapeHtml(entry.cssClass) + '"' + attrs + '>' +
      escapeHtml(entry.time) + '  ' + escapeHtml(entry.msg) +
      '</div>';
  }

  function pushMessage(msg, level) {
    const time = new Date().toLocaleTimeString('ru-RU');
    const cssClass = messageClass(level);
    if (cssClass === 'message_0') alarmActive = true;
    const entry = { time: time, msg: String(msg), cssClass: cssClass };
    saveHistory(entry);
    messages.push(entry);
    showMessages();
  }

  function addMessage(msg, level) {
    if (isOffline) return;
    pushMessage(msg, level);
  }

  function notify(msg, level) {
    pushMessage(msg, level === undefined ? 1 : level);
  }

  function removeLastMessage() {
    messages.pop();
    alarmActive = messages.some(function (entry) { return entry.cssClass === 'message_0'; });
    showMessages();
  }

  function clearMessages() {
    messages = [];
    alarmActive = false;
    showMessages();
  }

  function showMessages() {
    const box = byId('messagesBox');
    const list = byId('messages');
    if (!box || !list) return;
    if (messages.length === 0) {
      box.style.display = 'none';
      playSound(false);
      return;
    }
    alarmActive = messages.some(function (entry) { return entry.cssClass === 'message_0'; });
    list.innerHTML = messages.map(renderMessage).join('');
    box.style.display = 'block';
    box.scrollTop = box.scrollHeight;
    if (soundEnabled && alarmActive) {
      playSound(true);
    } else {
      playSound(false);
    }
  }

  function ensureSound() {
    if (sound) return sound;
    sound = new Audio('alarm.mp3');
    sound.loop = true;
    sound.preload = 'auto';
    sound.autoplay = false;
    return sound;
  }

  function notifyAudioBlocked() {
    if (audioBlockedNotified) return;
    audioBlockedNotified = true;
    addMessage('Браузер заблокировал звук тревоги. Нажмите на страницу, чтобы разрешить звук.', 1);
  }

  function playSound(play) {
    const alarmSound = ensureSound();
    if (!soundPlaying && play) {
      const result = alarmSound.play();
      soundPlaying = true;
      if (result && typeof result.catch === 'function') {
        result.catch(function () {
          soundPlaying = false;
          notifyAudioBlocked();
        });
      }
    } else if (soundPlaying && !play) {
      alarmSound.pause();
      soundPlaying = false;
    }
  }

  function unlockAudio() {
    const alarmSound = ensureSound();
    alarmSound.play()
      .then(function () {
        alarmSound.pause();
        alarmSound.currentTime = 0;
        soundPlaying = false;
        audioBlockedNotified = false;
        if (soundEnabled && alarmActive) playSound(true);
      })
      .catch(function () {});
  }

  function setSoundEnabled(enabled) {
    soundEnabled = !!enabled;
    if (!soundEnabled) playSound(false);
  }

  async function fetchJson(url, options) {
    const ctrl = new AbortController();
    const timeout = options && options.timeout ? options.timeout : 4000;
    const timer = setTimeout(function () { ctrl.abort(); }, timeout);
    try {
      const resp = await fetch(url, { signal: ctrl.signal });
      clearTimeout(timer);
      if (!resp.ok) {
        setConnectionError();
        return null;
      }
      const data = await resp.json();
      setConnectionOk();
      return data;
    } catch (err) {
      clearTimeout(timer);
      setConnectionError();
      return null;
    }
  }

  async function pollAjax(renderFn) {
    const data = await fetchJson('/ajax');
    if (!data) return;
    try {
      renderFn(data);
    } catch (err) {
      reportUiError(err);
    }
  }

  function reportUiError(err) {
    console.log('UI update error:', err);
    addMessage('Ошибка обновления интерфейса: ' + (err && err.message ? err.message : err), 1);
  }

  function startPollLoop(fn, intervalMs) {
    (async function pollLoop() {
      await fn();
      setTimeout(pollLoop, intervalMs || 2000);
    })();
  }

  function commandResultText(token, body) {
    const entry = COMMAND_TOKENS[token];
    if (entry) return entry;
    return { ok: false, level: 0, text: body || 'Неизвестный ответ команды.' };
  }

  async function sendCommand(command, options) {
    try {
      const commandBody = command.indexOf('=') === -1 ? command + '=1' : command;
      const resp = await fetch('/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: commandBody
      });
      const body = (await resp.text()).trim();
      const token = body || (resp.ok ? 'OK' : '');
      const result = commandResultText(token, body);
      const knownToken = token && Object.prototype.hasOwnProperty.call(COMMAND_TOKENS, token);
      if (knownToken && result.ok) {
        addMessage(options && options.successMessage ? options.successMessage : result.text, 2);
        return true;
      }
      if (knownToken) {
        addMessage(result.text, result.level);
        return false;
      }
      if (!resp.ok) {
        addMessage('Ошибка команды HTTP ' + resp.status + ': ' + (body || resp.statusText), 0);
        return false;
      }
      addMessage(result.text, result.level);
      return false;
    } catch (err) {
      addMessage('Ошибка сети при отправке команды: ' + err, 0);
      return false;
    }
  }

  async function postProgram(form) {
    const resp = await fetch('/program', { method: 'POST', body: new FormData(form) });
    let result;
    try {
      result = await resp.json();
    } catch (err) {
      throw new Error('Некорректный JSON-ответ /program.');
    }
    if (!result || typeof result.ok !== 'boolean' ||
        typeof result.err !== 'string' ||
        typeof result.program !== 'string') {
      throw new Error('Некорректный контракт /program.');
    }
    if (!resp.ok && result.ok) {
      throw new Error('Некорректный HTTP-статус /program: ' + resp.status);
    }
    return result;
  }

  function addLuaButtons() {
    let btnList = '';
    const luaBtnEl = byId('samovar_lua_btn_list');
    if (luaBtnEl) {
      try {
        const parsed = JSON.parse(luaBtnEl.textContent || '""');
        if (typeof parsed === 'string') btnList = parsed;
      } catch (err) {
        btnList = '';
      }
    }
    if (btnList === '') return;
    const line = byId('lua_btn_ln');
    const block = byId('lua_btn');
    if (!line || !block) return;
    btnList.split(',').forEach(function (item, index) {
      if (item === '') return;
      const parts = item.split('|');
      const btn = document.createElement('input');
      btn.type = 'button';
      btn.name = 'luabtn' + index;
      btn.value = parts[1] || parts[0];
      btn.className = 'button';
      btn.addEventListener('click', function () { runLua(parts[0]); });
      line.appendChild(btn);
      block.style.visibility = 'visible';
    });
  }

  function runLua(num) {
    sendCommand('lua=' + encodeURIComponent(num));
  }

  function runLuaString() {
    const input = byId('lua_str_i');
    if (!input) return;
    sendCommand('luastr=' + encodeURIComponent(input.value));
  }

  function init(options) {
    initConnection(options || {});
    initTheme();
    document.addEventListener('click', unlockAudio, { once: true });
    document.addEventListener('keydown', unlockAudio, { once: true });
  }

  window.SamovarApp = {
    addLuaButtons: addLuaButtons,
    addMessage: addMessage,
    clearHistory: clearHistory,
    clearMessages: clearMessages,
    cssVar: cssVar,
    escapeHtml: escapeHtml,
    fetchJson: fetchJson,
    init: init,
    initTheme: initTheme,
    notify: notify,
    openTab: openTab,
    pollAjax: pollAjax,
    postProgram: postProgram,
    removeLastMessage: removeLastMessage,
    reportUiError: reportUiError,
    runLua: runLua,
    runLuaString: runLuaString,
    sendCommand: sendCommand,
    setConnectionError: setConnectionError,
    setConnectionOk: setConnectionOk,
    setSoundEnabled: setSoundEnabled,
    showHistory: showHistory,
    startPollLoop: startPollLoop,
    toggleTheme: toggleTheme
  };
})();
