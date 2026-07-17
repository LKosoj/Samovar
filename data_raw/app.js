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
  const DECIMAL_PATTERN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
  const INTEGER_PATTERN = /^[+-]?\d+$/;
  const FLOAT32_MIN_NORMAL = 1.1754943508222875e-38;
  const FLOAT32_MAX = 3.4028234663852886e38;
  const OPERATION_POLL_INTERVAL_MS = 250;
  const OPERATION_TIMEOUT_MS = 45000;
  const MAX_MESSAGE_SEQUENCE = 0xFFFFFFFF;
  const MESSAGE_GAP_WARNING = 'Пропущены сообщения: обнаружен разрыв последовательности.';
  const RUNTIME_BUSY_WARNING = 'Контроллер временно занят, статус обновится при следующем опросе.';
  const TELEMETRY_OPTION_KEYS = [
    'threshold', 'onReady', 'connectionIds', 'storeMessageHistory',
    'dynamicThemeTitle', 'implicitSystemTheme', 'onLastMessageRemoved'
  ];

  let offlineCounter = 0;
  let offlineThreshold = 3;
  let isOffline = false;
  let runtimeBusyCounter = 0;
  let messages = [];
  let historyShown = false;
  let soundEnabled = true;
  let soundPlaying = false;
  let audioBlockedNotified = false;
  let alarmActive = false;
  let heaterAlarmLatched = false;
  let sound = null;
  let requestErrorRevision = 0;
  let programMutationPending = false;
  let messageCursor = 0;
  let messageCursorBootstrapped = false;
  let telemetryRequestInFlight = false;
  let telemetryPageStarted = false;
  let connectionIds = null;
  let storeMessageHistory = true;
  let dynamicThemeTitle = false;
  let implicitSystemTheme = false;
  let onLastMessageRemoved = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function requiredI2cPumpElement(id) {
    const element = byId(id);
    if (!element) throw new Error('I2C pump UI contract: missing #' + id);
    return element;
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

  function requestErrorElement() {
    let element = byId('request_error');
    if (element) return element;
    element = document.createElement('div');
    element.id = 'request_error';
    element.className = 'message_0';
    element.setAttribute('role', 'alert');
    element.setAttribute('aria-live', 'assertive');
    element.style.display = 'none';
    element.style.margin = '0.75em auto';
    element.style.maxWidth = '60em';
    element.style.padding = '0.75em 1em';
    const host = document.querySelector('form') || document.body;
    host.insertBefore(element, host.firstChild);
    return element;
  }

  function showRequestError(message) {
    requestErrorRevision++;
    const element = requestErrorElement();
    element.textContent = String(message || 'Неверные данные запроса.');
    element.style.display = 'block';
  }

  function clearRequestError() {
    requestErrorRevision++;
    const element = byId('request_error');
    if (!element) return;
    element.textContent = '';
    element.style.display = 'none';
  }

  function currentRequestErrorRevision() {
    return requestErrorRevision;
  }

  function clearRequestErrorIfUnchanged(revision) {
    if (revision !== requestErrorRevision) return false;
    clearRequestError();
    return true;
  }

  function normalizedNumericText(value) {
    return String(value === undefined || value === null ? '' : value).replace(',', '.');
  }

  function validateNumericInput(inputOrId, options) {
    const input = typeof inputOrId === 'string' ? byId(inputOrId) : inputOrId;
    const spec = options || {};
    const label = spec.label || (input && (input.name || input.id)) || 'Значение';
    if (!input) {
      return { ok: false, error: 'Не найдено поле «' + label + '».' };
    }

    const normalized = normalizedNumericText(input.value);
    const pattern = spec.integer ? INTEGER_PATTERN : DECIMAL_PATTERN;
    let error = '';
    let value = 0;
    if (normalized === '') {
      error = 'Поле «' + label + '» не заполнено.';
    } else if (!pattern.test(normalized)) {
      error = 'Поле «' + label + '» должно содержать одно число.';
    } else {
      value = Number(normalized);
      const mantissa = normalized.split(/[eE]/, 1)[0];
      if (!Number.isFinite(value) || (value === 0 && /[1-9]/.test(mantissa))) {
        error = 'Поле «' + label + '» выходит за допустимый диапазон.';
      } else if (!spec.integer && value !== 0 &&
                 (Math.abs(value) < FLOAT32_MIN_NORMAL || Math.abs(value) > FLOAT32_MAX)) {
        error = 'Поле «' + label + '» не представимо точным числом контроллера.';
      } else if (spec.integer && !Number.isSafeInteger(value)) {
        error = 'Поле «' + label + '» должно содержать целое число.';
      } else if (spec.min !== undefined && value < spec.min) {
        error = 'Поле «' + label + '»: минимум ' + spec.min + '.';
      } else if (spec.exclusiveMin !== undefined && value <= spec.exclusiveMin) {
        error = 'Поле «' + label + '» должно быть больше ' + spec.exclusiveMin + '.';
      } else if (spec.max !== undefined && value > spec.max) {
        error = 'Поле «' + label + '»: максимум ' + spec.max + '.';
      } else if (spec.accept && !spec.accept(value)) {
        error = spec.acceptMessage || 'Поле «' + label + '» содержит недопустимое значение.';
      }
    }

    input.setAttribute('aria-invalid', error ? 'true' : 'false');
    if (error) return { ok: false, error: error };
    return { ok: true, number: value, text: normalized, input: input };
  }

  function readNumericInput(inputOrId, options) {
    const result = validateNumericInput(inputOrId, options);
    if (!result.ok) {
      showRequestError(result.error);
      return null;
    }
    result.input.value = result.text;
    return result;
  }

  function validateNumericFields(form, schema) {
    const validated = [];
    for (let i = 0; i < schema.length; i++) {
      const rule = schema[i];
      const input = form.elements[rule.name];
      const result = validateNumericInput(input, rule);
      if (!result.ok) {
        showRequestError(result.error);
        if (input && typeof input.focus === 'function') input.focus();
        return false;
      }
      validated.push(result);
    }
    validated.forEach(function (result) { result.input.value = result.text; });
    clearRequestError();
    return true;
  }

  async function responseErrorText(resp, prefix) {
    let detail = '';
    const contentType = resp.headers.get('Content-Type') || '';
    try {
      if (contentType.indexOf('application/json') !== -1) {
        const body = await resp.json();
        if (body && typeof body === 'object') {
          // Конверт ошибок отдаёт message человеку и error машине; старые ответы кладут
          // человеческий текст прямо в error, а код - в code. Показываем текст, код даём
          // в скобках: так обе формы рисуются одинаково, пока эндпоинты переезжают.
          detail = body.message || body.error || body.err || body.code || '';
          const code = body.code || (body.message ? body.error : '');
          if (code && detail !== code) detail += ' (' + code + ')';
        }
      } else {
        detail = (await resp.text()).trim();
      }
    } catch (err) {
      if (err && err.name === 'AbortError') throw err;
      detail = '';
    }
    return (prefix ? prefix + ': ' : '') + 'HTTP ' + resp.status +
      (detail ? ' — ' + detail : (resp.statusText ? ' — ' + resp.statusText : ''));
  }

  function systemTheme() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark' : 'light';
  }

  function applyTheme(theme, effectiveTheme) {
    const root = document.documentElement;
    const toggle = byId('themeToggle');
    if (theme === 'dark' || theme === 'light') {
      root.setAttribute('data-theme', theme);
    } else {
      root.removeAttribute('data-theme');
    }
    if (toggle) {
      const dark = (effectiveTheme || theme) === 'dark';
      toggle.textContent = dark ? '☼' : '☾';
      toggle.setAttribute('aria-label', dark ? 'Включить светлую тему' : 'Включить тёмную тему');
      toggle.setAttribute('aria-pressed', dark ? 'true' : 'false');
      if (dynamicThemeTitle) {
        toggle.title = dark ? 'Светлая тема' : 'Тёмная тема';
      }
    }
  }

  function initTheme(options) {
    const themeOptions = options || {};
    Object.keys(themeOptions).forEach(function (key) {
      if (key !== 'dynamicThemeTitle' && key !== 'implicitSystemTheme') {
        throw new Error('Неизвестная опция theme: ' + key);
      }
    });
    if (themeOptions.dynamicThemeTitle !== undefined &&
        typeof themeOptions.dynamicThemeTitle !== 'boolean') {
      throw new Error('dynamicThemeTitle должен быть boolean.');
    }
    if (themeOptions.implicitSystemTheme !== undefined &&
        typeof themeOptions.implicitSystemTheme !== 'boolean') {
      throw new Error('implicitSystemTheme должен быть boolean.');
    }
    dynamicThemeTitle = themeOptions.dynamicThemeTitle === true;
    implicitSystemTheme = themeOptions.implicitSystemTheme === true;

    let saved;
    if (implicitSystemTheme) {
      try {
        saved = localStorage.getItem('theme');
      } catch (err) {
        saved = null;
      }
    } else {
      saved = localStorage.getItem('theme');
    }
    if (saved === 'dark' || saved === 'light') {
      applyTheme(saved, saved);
      return;
    }
    const effectiveTheme = systemTheme();
    if (implicitSystemTheme) {
      applyTheme(null, effectiveTheme);
    } else {
      applyTheme(effectiveTheme, effectiveTheme);
    }
  }

  function toggleTheme() {
    const attributeTheme = document.documentElement.getAttribute('data-theme');
    const current = implicitSystemTheme && !attributeTheme
      ? systemTheme()
      : (attributeTheme === 'dark' ? 'dark' : 'light');
    const next = current === 'dark' ? 'light' : 'dark';
    if (implicitSystemTheme) {
      try {
        localStorage.setItem('theme', next);
      } catch (err) {
        applyTheme(next, next);
        return;
      }
    } else {
      localStorage.setItem('theme', next);
    }
    applyTheme(next, next);
  }

  function openTab(evt, tabName) {
    const tabcontent = document.getElementsByClassName('tabcontent');
    for (let i = 0; i < tabcontent.length; i++) {
      tabcontent[i].style.display = 'none';
      tabcontent[i].setAttribute('aria-hidden', 'true');
    }
    const tablinks = document.getElementsByClassName('tablinks');
    for (let i = 0; i < tablinks.length; i++) {
      tablinks[i].className = tablinks[i].className.replace(' active', '');
      if (tablinks[i].hasAttribute('aria-pressed')) {
        tablinks[i].setAttribute('aria-pressed', 'false');
      }
    }
    const tab = byId(tabName);
    if (tab && tab.classList.contains('tabcontent')) {
      tab.style.display = 'block';
      tab.setAttribute('aria-hidden', 'false');
    }
    if (evt && evt.currentTarget) {
      evt.currentTarget.className += ' active';
      if (evt.currentTarget.hasAttribute('aria-pressed')) {
        evt.currentTarget.setAttribute('aria-pressed', 'true');
      }
    }
  }

  function setConnectionIcon(fileName) {
    if (connectionIds) {
      const online = byId(connectionIds.online);
      const offline = byId(connectionIds.offline);
      const connected = fileName === 'Green.png';
      online.style = connected ? '' : 'visibility: hidden;position: fixed;';
      offline.style = connected ? 'visibility: hidden;position: fixed;' : '';
      return;
    }
    const indicator = byId('connection_indicator');
    if (!indicator) return;
    indicator.innerHTML = '<img src="' + fileName + '" style="margin: 0 !important; width: 20px">';
  }

  function initConnection(options) {
    offlineThreshold = options && options.threshold ? options.threshold : 3;
    connectionIds = options && options.connectionIds ? options.connectionIds : null;
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
      if (connectionIds) offlineCounter = 0;
      else offlineCounter++;
    }, 100);
  }

  function setConnectionOk() {
    setConnectionIcon('Green.png');
    isOffline = false;
    if (!connectionIds && offlineCounter >= offlineThreshold) playSound(false);
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
    const trigger = document.querySelector('.history-trigger');
    if (!box || !list) return;
    if (historyShown) {
      box.style.display = 'none';
      historyShown = false;
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
      return;
    }
    list.innerHTML = getHistory().map(renderHistoryEntry).join('');
    box.style.display = 'block';
    box.scrollTop = box.scrollHeight;
    historyShown = true;
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
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
    const content = escapeHtml(entry.time) + '  ' + escapeHtml(entry.msg);
    if (index === messages.length - 1) {
      return '<button type="button" class="' + escapeHtml(entry.cssClass) +
        ' message-dismiss" onclick="SamovarApp.removeLastMessage()">' + content + '</button>';
    }
    return '<div align="left" class="' + escapeHtml(entry.cssClass) + '">' + content + '</div>';
  }

  function pushMessage(msg, level) {
    const time = new Date().toLocaleTimeString('ru-RU');
    const cssClass = messageClass(level);
    const entry = { time: time, msg: String(msg), cssClass: cssClass };
    if (storeMessageHistory) saveHistory(entry);
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
    if (messages.length === 0) return;
    messages.pop();
    if (onLastMessageRemoved) onLastMessageRemoved(messages.length);
    showMessages();
  }

  function clearMessages() {
    messages = [];
    showMessages();
  }

  function updateHeaterAlarmLatched(latched) {
    heaterAlarmLatched = latched;
    showMessages();
  }

  function showMessages() {
    const box = byId('messagesBox');
    const list = byId('messages');
    // Сирена обязана отражать текущее реальное состояние аварии (heaterAlarmLatched),
    // а не только факт наличия сообщения в ленте - иначе бэклог-сообщение или сброс
    // тоста могут её заглушить/включить ложно. См. FAIL-SAFE в архитектурных заметках.
    alarmActive = heaterAlarmLatched ||
      messages.some(function (entry) { return entry.cssClass === 'message_0'; });
    if (box && list) {
      if (messages.length === 0) {
        box.style.display = 'none';
      } else {
        list.innerHTML = messages.map(renderMessage).join('');
        box.style.display = 'block';
        box.scrollTop = box.scrollHeight;
      }
    }
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

  function renderI2cPumpStatus(data) {
    const panel = requiredI2cPumpElement('i2c_pump_status');
    const status = requiredI2cPumpElement('i2c_status');
    const remaining = requiredI2cPumpElement('i2c_remaining');
    const speed = requiredI2cPumpElement('i2c_speed_cur');
    const present = data.i2c_pump_present === 1;

    panel.hidden = !present;
    status.textContent = present
      ? (data.i2c_pump_running === 1 ? 'Работает' : 'Остановлен')
      : 'Не подключён';
    remaining.textContent = present ? data.i2c_pump_remaining_ml : '0';
    speed.textContent = present ? data.i2c_pump_speed : '0';
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

  function validateRuntimeEvent(data) {
    const hasSequence = Object.prototype.hasOwnProperty.call(data, 'messageSequence');
    const hasMessage = Object.prototype.hasOwnProperty.call(data, 'Msg');
    const hasLog = Object.prototype.hasOwnProperty.call(data, 'LogMsg');
    const hasLevel = Object.prototype.hasOwnProperty.call(data, 'msglvl');

    if (!hasSequence) {
      if (hasMessage || hasLog || hasLevel) {
        throw new Error('Некорректный контракт runtime-сообщения.');
      }
      return null;
    }
    if (!Number.isInteger(data.messageSequence) ||
        data.messageSequence < 1 || data.messageSequence > MAX_MESSAGE_SEQUENCE ||
        hasMessage === hasLog) {
      throw new Error('Некорректный контракт runtime-сообщения.');
    }
    if (hasMessage) {
      if (!hasLevel || typeof data.Msg !== 'string' || data.Msg === '' ||
          !Number.isInteger(data.msglvl) || data.msglvl < 0 || data.msglvl > 255) {
        throw new Error('Некорректный контракт runtime-сообщения.');
      }
      return {
        kind: 'message',
        level: data.msglvl,
        sequence: data.messageSequence,
        text: data.Msg
      };
    }
    if (hasLevel || typeof data.LogMsg !== 'string' || data.LogMsg === '') {
      throw new Error('Некорректный контракт runtime-сообщения.');
    }
    return {
      kind: 'log',
      sequence: data.messageSequence,
      text: data.LogMsg
    };
  }

  function validateHeaterTelemetry(data) {
    if ((data.heaterAlarmLatched !== 0 && data.heaterAlarmLatched !== 1) ||
        !Number.isInteger(data.latestMessageSequence) ||
        data.latestMessageSequence < 0 || data.latestMessageSequence > MAX_MESSAGE_SEQUENCE) {
      throw new Error('Некорректный контракт heaterAlarmLatched/latestMessageSequence.');
    }
    return {
      heaterAlarmLatched: data.heaterAlarmLatched === 1,
      latestSequence: data.latestMessageSequence
    };
  }

  function resolvePollSinks(sinks) {
    if (sinks === undefined) {
      return {
        message: addMessage,
        log: function (text, data) { console.log(data.crnt_tm + '; ' + text); },
        connection: function (hasError) {
          if (hasError) setConnectionError();
          else setConnectionOk();
        }
      };
    }
    if (!sinks || typeof sinks.message !== 'function' ||
        typeof sinks.log !== 'function' || typeof sinks.connection !== 'function') {
      throw new Error('Некорректные обработчики telemetry poll.');
    }
    return sinks;
  }

  function nextMessageSequence(sequence) {
    return sequence === MAX_MESSAGE_SEQUENCE ? 1 : sequence + 1;
  }

  async function pollAjax(renderFn, sinks) {
    if (typeof renderFn !== 'function') {
      throw new Error('Не задан обработчик telemetry response.');
    }
    const activeSinks = resolvePollSinks(sinks);
    if (telemetryRequestInFlight) return false;
    telemetryRequestInFlight = true;
    const ctrl = new AbortController();
    const timer = setTimeout(function () { ctrl.abort(); }, 4000);
    try {
      let data;
      try {
        const resp = await fetch('/ajax?messageCursor=' + String(messageCursor), {
          cache: 'no-store',
          signal: ctrl.signal
        });
        if (resp.status === 503) {
          // Состояние контроллера временно занято (мьютекс/снапшот) - это не обрыв связи,
          // сервер жив и отвечает. Считаем такие ответы отдельно и не эскалируем как сбой.
          runtimeBusyCounter += 1;
          if (runtimeBusyCounter >= offlineThreshold) {
            runtimeBusyCounter = 0;
            activeSinks.message(RUNTIME_BUSY_WARNING, 1);
          }
          return false;
        }
        runtimeBusyCounter = 0;
        if (!resp.ok) {
          activeSinks.connection(true);
          return false;
        }
        data = await resp.json();
      } catch (err) {
        activeSinks.connection(true);
        return false;
      }

      let event;
      try {
        event = validateRuntimeEvent(data);
        const heaterTelemetry = validateHeaterTelemetry(data);
        activeSinks.connection(false);
        renderFn(data);
        if (!messageCursorBootstrapped) {
          // Бутстрап (первая загрузка страницы/вкладки): не переигрываем бэклог
          // кольцевого буфера по одному сообщению раз в 2 секунды - сразу переходим
          // на текущий конец очереди, как это уже делает reset_lua_message_cursor().
          // Признак бутстрапа - отдельный флаг, а не messageCursor === 0: на пустом
          // кольце latestSequence тоже 0, курсор не сдвигается, и первое в жизни
          // устройства событие попадало бы сюда же и молча терялось вместе с сиреной
          // (авария без защёлки, например захлёб, живёт только в тексте сообщения).
          messageCursor = heaterTelemetry.latestSequence;
          messageCursorBootstrapped = true;
        } else if (event) {
          if (event.sequence !== nextMessageSequence(messageCursor)) {
            activeSinks.message(MESSAGE_GAP_WARNING, 1);
          }
          if (event.kind === 'message') {
            activeSinks.message(event.text, event.level);
          } else {
            activeSinks.log(event.text, data);
          }
          messageCursor = event.sequence;
        }
        updateHeaterAlarmLatched(heaterTelemetry.heaterAlarmLatched);
        return true;
      } catch (err) {
        reportUiError(err, activeSinks.message);
        return false;
      }
    } finally {
      clearTimeout(timer);
      telemetryRequestInFlight = false;
    }
  }

  function reportUiError(err, messageSink) {
    console.log('UI update error:', err);
    (messageSink || addMessage)(
      'Ошибка обновления интерфейса: ' + (err && err.message ? err.message : err), 1
    );
  }

  function startPollLoop(fn, intervalMs) {
    (async function pollLoop() {
      await fn();
      setTimeout(pollLoop, intervalMs || 2000);
    })();
  }

  function startTelemetryPage(renderFn, options) {
    if (typeof renderFn !== 'function') {
      throw new Error('Не задан обработчик telemetry response.');
    }
    const pageOptions = options || {};
    Object.keys(pageOptions).forEach(function (key) {
      if (TELEMETRY_OPTION_KEYS.indexOf(key) === -1) {
        throw new Error('Неизвестная опция telemetry lifecycle: ' + key);
      }
    });
    if (pageOptions.threshold !== undefined &&
        (!Number.isInteger(pageOptions.threshold) || pageOptions.threshold < 1)) {
      throw new Error('threshold должен быть положительным целым числом.');
    }
    if (pageOptions.onReady !== undefined && typeof pageOptions.onReady !== 'function') {
      throw new Error('onReady должен быть функцией.');
    }
    if (pageOptions.storeMessageHistory !== undefined &&
        typeof pageOptions.storeMessageHistory !== 'boolean') {
      throw new Error('storeMessageHistory должен быть boolean.');
    }
    if (pageOptions.dynamicThemeTitle !== undefined &&
        typeof pageOptions.dynamicThemeTitle !== 'boolean') {
      throw new Error('dynamicThemeTitle должен быть boolean.');
    }
    if (pageOptions.implicitSystemTheme !== undefined &&
        typeof pageOptions.implicitSystemTheme !== 'boolean') {
      throw new Error('implicitSystemTheme должен быть boolean.');
    }
    if (pageOptions.onLastMessageRemoved !== undefined &&
        typeof pageOptions.onLastMessageRemoved !== 'function') {
      throw new Error('onLastMessageRemoved должен быть функцией.');
    }
    if (pageOptions.connectionIds !== undefined) {
      const ids = pageOptions.connectionIds;
      if (!ids || Object.keys(ids).length !== 2 ||
          typeof ids.online !== 'string' || typeof ids.offline !== 'string' ||
          !byId(ids.online) || !byId(ids.offline)) {
        throw new Error('Не найдены обязательные индикаторы telemetry connection.');
      }
    } else if (!byId('connection_indicator')) {
      throw new Error('Не найден обязательный #connection_indicator.');
    }
    if (telemetryPageStarted) {
      throw new Error('Telemetry lifecycle уже запущен.');
    }

    telemetryPageStarted = true;
    storeMessageHistory = pageOptions.storeMessageHistory !== false;
    onLastMessageRemoved = pageOptions.onLastMessageRemoved || null;
    init({
      threshold: pageOptions.threshold || 3,
      connectionIds: pageOptions.connectionIds,
      dynamicThemeTitle: pageOptions.dynamicThemeTitle === true,
      implicitSystemTheme: pageOptions.implicitSystemTheme === true
    });
    if (pageOptions.onReady) pageOptions.onReady();
    startPollLoop(function () { return pollAjax(renderFn); }, 2000);
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
      // Отказы приходят конвертом, где токен лежит в error; успех - по-прежнему текстом.
      // Читаем тело один раз и достаём из той формы, в которой оно пришло, две разные
      // вещи: token - чтобы распознать штатный отказ раньше общей HTTP-ошибки, detail -
      // чтобы показать человеку текст, а не сырой JSON.
      let token = body;
      let detail = body;
      if ((resp.headers.get('Content-Type') || '').indexOf('application/json') !== -1) {
        try {
          const parsed = JSON.parse(body);
          if (parsed && typeof parsed === 'object') {
            if (parsed.error) token = String(parsed.error);
            detail = parsed.message || parsed.error || body;
          }
        } catch (e) {
          // Битый JSON - оставляем тело как есть, ниже оно уйдёт в общую ветку HTTP-ошибки.
        }
      }
      token = token || (resp.ok ? 'OK' : '');
      const result = commandResultText(token, detail);
      const knownToken = token && Object.prototype.hasOwnProperty.call(COMMAND_TOKENS, token);
      if (knownToken && !result.ok) {
        // Штатный отказ (BUSY/IGNORED/POWER_OFF/BAD_REQUEST) распознаём по токену раньше
        // общей HTTP-ошибки: сервер шлёт такие ответы с кодами 429/409/503/400, и это не
        // критический сбой связи, а обычный временный отказ команды.
        showRequestError(result.text);
        addMessage(result.text, result.level);
        return false;
      }
      if (!resp.ok) {
        const errorText = 'Ошибка команды HTTP ' + resp.status + ': ' + (detail || resp.statusText);
        showRequestError(errorText);
        addMessage(errorText, 0);
        return false;
      }
      if (knownToken && result.ok) {
        clearRequestError();
        addMessage(options && options.successMessage ? options.successMessage : result.text, 2);
        return true;
      }
      addMessage(result.text, result.level);
      return false;
    } catch (err) {
      const errorText = 'Ошибка сети при отправке команды: ' + err;
      showRequestError(errorText);
      addMessage(errorText, 0);
      return false;
    }
  }

  async function sendNumericCommand(action, inputOrId, spec, options) {
    const result = readNumericInput(inputOrId, spec);
    if (!result) return false;
    return sendCommand(action + '=' + encodeURIComponent(result.text), options);
  }

  function sendPowerCommand(inputOrId, powerUnit, maxValue, options) {
    if (!Number.isFinite(maxValue) || maxValue <= 0) {
      showRequestError('Не получен допустимый предел мощности от контроллера.');
      return Promise.resolve(false);
    }
    return sendNumericCommand('voltage', inputOrId, {
      label: powerUnit === 'P' ? 'Мощность' : 'Напряжение',
      min: 0,
      max: maxValue
    }, options);
  }

  function hasExactKeys(value, expectedKeys) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const actualKeys = Object.keys(value).sort();
    const sortedExpected = expectedKeys.slice().sort();
    if (actualKeys.length !== sortedExpected.length) return false;
    return actualKeys.every(function (key, index) { return key === sortedExpected[index]; });
  }

  function validateOperationPayload(value, expectedKeys, expectedOperationId, context) {
    if (!hasExactKeys(value, expectedKeys) ||
        !Number.isInteger(value.operationId) || value.operationId <= 0 ||
        value.operationId > 0xFFFFFFFF ||
        typeof value.state !== 'string' || typeof value.error !== 'string' ||
        !['queued', 'running', 'succeeded', 'failed'].includes(value.state) ||
        (expectedOperationId !== undefined && value.operationId !== expectedOperationId) ||
        (value.state === 'failed' ? value.error === 'none' || value.error === '' : value.error !== 'none')) {
      throw new Error('Некорректный контракт ' + context + '.');
    }
    return value;
  }

  async function readOperationAcceptance(resp) {
    if (!resp || resp.status !== 202) {
      throw new Error('Некорректный HTTP-статус операции: ' + (resp ? resp.status : 0) + '.');
    }
    let result;
    try {
      result = await resp.json();
    } catch (err) {
      throw new Error('Некорректный JSON-ответ операции.');
    }
    validateOperationPayload(
      result,
      ['operationId', 'state', 'error'],
      undefined,
      'ответа операции'
    );
    if (result.state !== 'queued' || result.error !== 'none') {
      throw new Error('Операция не подтверждена как queued.');
    }
    return result;
  }

  async function waitForOperation(operationId) {
    if (!Number.isInteger(operationId) || operationId <= 0 || operationId > 0xFFFFFFFF) {
      throw new Error('Некорректный идентификатор операции.');
    }
    const startedAt = Date.now();
    let lastPollBusy = false;
    while (Date.now() - startedAt < OPERATION_TIMEOUT_MS) {
      let resp;
      let receivedResponse = false;
      const controller = new AbortController();
      const remainingMs = OPERATION_TIMEOUT_MS - (Date.now() - startedAt);
      const timer = setTimeout(function () { controller.abort(); }, remainingMs);
      try {
        resp = await fetch('/ajax?operationId=' + encodeURIComponent(String(operationId)), {
          cache: 'no-store',
          signal: controller.signal
        });
        receivedResponse = true;
        if (resp.status === 503) {
          let busy;
          try {
            busy = await resp.json();
          } catch (err) {
            if (controller.signal.aborted || (err && err.name === 'AbortError')) throw err;
            throw new Error('Некорректный JSON-ответ HTTP 503 для операции ' + operationId + '.');
          }
          if (!hasExactKeys(busy, ['operationId', 'error']) ||
              busy.operationId !== operationId || busy.error !== 'operation_store_busy') {
            throw new Error('Некорректный контракт HTTP 503 для операции ' + operationId + '.');
          }
          lastPollBusy = true;
        } else {
          lastPollBusy = false;
          if (resp.status === 404) {
            throw new Error('Операция ' + operationId + ' не найдена или её результат истёк (HTTP 404).');
          }
          if (!resp.ok) {
            const errorText = await responseErrorText(resp, 'Ошибка проверки операции ' + operationId);
            if (controller.signal.aborted) throw new DOMException('aborted', 'AbortError');
            throw new Error(errorText);
          }
          let result;
          try {
            result = await resp.json();
          } catch (err) {
            if (controller.signal.aborted || (err && err.name === 'AbortError')) throw err;
            throw new Error('Некорректный JSON-ответ /ajax для операции ' + operationId + '.');
          }
          validateOperationPayload(
            result,
            ['operationId', 'state', 'error'],
            operationId,
            '/ajax для операции ' + operationId
          );
          if (result.state === 'succeeded') return result;
          if (result.state === 'failed') {
            throw new Error('Операция ' + operationId + ' завершилась с ошибкой: ' + result.error + '.');
          }
        }
      } catch (err) {
        if (controller.signal.aborted || (err && err.name === 'AbortError')) {
          throw new Error('Операция ' + operationId + ' не завершилась за 45 секунд.');
        }
        if (!receivedResponse) {
          throw new Error('Ошибка сети при проверке операции ' + operationId + ': ' + err);
        }
        throw err;
      } finally {
        clearTimeout(timer);
      }
      await new Promise(function (resolve) { setTimeout(resolve, OPERATION_POLL_INTERVAL_MS); });
    }
    throw new Error(
      'Операция ' + operationId + ' не завершилась за 45 секунд' +
      (lastPollBusy ? ' (последний ответ HTTP 503).' : '.')
    );
  }

  async function requestI2cPump(url, fallbackText) {
    const ctrl = new AbortController();
    const timer = setTimeout(function () { ctrl.abort(); }, 4000);
    try {
      const resp = await fetch(url, { cache: 'no-store', signal: ctrl.signal });
      if (!resp.ok) {
        showRequestError(await responseErrorText(resp, fallbackText));
        return false;
      }
      clearRequestError();
      return true;
    } catch (err) {
      showRequestError(String(err && err.message ? err.message : err));
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  async function sendI2cPump() {
    const speed = readNumericInput('i2c_speed', { label: 'Скорость отбора', exclusiveMin: 0 });
    if (!speed) return false;
    const volume = readNumericInput('i2c_volume', { label: 'Объём', exclusiveMin: 0, max: 65535 });
    if (!volume) return false;
    const url = '/i2cpump?speed=' + encodeURIComponent(speed.text) +
      '&volume=' + encodeURIComponent(volume.text);
    return requestI2cPump(url, 'I2C-насос не принял команду');
  }

  async function stopI2cPump() {
    return requestI2cPump('/i2cpump?stop=1', 'I2C-насос не принял команду остановки');
  }

  async function readProgramResponse(resp) {
    let result;
    try {
      result = await resp.json();
    } catch (err) {
      throw new Error('Некорректный JSON-ответ /program.');
    }
    const baseKeys = ['ok', 'err', 'program'];
    const acceptedKeys = baseKeys.concat(['operationId', 'state', 'error']);
    if (!hasExactKeys(result, resp.status === 202 ? acceptedKeys : baseKeys) ||
        typeof result.ok !== 'boolean' ||
        typeof result.err !== 'string' ||
        typeof result.program !== 'string') {
      throw new Error('Некорректный контракт /program.');
    }
    if (!resp.ok && result.ok) {
      throw new Error('Некорректный HTTP-статус /program: ' + resp.status);
    }
    if (result.ok && resp.status !== 200 && resp.status !== 202) {
      throw new Error('Некорректный HTTP-статус /program: ' + resp.status);
    }
    if (resp.status === 202) {
      if (!result.ok) throw new Error('Некорректный контракт /program.');
      validateOperationPayload(result, acceptedKeys, undefined, '/program');
      if (result.state !== 'queued' || result.error !== 'none') {
        throw new Error('Операция /program не подтверждена как queued.');
      }
    }
    result.httpStatus = resp.status;
    result.queued = result.ok && resp.status === 202;
    return result;
  }

  async function postProgram(form) {
    const body = new FormData();
    const allowedFields = ['WProgram', 'vless', 'Descr'];
    for (let i = 0; i < allowedFields.length; i++) {
      const name = allowedFields[i];
      const fields = form.querySelectorAll('[name="' + name + '"]');
      if (fields.length > 1) {
        const err = 'Поле «' + name + '» повторяется.';
        showRequestError(err);
        return { ok: false, err: err, program: '', httpStatus: 0, queued: false };
      }
      if (fields.length === 0 || fields[0].disabled) continue;
      if (name === 'vless') {
        const volume = readNumericInput(fields[0], {
          label: 'Объём спирта-сырца', min: 0.001, max: 10000
        });
        if (!volume) {
          return { ok: false, err: byId('request_error').textContent, program: '', httpStatus: 0, queued: false };
        }
      }
      body.append(name, fields[0].value);
    }
    if (Array.from(body.keys()).length === 0) {
      const err = 'Нет данных для /program.';
      showRequestError(err);
      return { ok: false, err: err, program: '', httpStatus: 0, queued: false };
    }
    if (programMutationPending) {
      const err = 'Изменение программы уже выполняется.';
      showRequestError(err);
      return { ok: false, err: err, program: '', httpStatus: 0, queued: false };
    }
    programMutationPending = true;
    try {
      const resp = await fetch('/program', { method: 'POST', body: body });
      const result = await readProgramResponse(resp);
      if (!result.ok) {
        showRequestError('/program: HTTP ' + result.httpStatus + ' — ' + (result.err || 'запрос не принят'));
        return result;
      }
      if (!result.queued) throw new Error('Сервер не подтвердил постановку программы в очередь.');
      await waitForOperation(result.operationId);
      result.queued = false;
      result.state = 'succeeded';
      clearRequestError();
      return result;
    } catch (err) {
      const message = String(err && err.message ? err.message : err);
      showRequestError(message);
      return { ok: false, err: message, program: '', httpStatus: 0, queued: false };
    } finally {
      programMutationPending = false;
    }
  }

  async function clearProgram() {
    if (!confirm('Очистить текущую программу?')) return false;
    if (programMutationPending) {
      const message = 'Изменение программы уже выполняется.';
      showRequestError(message);
      notify(message, 1);
      return false;
    }
    const body = new FormData();
    body.append('clear', '1');
    programMutationPending = true;
    try {
      const resp = await fetch('/program', { method: 'POST', body: body });
      const result = await readProgramResponse(resp);
      if (!result.ok) {
        notify(
          'Очистка не принята (HTTP ' + result.httpStatus + '): ' +
            (result.err || 'неизвестная ошибка'),
          result.httpStatus === 400 || result.httpStatus === 409 || result.httpStatus === 503 ? 1 : 0
        );
        showRequestError('/program: HTTP ' + result.httpStatus + ' — ' + (result.err || 'очистка не принята'));
        return false;
      }
      if (!result.queued) throw new Error('Сервер не подтвердил постановку очистки в очередь.');
      await waitForOperation(result.operationId);
      clearRequestError();
      notify('Программа очищена.', 2);
      return true;
    } catch (err) {
      const message = 'Ошибка очистки программы: ' + err;
      showRequestError(message);
      notify(message, 0);
      return false;
    } finally {
      programMutationPending = false;
    }
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
    const initOptions = options || {};
    initConnection(initOptions);
    initTheme({
      dynamicThemeTitle: initOptions.dynamicThemeTitle === true,
      implicitSystemTheme: initOptions.implicitSystemTheme === true
    });
    document.addEventListener('click', unlockAudio, { once: true });
    document.addEventListener('keydown', unlockAudio, { once: true });
  }

  window.SamovarApp = {
    addLuaButtons: addLuaButtons,
    addMessage: addMessage,
    clearProgram: clearProgram,
    clearHistory: clearHistory,
    clearMessages: clearMessages,
    clearRequestError: clearRequestError,
    clearRequestErrorIfUnchanged: clearRequestErrorIfUnchanged,
    cssVar: cssVar,
    currentRequestErrorRevision: currentRequestErrorRevision,
    escapeHtml: escapeHtml,
    fetchJson: fetchJson,
    init: init,
    initTheme: initTheme,
    notify: notify,
    openTab: openTab,
    pollAjax: pollAjax,
    postProgram: postProgram,
    readOperationAcceptance: readOperationAcceptance,
    renderI2cPumpStatus: renderI2cPumpStatus,
    removeLastMessage: removeLastMessage,
    reportUiError: reportUiError,
    readNumericInput: readNumericInput,
    responseErrorText: responseErrorText,
    runLua: runLua,
    runLuaString: runLuaString,
    sendCommand: sendCommand,
    sendI2cPump: sendI2cPump,
    sendNumericCommand: sendNumericCommand,
    sendPowerCommand: sendPowerCommand,
    setConnectionError: setConnectionError,
    setConnectionOk: setConnectionOk,
    setSoundEnabled: setSoundEnabled,
    showHistory: showHistory,
    showRequestError: showRequestError,
    startPollLoop: startPollLoop,
    startTelemetryPage: startTelemetryPage,
    stopI2cPump: stopI2cPump,
    toggleTheme: toggleTheme,
    validateNumericFields: validateNumericFields,
    validateNumericInput: validateNumericInput,
    waitForOperation: waitForOperation
  };
})();
