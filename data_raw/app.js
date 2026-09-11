(function () {
  'use strict';

  // На телефоне полоса вкладок в шапке прокручивается по горизонтали; при
  // переходе по Tab фокус не должен уезжать за край экрана.
  document.addEventListener('focusin', function (event) {
    const target = event.target;
    if (target && target.closest && target.closest('.top .tab')) {
      target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  });

  const HISTORY_KEY = 'samovarHistoryV2';
  const HISTORY_LIMIT = 500;
  const COMMAND_TOKENS = {
    // Успех молчит: подтверждение показываем только там, где страница передала successMessage.
    OK: { ok: true, level: 2, text: '' },
    BUSY: { ok: false, level: 1, text: 'Устройство занято. Команда не принята.' },
    IGNORED: { ok: false, level: 1, text: 'Команда проигнорирована.' },
    POWER_OFF: { ok: false, level: 1, text: 'Нагрев выключен. Команда не принята.' },
    PWM_TOO_LOW: { ok: false, level: 1, text: 'ШИМ насоса ниже минимума при работающем нагреве. Команда не принята.' },
    NOT_RUNNING: { ok: false, level: 1, text: 'Программа БК не выполняется. Команда не принята.' },
    NO_SETPOINT: { ok: false, level: 1, text: 'У текущей строки нет уставки пара. Команда не принята.' },
    NO_PUMP: { ok: false, level: 1, text: 'Нужен ШИМ-насос охлаждения. Команда не принята.' },
    BAD_REQUEST: { ok: false, level: 0, text: 'Неверная команда.' }
  };
  const DECIMAL_PATTERN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
  const INTEGER_PATTERN = /^[+-]?\d+$/;
  const FLOAT32_MIN_NORMAL = 1.1754943508222875e-38;
  const FLOAT32_MAX = 3.4028234663852886e38;
  const OPERATION_POLL_INTERVAL_MS = 250;
  const OPERATION_TIMEOUT_MS = 45000;
  const MAX_MESSAGE_SEQUENCE = 0xFFFFFFFF;
  const RUNTIME_EVENT_BATCH_LIMIT = 32;
  const RUNTIME_PAIR_PATTERN = /^(?:(?:Тревога|Предупреждение)! )?@P1;s=([0-9A-F]{8});b=([0-9A-F]{8});p=([0-9A-F]{8});e=([BE]);m=([0-7]);r=([0-9A-F]{2});q=([0-9A-F]{2});o=([0-9A-F]{2});t=([0-9A-F]{16})(?:;u=([0-9A-F]{8}))?\|(.+)$/;
  const MESSAGE_GAP_WARNING = 'Пропущены сообщения: обнаружен разрыв последовательности.';
  const MESSAGE_REBOOT_WARNING = 'Контроллер перезагрузился: счёт сообщений начат заново.';
  const RUNTIME_BUSY_WARNING = 'Контроллер временно занят, статус обновится при следующем опросе.';
  const TELEMETRY_OPTION_KEYS = [
    'threshold', 'onReady', 'connectionIds', 'storeMessageHistory',
    'dynamicThemeTitle', 'implicitSystemTheme', 'onLastMessageRemoved', 'onConnectionChange'
  ];
  const UI_BOOTSTRAP_KEYS = [
    'mode', 'version', 'powerUnit', 'program', 'description', 'luaButtonList',
    'steamColor', 'pipeColor', 'waterColor', 'tankColor', 'acpColor',
    'steamVisible', 'pipeVisible', 'waterVisible', 'tankVisible', 'pressureVisible',
    'programNumberVisible', 'i2cStepperVisible', 'i2cPumpVisible',
    'beerBrewOrder', 'pwmLow', 'pwmValue', 'nbkDp', 'columnDiameter',
    'columnHeight', 'packDensity', 'heaterResistance', 'mainsVoltage', 'heaterMaxPower',
    'stepperMaxSpeed', 'stepperStepsPerMl', 'i2cStepperStepsPerMl',
    'calibrationRunning', 'calibrationPump', 'cheesePhSlope', 'cheesePhOffset',
    'cheeseCoolingScheme', 'cheesePhAvailable', 'cheesePhAds1115Address'
  ];
  const UI_BOOTSTRAP_STRING_KEYS = [
    'version', 'powerUnit', 'program', 'description', 'luaButtonList',
    'steamColor', 'pipeColor', 'waterColor', 'tankColor', 'acpColor',
    'cheeseCoolingScheme'
  ];
  const UI_BOOTSTRAP_BOOLEAN_KEYS = [
    'steamVisible', 'pipeVisible', 'waterVisible', 'tankVisible', 'pressureVisible',
    'programNumberVisible', 'i2cStepperVisible', 'i2cPumpVisible', 'calibrationRunning',
    'cheesePhAvailable'
  ];
  const UI_BOOTSTRAP_INTEGER_KEYS = [
    'mode', 'pwmValue', 'packDensity', 'stepperMaxSpeed', 'stepperStepsPerMl',
    'i2cStepperStepsPerMl', 'cheesePhAds1115Address'
  ];
  const UI_BOOTSTRAP_NUMBER_KEYS = [
    'pwmLow', 'nbkDp', 'columnDiameter', 'columnHeight', 'heaterResistance',
    'mainsVoltage', 'heaterMaxPower', 'cheesePhSlope', 'cheesePhOffset'
  ];

  let offlineCounter = 0;
  let offlineThreshold = 3;
  let isOffline = false;
  let runtimeBusyCounter = 0;
  let lastValidTelemetryAt = Date.now();
  let messages = [];
  let historyShown = false;
  // Картинки индикатора связи и сирена лежат рядом с app.js. На устройстве это корень,
  // но страницы могут открываться и из подпапки (тесты) - путь берём от самого скрипта.
  const assetBase = (function () {
    const script = document.currentScript;
    try { return script && script.src ? new URL('.', script.src).pathname : '/'; } catch (e) { return '/'; }
  })();
  let soundEnabled = true;
  let soundPlaying = false;
  let audioBlockedNotified = false;
  let alarmActive = false;
  let heaterAlarmLatched = false;
  let connectionAlarm = false;
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
  let onConnectionChange = null;
  let clockStale = false;
  let pageLockBound = false;
  let bootstrapPending = false;
  let bootstrapStarted = false;
  let deviceScheduleInput = null;
  let deviceScheduleOnSave = null;
  let luaProgramTextInput = null;
  let luaProgramTimeoutInput = null;
  let luaProgramOnSave = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function requiredI2cPumpElement(id) {
    const element = byId(id);
    if (!element) throw new Error('I2C pump UI contract: missing #' + id);
    return element;
  }

  // Текст состояния детектора примесей, пока он НЕ реагирует (impurity_detector.h,
  // DetectorIdleReason). Пустая строка = детектор активен, показывать статус 0/1/2.
  function detectorIdleText(idle, prgType, waitLeftSec, waitSpan) {
    if (prgType === 'H') return '👁 Головы: наблюдение';
    switch (idle) {
      case 2: return '👁 Головы: наблюдение';
      case 3: return '⏳ Пауза после старта строки';
      case 4: return '⏳ Пауза после ручного продолжения';
      case 5: {
        const left = Number.isFinite(waitLeftSec) && waitLeftSec > 0 ? ', осталось ' + Math.ceil(waitLeftSec / 60) + ' мин' : '';
        const span = Number.isFinite(waitSpan) && waitSpan > 0 ? ', размах ' + waitSpan.toFixed(2) + ' °C' : '';
        return '⏳ Жду стабилизации пара' + span + left;
      }
      case 6: return '⏳ Набираю историю';
      case 7: return '⏸ Пауза';
      case 8: return '👁 Хвосты: наблюдение';
      case 1: return '— не активен';
      default: return '';
    }
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

  function descriptionByteLength(description) {
    return new TextEncoder().encode(description).length;
  }

  // Правила типов строк программы «Пиво» — единый источник для beer.htm
  // (check_program) и brewxml.htm (validateBeerProgramText); зеркало
  // program_io.h::program_validate_beer_row_semantics.
  function beerRowTypeOk(type, temp, time, noDevice, sensor) {
    if (type === 'M' || type === 'C' || type === 'F') return temp > 0 && time === 0;
    if (type === 'P') return temp > 0 && time > 0;
    if (type === 'B') return temp === 0 && time > 0;
    if (type === 'W') return temp === 0 && time === 0;
    if (type === 'L') return temp === 0 && time === 0 && noDevice && sensor === 0;
    if (type === 'A') return temp > 0 && time === 0 && noDevice;
    return false;
  }

  var BEER_MASH_DEVICE_DEFAULT = '1^-1^2^3';
  var BEER_PUMP_CONTINUOUS = '2^0^65535^0';
  var BEER_WAIT_DEVICE = '0^0^0^0';
  var BEER_PROGRAM_MAX_ROWS = 20;
  var configuredBeerBrewOrderId = 'allinone';

  function beerBrewOrders() {
    return {
      allinone: {
        id: 'allinone',
        label: 'All-in-one / BIAB',
        mashSensor: 0,
        mashDevice: BEER_MASH_DEVICE_DEFAULT,
        hint: 'ПИД по кубу (затор), мешалка как в универсальной программе.'
      },
      herms: {
        id: 'herms',
        label: 'HERMS',
        mashSensor: 1,
        mashDevice: BEER_PUMP_CONTINUOUS,
        hint: 'ПИД по воде (бойлер), насос непрерывно гоняет затор через змеевик. Датчик куба — контроль затора.'
      },
      rims: {
        id: 'rims',
        label: 'RIMS',
        mashSensor: 2,
        mashDevice: BEER_PUMP_CONTINUOUS,
        hint: 'ПИД по царге (обратка), насос непрерывно. Нагрев без потока на реальном RIMS опасен.'
      }
    };
  }

  function beerBrewOrder(id) {
    var orders = beerBrewOrders();
    return orders[id] || orders.allinone;
  }

  function setConfiguredBeerBrewOrder(id) {
    configuredBeerBrewOrderId = beerBrewOrder(id).id;
    return configuredBeerBrewOrderId;
  }

  function currentBeerBrewOrderId() {
    var fromBody = document.body && document.body.getAttribute('data-beer-brew-order');
    if (fromBody && beerBrewOrders()[fromBody]) {
      configuredBeerBrewOrderId = fromBody;
    }
    return beerBrewOrder(configuredBeerBrewOrderId).id;
  }

  function beerSensorOptionHtml() {
    return '<option value="0">Куб (затор)</option>' +
      '<option value="1">Вода (бойлер HERMS)</option>' +
      '<option value="2">Царга (обратка RIMS)</option>' +
      '<option value="3">Пар</option>' +
      '<option value="4">ТСА</option>';
  }

  function beerProgramRow(type, temp, time, device, sensor) {
    return type + ';' + temp + ';' + time + ';' + device + ';' + sensor;
  }

  function normalizeMashStepType(raw) {
    if (raw == null) return 'temperature';
    var t = String(raw).trim();
    if (!t || t === 'Нет в рецепте') return 'temperature';
    t = t.toLowerCase();
    if (t === 'temperature' || t === 'step' || t === 'настойный') return 'temperature';
    if (t === 'infusion' || t === 'infuse') return 'infusion';
    if (t === 'decoction' || t === 'отварка') return 'decoction';
    return '';
  }

  function effectiveMashKind(stepType) {
    return normalizeMashStepType(stepType);
  }

  function applyBeerBrewOrderToProgramText(text, orderId) {
    var order = beerBrewOrder(orderId);
    var lines = String(text || '').split('\n');
    var out = [];
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (line === '') {
        out.push(line);
        continue;
      }
      var f = line.split(';');
      if (f.length !== 5) {
        out.push(line);
        continue;
      }
      if (f[0] === 'M' || f[0] === 'P') {
        f[3] = order.mashDevice;
        f[4] = String(order.mashSensor);
      }
      out.push(f.join(';'));
    }
    return out.join('\n');
  }

  // steps: [{type, temp, time, infuseAmount, infuseTemp, decoctionAmount, name}]
  function buildBeerMashStageLines(steps, orderId) {
    var order = beerBrewOrder(orderId);
    var hints = [];
    var lines = [];
    if (!steps || !steps.length) {
      return { error: 'в рецепте нет шагов затирания', lines: lines, hints: hints };
    }
    for (var i = 0; i < steps.length; i++) {
      var step = steps[i];
      var kind = effectiveMashKind(step.type);
      if (!kind) {
        return {
          error: 'неизвестный TYPE шага затирания «' + step.type + '» (нужны Infusion, Temperature или Decoction)',
          lines: [],
          hints: []
        };
      }
      var n = i + 1;
      var title = step.name ? ('«' + step.name + '»') : ('шаг ' + n);
      if (kind === 'infusion' && i > 0) {
        var amt = step.infuseAmount ? (step.infuseAmount + ' л') : 'расчётный объём';
        var it = step.infuseTemp ? (step.infuseTemp + ' °C') : 'кипяток';
        hints.push('Infusion ' + title + ': долейте ' + amt + ' воды (' + it + '), затем «далее».');
        lines.push(beerProgramRow('W', '0', '0', BEER_WAIT_DEVICE, '0'));
      }
      if (kind === 'decoction') {
        var decoct = step.decoctionAmount ? (step.decoctionAmount + ' л') : 'густую треть затора';
        hints.push('Decoction ' + title + ': отберите ' + decoct + ', закипятите, верните. Две строки ожидания, затем выдержка без догрева ТЭНом до паузы.');
        lines.push(beerProgramRow('W', '0', '0', BEER_WAIT_DEVICE, '0'));
        lines.push(beerProgramRow('W', '0', '0', BEER_WAIT_DEVICE, '0'));
      }
      lines.push(beerProgramRow('P', step.temp, step.time, order.mashDevice, String(order.mashSensor)));
    }
    return { error: '', lines: lines, hints: hints };
  }

  // Текст тела ответа для показа человеку: HTML-страницу ошибки веб-сервера
  // (404 и т.п.) не показываем - остаётся только код HTTP.
  function plainBodyText(text) {
    const trimmed = String(text || '').trim();
    return /^<(!doctype|html|head|body)\b/i.test(trimmed) ? '' : trimmed;
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

  function showRequestError(message, level) {
    requestErrorRevision++;
    const element = requestErrorElement();
    element.className = messageClass(level === undefined ? 0 : level);
    element.textContent = String(message || 'Неверные данные запроса.');
    // Крестик: раньше плашка гасла только после следующей удачной операции.
    if (typeof element.appendChild === 'function') {
      const close = document.createElement('button');
      close.type = 'button';
      close.className = 'message-dismiss request-error-close';
      close.setAttribute('aria-label', 'Скрыть сообщение');
      close.textContent = '✕';
      close.onclick = clearRequestError;
      element.appendChild(close);
    }
    element.style.display = 'block';
    // Плашка стоит первой в форме: на прокрученной вкладке она за верхним краем экрана.
    if (typeof element.scrollIntoView === 'function') element.scrollIntoView({ block: 'nearest' });
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

  function fieldLabelFromDom(name) {
    if (!name || typeof document === 'undefined' || !document.querySelector) return null;
    const source = document.querySelector('label[for="' + name + '"]');
    if (!source || typeof source.cloneNode !== 'function') return null;
    const clone = source.cloneNode(true);
    if (typeof clone.querySelectorAll === 'function') {
      const tooltips = clone.querySelectorAll('.tooltiptext');
      for (let i = 0; i < tooltips.length; i++) tooltips[i].remove();
    }
    const text = (clone.textContent || '').trim();
    return text || null;
  }

  function validateNumericInput(inputOrId, options) {
    const input = typeof inputOrId === 'string' ? byId(inputOrId) : inputOrId;
    const spec = options || {};
    const fieldName = input && (input.name || input.id);
    const label = spec.label || fieldLabelFromDom(fieldName) || fieldName || 'Значение';
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

  function operationErrorText(code) {
    const messages = {
      invalid_operation_id: 'некорректный номер операции',
      operation_not_found: 'операция не найдена или её результат уже удалён',
      operation_store_full: 'очередь операций заполнена',
      operation_store_busy: 'хранилище операций временно занято',
      invalid_operation_transition: 'нарушена последовательность выполнения операции',
      operation_internal: 'внутренняя ошибка выполнения операции',
      operation_cancelled: 'операция отменена',
      profile_persist_failed: 'настройки не удалось записать в постоянную память',
      mode_switch_failed: 'не удалось завершить смену режима; точная причина есть в журнале',
      mode_switch_log_failed: 'не завершилось закрытие журнала',
      mode_switch_lua_stop_failed: 'не остановилось выполнение Lua',
      mode_switch_queue_failed: 'не освободилась очередь команд',
      mode_switch_actuator_failed: 'привод не подтвердил остановку',
      mode_switch_i2c_mixer_failed: 'I2C-мешалка не подтвердила остановку',
      mode_switch_i2c_pump_failed: 'I2C-насос не подтвердил остановку',
      mode_switch_local_stepper_failed: 'шаговый двигатель не остановился',
      mode_switch_valve_failed: 'клапан не закрылся',
      mode_switch_mixer_failed: 'мешалка не остановилась',
      mode_switch_cooling_pump_failed: 'насос охлаждения не остановился',
      mode_switch_calibration_failed: 'не завершилась калибровка насоса',
      mode_switch_heater_failed: 'нагрев не подтвердил выключение',
      mode_switch_power_transition_failed: 'не завершился переход мощности',
      mode_switch_nbk_transition_failed: 'не завершился переход НБК',
      mode_switch_heating_start_failed: 'не отменился запуск нагрева',
      mode_switch_self_test_failed: 'не остановился самотест',
      mode_switch_owner_failed: 'после предыдущего режима не сбросилось внутреннее состояние программы',
      mode_switch_lua_reload_failed: 'не удалось перечитать Lua-скрипт нового режима',
      operation_runtime_busy: 'устройство занято другой операцией',
      i2c_config_busy: 'I2C-устройство занято настройкой',
      i2c_command_failed: 'I2C-устройство не подтвердило команду',
      i2c_device_error: 'I2C-устройство сообщило об ошибке',
      i2c_refresh_failed: 'не удалось получить текущее состояние I2C-устройства',
      calibration_invalid_result: 'получен некорректный результат калибровки',
      operation_stale_reaped: 'операция не завершилась вовремя и была остановлена'
    };
    return messages[code] || code;
  }

  async function responseErrorText(resp, prefix) {
    let detail = '';
    const contentType = resp.headers.get('Content-Type') || '';
    try {
      if (contentType.indexOf('application/json') !== -1) {
        const body = await resp.json();
        if (body && typeof body === 'object') {
          // Конверт ошибок отдаёт message человеку и error машине; старые ответы кладут
          // человеческий текст прямо в error, а код - в code. Известные коды переводим,
          // неизвестные сохраняем для диагностики.
          detail = body.message || body.error || body.err || body.code || '';
          const code = body.code || (body.message ? body.error : '');
          detail = operationErrorText(detail);
          if (code && detail !== code && operationErrorText(code) === code) detail += ' (' + code + ')';
        }
      } else {
        detail = operationErrorText(plainBodyText(await resp.text()));
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
      scheduleProgramHeaderAlign();
    }
    let activeLink = evt && evt.currentTarget;
    if (!activeLink) {
      for (let i = 0; i < tablinks.length; i++) {
        const onclickAttr = tablinks[i].getAttribute && tablinks[i].getAttribute('onclick');
        if (onclickAttr && onclickAttr.indexOf("'" + tabName + "'") !== -1) {
          activeLink = tablinks[i];
          break;
        }
      }
    }
    if (activeLink) {
      activeLink.className += ' active';
      if (activeLink.hasAttribute('aria-pressed')) {
        activeLink.setAttribute('aria-pressed', 'true');
      }
    }
  }

  function openDeviceScheduleModal(input, onSave) {
    const values = String(input.value || '0^0^0^0').split('^');
    if (values.length !== 4) return false;
    deviceScheduleInput = input;
    deviceScheduleOnSave = typeof onSave === 'function' ? onSave : null;
    byId('m_type').value = values[0];
    byId('m_direction').value = values[1];
    byId('m_time').value = values[2];
    byId('m_pause').value = values[3];
    byId('popup').style.display = 'block';
    byId('overlay').classList.add('show');
    return true;
  }

  function closeDeviceScheduleModal() {
    byId('popup').style.display = 'none';
    byId('overlay').classList.remove('show');
    deviceScheduleInput = null;
    deviceScheduleOnSave = null;
  }

  function normalizeDeviceScheduleSeconds(input) {
    let value = String(input.value || '').replace(/[^0-9]/g, '');
    let seconds = parseInt(value, 10);
    if (Number.isNaN(seconds)) seconds = 0;
    if (seconds > 65535) seconds = 65535;
    input.value = String(seconds);
  }

  function saveDeviceScheduleModal() {
    if (!deviceScheduleInput) return false;
    normalizeDeviceScheduleSeconds(byId('m_time'));
    normalizeDeviceScheduleSeconds(byId('m_pause'));
    const run = readNumericInput('m_time', {
      integer: true, min: 0, max: 65535, label: 'Время включения устройства'
    });
    if (!run) return false;
    const pause = readNumericInput('m_pause', {
      integer: true, min: 0, max: 65535, label: 'Время паузы устройства'
    });
    if (!pause) return false;
    deviceScheduleInput.value = byId('m_type').value + '^' + byId('m_direction').value + '^' + run.text + '^' + pause.text;
    const onSave = deviceScheduleOnSave;
    closeDeviceScheduleModal();
    if (onSave) onSave();
    return true;
  }

  function addLuaProgramArgument(value) {
    const container = byId('lua-program-arguments');
    const row = document.createElement('div');
    row.className = 'modalline lua-program-argument';
    const input = document.createElement('input');
    input.type = 'text';
    input.value = value == null ? '' : String(value);
    input.setAttribute('aria-label', 'Параметр Lua');
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'program-row-action';
    remove.title = 'Удалить параметр';
    remove.setAttribute('aria-label', 'Удалить параметр');
    remove.innerHTML = '<img src="minus.png" alt="">';
    remove.addEventListener('click', function () { row.remove(); });
    row.appendChild(input);
    row.appendChild(remove);
    container.appendChild(row);
  }

  async function openLuaProgramModal(textInput, timeoutInput, onSave) {
    let files;
    try {
      const response = await fetch('/edit?list=/');
      if (!response.ok) throw new Error('HTTP ' + response.status);
      files = await response.json();
    } catch (error) {
      notify('Не удалось получить список Lua-файлов: ' + error.message, 1);
      return false;
    }
    const luaFiles = files
      .filter(function (item) { return item && item.type === 'file' && /\.lua$/i.test(item.name); })
      .map(function (item) { return String(item.name).replace(/^\//, ''); })
      .filter(function (name) { return name !== 'script.lua' && name.indexOf('btn_') !== 0; });
    if (luaFiles.length === 0) {
      notify('В памяти Самовара нет Lua-файлов.', 1);
      return false;
    }
    luaProgramTextInput = textInput;
    luaProgramTimeoutInput = timeoutInput;
    luaProgramOnSave = typeof onSave === 'function' ? onSave : null;
    const parts = String(textInput.value || '').split('^');
    const select = byId('lua-program-file');
    select.innerHTML = '';
    luaFiles.forEach(function (name) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      select.appendChild(option);
    });
    if (parts[0] && luaFiles.indexOf(parts[0]) >= 0) select.value = parts[0];
    byId('lua-program-timeout').value = String(timeoutInput.value || '1');
    byId('lua-program-arguments').innerHTML = '';
    parts.slice(1).forEach(function (value) { addLuaProgramArgument(value); });
    byId('lua-program-popup').style.display = 'block';
    byId('lua-program-overlay').classList.add('show');
    return true;
  }

  function closeLuaProgramModal() {
    byId('lua-program-popup').style.display = 'none';
    byId('lua-program-overlay').classList.remove('show');
    luaProgramTextInput = null;
    luaProgramTimeoutInput = null;
    luaProgramOnSave = null;
  }

  function saveLuaProgramModal() {
    if (!luaProgramTextInput || !luaProgramTimeoutInput) return false;
    const timeout = readNumericInput('lua-program-timeout', {
      integer: true, min: 1, max: 65535, label: 'Тайм-аут Lua-этапа'
    });
    if (!timeout) return false;
    const values = [];
    const inputs = byId('lua-program-arguments').querySelectorAll('input');
    for (let i = 0; i < inputs.length; i++) {
      const value = inputs[i].value;
      if (value === '') {
        notify('Пустой параметр: укажите "" или удалите его.', 1);
        inputs[i].focus();
        return false;
      }
      if (value.indexOf('^') >= 0) {
        notify('Символ ^ используется как разделитель параметров.', 1);
        inputs[i].focus();
        return false;
      }
      values.push(value);
    }
    luaProgramTextInput.value = [byId('lua-program-file').value].concat(values).join('^');
    luaProgramTimeoutInput.value = timeout.text;
    const onSave = luaProgramOnSave;
    closeLuaProgramModal();
    if (onSave) onSave();
    return true;
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
    indicator.innerHTML = '<img src="' + assetBase + fileName + '" style="margin: 0 !important; width: 20px">';
  }

  function initConnection(options) {
    offlineThreshold = options && options.threshold ? options.threshold : 3;
    connectionIds = options && options.connectionIds ? options.connectionIds : null;
    setConnectionIcon('Green.png');
  }

  function onLockedPageInput(event) {
    if (!document.documentElement.classList.contains('connection-lost')) return;
    event.preventDefault();
    event.stopPropagation();
  }

  function bindPageLock() {
    if (pageLockBound) return;
    pageLockBound = true;
    document.addEventListener('click', onLockedPageInput, true);
    document.addEventListener('pointerdown', onLockedPageInput, true);
    document.addEventListener('keydown', onLockedPageInput, true);
    document.addEventListener('submit', onLockedPageInput, true);
  }

  function assertOnline() {
    if (bootstrapPending) throw new Error('Начальные данные ещё не загружены: действие заблокировано.');
    if (isOffline) throw new Error('Нет связи: действие заблокировано.');
  }

  // Обрыв связи: вся страница приглушается и блокируется (клики, клавиатура,
  // правки). Иначе оператор жмёт по застывшим кнопкам и полям. Часы помечаются
  // текстом «Нет связи, данные от …», чтобы было видно, насколько цифры старые.
  function applyStaleVisuals(offline) {
    const clock = byId('crnt_tm');
    const root = document.documentElement;
    if (offline) {
      if (clockStale) return;
      clockStale = true;
      if (clock) {
        clock.textContent = 'Нет связи, данные от ' + clock.textContent;
      }
      root.classList.add('connection-lost');
      document.body.inert = true;
      const active = document.activeElement;
      if (active && active !== document.body && typeof active.blur === 'function') {
        active.blur();
      }
    } else {
      clockStale = false;
      root.classList.remove('connection-lost');
      document.body.inert = false;
    }
  }

  function setConnectionError(staleTelemetry) {
    if (!staleTelemetry && offlineCounter < offlineThreshold) {
      offlineCounter++;
      return;
    }
    setConnectionIcon('Red_light.gif');
    connectionAlarm = true;
    addMessage('Обрыв связи!', 0);
    setTimeout(function () {
      isOffline = true;
      if (connectionIds) offlineCounter = 0;
      else offlineCounter++;
      applyStaleVisuals(true);
      if (onConnectionChange) onConnectionChange(true);
    }, 100);
  }

  function setConnectionOk() {
    connectionAlarm = false;
    setConnectionIcon('Green.png');
    isOffline = false;
    offlineCounter = 0;
    applyStaleVisuals(false);
    showMessages();
    if (onConnectionChange) onConnectionChange(false);
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

  // Закрытие истории по Esc и по клику/касанию вне окна: кнопка ☰ на планшете
  // бывает накрыта самим окном или лентой сообщений, и другого выхода не было.
  function onHistoryKeydown(event) {
    if (event.key === 'Escape' || event.key === 'Esc') showHistory();
  }

  function onHistoryPointerdown(event) {
    const box = byId('historyBox');
    const trigger = document.querySelector('.history-trigger');
    if ((box && box.contains(event.target)) || (trigger && trigger.contains(event.target))) return;
    showHistory();
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
      document.removeEventListener('keydown', onHistoryKeydown);
      document.removeEventListener('pointerdown', onHistoryPointerdown);
      return;
    }
    list.innerHTML = getHistory().map(renderHistoryEntry).join('');
    box.style.display = 'block';
    box.scrollTop = box.scrollHeight;
    historyShown = true;
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    document.addEventListener('keydown', onHistoryKeydown);
    document.addEventListener('pointerdown', onHistoryPointerdown);
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
    // Раньше вся строка была кнопкой-самоудалением - случайный тычок в аварийное
    // сообщение (например, при захлёбе, который живёт только в тексте, без latch)
    // гасил его вместе с сиреной незаметно для пользователя. Удаляет только отдельный
    // крестик; у аварийных сообщений removeMessage() дополнительно спрашивает подтверждение.
    const last = index === messages.length - 1;
    const handler = last ? 'SamovarApp.removeLastMessage()' : 'SamovarApp.removeMessage(' + index + ')';
    return '<div align="left" class="' + escapeHtml(entry.cssClass) +
      '" style="display: flex; justify-content: space-between; align-items: center; gap: 0.5em;">' +
      '<span>' + content + '</span>' +
      '<button type="button" class="message-dismiss" aria-label="Скрыть сообщение" ' +
      'onclick="' + handler + '">✕</button></div>';
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

  // message_0 - аварийный уровень (level 0). Для аппаратной защёлки нагрева
  // и обрыва связи сирена живёт отдельно от тоста: спрашиваем подтверждение,
  // чтобы случайный тычок не прятал аварию молча.
  function confirmMessageRemoval(entry) {
    return entry.cssClass !== 'message_0' ||
      confirm('Скрыть аварийное сообщение «' + entry.msg + '»?');
  }

  function removeMessage(index) {
    if (index < 0 || index >= messages.length) return;
    if (!confirmMessageRemoval(messages[index])) return;
    messages.splice(index, 1);
    if (onLastMessageRemoved) onLastMessageRemoved(messages.length);
    showMessages();
  }

  function removeLastMessage() {
    if (messages.length === 0) return;
    if (!confirmMessageRemoval(messages[messages.length - 1])) return;
    messages.pop();
    if (onLastMessageRemoved) onLastMessageRemoved(messages.length);
    showMessages();
  }

  function clearMessages() {
    messages = [];
    showMessages();
  }

  function updateHeaterAlarmLatched(latched, reason) {
    heaterAlarmLatched = latched;
    if (latched) {
      const present = messages.some(function (entry) { return entry.msg === reason; });
      if (!present) pushMessage(reason, 0);
    }
    showMessages();
  }

  function showMessages() {
    const box = byId('messagesBox');
    const list = byId('messages');
    // Сирена: аппаратная защёлка нагрева ИЛИ подтверждённый обрыв связи.
    // Обычный message_0 (датчик ТСА, захлёб в ленте и т.п.) в тосте есть,
    // но не крутит alarm.mp3 - иначе открытие страницы с хвостом ошибки орёт сразу.
    alarmActive = heaterAlarmLatched || connectionAlarm;
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
    sound = new Audio(assetBase + 'alarm.mp3');
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

  // Подсказки как в 6.27: CSS :hover/:focus-within на .tooltip .tooltiptext.
  // Страницы всё ещё вызывают enhanceTooltips() после перерисовки программы.
  function enhanceTooltip(container) {}
  function enhanceTooltips(root) {}

  // ==================== Общая часть renderTelemetry ====================
  // version/crnt_tm/stm, блок мощности, служебные показания (heap/rssi/...), звук,
  // Lstatus и подпись насоса воды - одинаковы на index/beer/bk/nbk/distiller.htm.
  // Формат current_power_volt/target_power_volt - единственное, что реально
  // отличается (distiller.htm и index.htm показывают десятые), поэтому это параметр,
  // а не отдельная копия функции. Рендер I2C-насоса и кнопку нагрева страницы
  // вызывают сами, отдельно от этой функции: smoke_i2c_pump_ui_contract.py требует,
  // чтобы SamovarApp.renderI2cPumpStatus(myObj) и запись
  // document.getElementById('power').value были видны прямо в коде страницы.
  function renderTelemetryCommon(myObj, options) {
    var opts = options || {};
    byId('version').textContent = myObj.version;
    byId('crnt_tm').textContent = myObj.crnt_tm;
    byId('stm').textContent = myObj.stm;

    var voltFixed = opts.powerVoltFixed;
    byId('current_power_volt').innerHTML = voltFixed === undefined
      ? myObj.current_power_volt
      : myObj.current_power_volt.toFixed(voltFixed);
    byId('target_power_volt').innerHTML = voltFixed === undefined
      ? myObj.target_power_volt
      : myObj.target_power_volt.toFixed(voltFixed);
    byId('current_power_mode').innerHTML = myObj.current_power_mode;
    byId('current_power_p').innerHTML = myObj.current_power_p;

    byId('bme_temp').innerHTML = myObj.bme_temp;
    byId('heap').innerHTML = myObj.heap;
    byId('rssi').innerHTML = myObj.rssi;
    byId('fr_bt').innerHTML = myObj.fr_bt;
    setSoundEnabled(!!myObj.UseBBuzzer);

    if (myObj.Lstatus) {
      if (myObj.Lstatus != "") {
        byId('Lstatus').textContent = myObj.Lstatus;
      }
    }

    if (myObj.wp_spd !== undefined) {
      byId('add_param').textContent = "; ШИМ насоса воды: " + myObj.wp_spd;
    }
    renderUiDetails(myObj);
  }

  const UI_PHASE_NAMES = ['Простой', 'Строка программы', 'Нагрев', 'Стабилизация', 'Выдержка', 'Охлаждение', 'Ожидание оператора', 'Подтверждение привода', 'Безопасное ожидание', 'Известная Lua-операция', 'Завершение', 'Ошибка', 'Неизвестная Lua-фаза'];
  const UI_END_NAMES = ['', 'порог датчика', 'объём', 'спиртуозность', 'соотношение', 'время', 'результат привода', 'действие оператора', 'конец программы', 'результат Lua-операции', 'плато температуры'];
  const UI_END_SOURCE_NAMES = ['', 'по пару', 'по царге', 'по воде', 'по кубу', 'по ТСА', 'по pH', 'по таймеру', 'по объёму', 'по приводу'];
  const UI_END_OPERATOR_NAMES = ['', 'не ниже', 'не выше', 'по истечении времени', 'после подтверждения', 'вручную'];
  const UI_WAIT_NAMES = ['', 'Ручная пауза ректификации', 'Ручная пауза пивоварения', 'Ожидание температуры пара', 'Ожидание температуры царги', 'Пауза детектора', 'Программная пауза', 'Нагрев дистилляции', 'Недостоверная спиртуозность', 'Ожидание кипения БК', 'Подтверждение мощности БК', 'Переход НБК', 'Безопасное ожидание НБК', 'Ожидание солода', 'Подтверждение пропуска охлаждения', 'Заморозка выдержки пива', 'Ожидание оператора пивоварения', 'Выдержка Сувид вне полосы', 'Заморозка выдержки сыра', 'Ожидание оператора сыра', 'Дозирование сыра', 'Подтверждение температуры/pH', 'Подтверждение привода', 'Известная Lua-операция'];
  const UI_CONTINUATION_NAMES = ['способ продолжения неизвестен', 'автоматически', 'после действия оператора', 'после подтверждения привода', 'при смене строки', 'при завершении процесса'];
  const UI_UNIT_NAMES = ['', '°C', 'мл', 'л/ч', '%', 'pH', 'с', 'мин', 'вкл/выкл', 'В', 'Вт', 'ШИМ'];
  const UI_SOURCE_NAMES = ['источник неизвестен', 'по программе', 'вручную', 'автоматика воды', 'защита', 'операция', 'автоскорость', 'детектор'];
  const UI_EQUIPMENT_NAMES = ['', 'нагрев', 'отбор', 'вода', 'мешалка', 'I2C-насос', 'подача НБК'];

  function uiWaitReasonName(code) {
    return UI_WAIT_NAMES[code];
  }

  function hasUiInteger(value, min, max) {
    return Number.isInteger(value) && value >= min && value <= max;
  }

  function hasUiValue(value) {
    return (typeof value === 'number' && Number.isFinite(value)) || typeof value === 'boolean';
  }

  function validateUiCondition(condition) {
    return condition && typeof condition === 'object' && hasUiInteger(condition.e, 1, 10) &&
      (condition.es === undefined || hasUiInteger(condition.es, 0, 9)) &&
      (condition.eo === undefined || hasUiInteger(condition.eo, 0, 5)) &&
      (condition.ev === undefined || Number.isFinite(condition.ev)) &&
      (condition.eu === undefined || hasUiInteger(condition.eu, 0, 8)) &&
      ((condition.ev === undefined) === (condition.eu === undefined)) &&
      (condition.et === undefined || hasUiInteger(condition.et, 0, 0xFFFFFFFF));
  }

  function validateUi(ui) {
    if (!ui || typeof ui !== 'object' || !hasUiInteger(ui.m, 0, 7) || !hasUiInteger(ui.p, 0, 12) ||
        (ui.r !== undefined && !hasUiInteger(ui.r, 1, 255)) ||
        (ui.n !== undefined && !hasUiInteger(ui.n, 1, 255)) ||
        (ui.ls !== undefined && (ui.m !== 6 || typeof ui.ls !== 'string'))) return false;
    const hasEnd = ui.e !== undefined || ui.es !== undefined || ui.eo !== undefined ||
      ui.ev !== undefined || ui.eu !== undefined || ui.et !== undefined;
    if (hasEnd && !validateUiCondition(ui)) return false;
    if (ui.g !== undefined && (!Array.isArray(ui.g) || ui.g.length > 2 || !ui.g.every(validateUiCondition))) return false;
    if (ui.w !== undefined && (!Array.isArray(ui.w) || ui.w.length > 2 || !ui.w.every(function(wait) {
      return wait && typeof wait === 'object' && hasUiInteger(wait.q, 1, 23) && hasUiInteger(wait.co, 0, 5);
    }))) return false;
    if (ui.c !== undefined && (!Array.isArray(ui.c) || ui.c.length > 4 || !ui.c.every(function(control) {
      return control && typeof control === 'object' && hasUiInteger(control.k, 1, 6) &&
        hasUiInteger(control.u, 0, 11) && hasUiInteger(control.s, 0, 7) &&
        (control.r === undefined || hasUiValue(control.r)) && (control.a === undefined || hasUiValue(control.a));
    }))) return false;
    return true;
  }

  function formatUiCondition(condition) {
    const unit = UI_UNIT_NAMES[condition.eu] || '';
    const operator = UI_END_OPERATOR_NAMES[condition.eo] || '';
    const source = UI_END_SOURCE_NAMES[condition.es] || '';
    const target = condition.ev === undefined ? '' : ' ' + condition.ev + (unit ? ' ' + unit : '');
    return UI_END_NAMES[condition.e] + ':' + (operator ? ' ' + operator : '') + target + (source ? ' ' + source : '') +
      (condition.et === undefined ? '' : '; осталось ' + condition.et + ' с');
  }

  function renderUiControls(controls) {
    let block = byId('ui_control_details');
    if (!block) {
      const host = document.querySelector('#regulator, .sec-actions');
      if (!host) return;
      block = document.createElement('div');
      block.id = 'ui_control_details';
      block.className = 'meta';
      host.appendChild(block);
    }
    if (!controls || !controls.length) {
      block.style.display = 'none';
      return;
    }
    block.textContent = controls.map(function(control) {
      function valueText(value) {
        if (value === undefined) return '—';
        if (control.u === 8 && (value === true || value === 1)) return 'вкл';
        if (control.u === 8 && (value === false || value === 0)) return 'выкл';
        return String(value) + (UI_UNIT_NAMES[control.u] ? ' ' + UI_UNIT_NAMES[control.u] : '');
      }
      return UI_EQUIPMENT_NAMES[control.k] + ': задано ' + valueText(control.r) +
        ', применяется ' + valueText(control.a) + ' (' + UI_SOURCE_NAMES[control.s] + ')';
    }).join('; ');
    block.style.display = '';
  }

  function renderUiDetails(data) {
    let block = byId('ui_details');
    if (!block) {
      const stage = document.querySelector('.stage');
      if (!stage) return;
      block = document.createElement('div');
      block.id = 'ui_details';
      block.className = 'meta';
      stage.appendChild(block);
    }
    const ui = data && data.ui;
    if (!validateUi(ui)) {
      block.textContent = 'Подробное объяснение недоступно: данные этапа отсутствуют или некорректны.';
      block.style.display = '';
      renderUiControls(null);
      return;
    }
    const lines = ['Этап: ' + UI_PHASE_NAMES[ui.p]];
    if (Number.isInteger(ui.r)) lines.push('Строка: ' + ui.r);
    if (ui.e !== undefined) lines.push('Завершение: ' + formatUiCondition(ui));
    if (ui.g && ui.g.length) lines.push('Процесс: ' + ui.g.map(formatUiCondition).join('; '));
    if (Array.isArray(ui.w) && ui.w.length) {
      lines.push('Ожидание: ' + ui.w.map(function (wait) {
        return uiWaitReasonName(wait.q) + '; ' + UI_CONTINUATION_NAMES[wait.co];
      }).join('; '));
    }
    if (Number.isInteger(ui.n)) lines.push('Далее: строка ' + ui.n);
    if (ui.m === 6 && typeof ui.ls === 'string') lines.push('Lua: ' + ui.ls);
    block.textContent = lines.join(' · ');
    block.style.display = '';
    renderUiControls(ui.c);
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

  function validateRuntimeEventItem(data) {
    const hasMessage = Object.prototype.hasOwnProperty.call(data, 'Msg');
    const hasLog = Object.prototype.hasOwnProperty.call(data, 'LogMsg');
    const hasLevel = Object.prototype.hasOwnProperty.call(data, 'msglvl');
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

  function validateRuntimeEvents(data) {
    const hasSequence = Object.prototype.hasOwnProperty.call(data, 'messageSequence');
    const hasMessage = Object.prototype.hasOwnProperty.call(data, 'Msg');
    const hasLog = Object.prototype.hasOwnProperty.call(data, 'LogMsg');
    const hasLevel = Object.prototype.hasOwnProperty.call(data, 'msglvl');
    const hasEvents = Object.prototype.hasOwnProperty.call(data, 'events');
    if (hasSequence || hasMessage || hasLog || hasLevel) {
      throw new Error('Некорректный контракт runtime-сообщения.');
    }
    if (!hasEvents) return [];
    if (!Array.isArray(data.events) || data.events.length > RUNTIME_EVENT_BATCH_LIMIT) {
      throw new Error('Некорректный контракт runtime-сообщения.');
    }
    const events = [];
    for (let index = 0; index < data.events.length; index++) {
      const item = data.events[index];
      if (!item || typeof item !== 'object') {
        throw new Error('Некорректный контракт runtime-сообщения.');
      }
      events.push(validateRuntimeEventItem(item));
    }
    return events;
  }

  function parseRuntimePair(text) {
    const match = RUNTIME_PAIR_PATTERN.exec(text);
    if (!match) return null;
    const isBegin = match[4] === 'B';
    if ((isBegin && match[8] !== 'FF') ||
        (!isBegin && !/^(?:00|01|02|03|04)$/.test(match[8])) ||
        match[1] === '00000000' || match[3] === '00000000' ||
        (match[6] !== 'FF' && match[6] === '00') ||
        match[7] === '00' || Number.parseInt(match[7], 16) > 23) {
      return null;
    }
    return {
      sessionId: match[1],
      bootId: match[2],
      pairId: match[3],
      event: isBegin ? 'begin' : 'end',
      mode: match[5],
      row: match[6],
      reason: match[7],
      outcome: match[8],
      monotonicMs: match[9],
      utc: match[10] || null,
      text: match[11]
    };
  }

  function validateHeaterTelemetry(data) {
    if ((data.heaterAlarmLatched !== 0 && data.heaterAlarmLatched !== 1) ||
        typeof data.heaterAlarmReason !== 'string' ||
        !Number.isInteger(data.latestMessageSequence) ||
        data.latestMessageSequence < 0 || data.latestMessageSequence > MAX_MESSAGE_SEQUENCE) {
      throw new Error('Некорректный контракт heaterAlarmLatched/heaterAlarmReason/latestMessageSequence.');
    }
    const latched = data.heaterAlarmLatched === 1;
    // heaterAlarmReason живёт вместе с защёлкой (до перезагрузки ESP).
    // Кольцо событий может вытеснить исходный SendMsg; пустая причина при
    // latch=1 — нарушение контракта, не «нет текста».
    if (latched === (data.heaterAlarmReason === '')) {
      throw new Error('Некорректный контракт heaterAlarmLatched/heaterAlarmReason/latestMessageSequence.');
    }
    return {
      heaterAlarmLatched: latched,
      reason: data.heaterAlarmReason,
      latestSequence: data.latestMessageSequence
    };
  }

  function resolvePollSinks(sinks) {
    if (sinks === undefined) {
      return {
        message: addMessage,
        log: function (text, data) { console.log(data.crnt_tm + '; ' + text); },
        connection: function (hasError, staleTelemetry) {
          if (hasError) setConnectionError(staleTelemetry);
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
          // Состояние контроллера временно занято (мьютекс/снапшот) - это не обрыв
          // связи само по себе. Но серия 503 не обновляет показания: когда возраст
          // последнего валидного /ajax превышает обычный порог опросов, используем
          // уже существующее состояние устаревших данных.
          runtimeBusyCounter += 1;
          if (runtimeBusyCounter >= offlineThreshold) {
            runtimeBusyCounter = 0;
            activeSinks.message(RUNTIME_BUSY_WARNING, 1);
          }
          if (Date.now() - lastValidTelemetryAt >= offlineThreshold * 2000) {
            activeSinks.connection(true, true);
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

      let events;
      try {
        events = validateRuntimeEvents(data);
        const heaterTelemetry = validateHeaterTelemetry(data);
        lastValidTelemetryAt = Date.now();
        activeSinks.connection(false);
        renderFn(data);
        notifyTelemetryListeners(data);
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
        } else {
          for (let index = 0; index < events.length; index++) {
            const event = events[index];
            const expected = nextMessageSequence(messageCursor);
            if (event.sequence !== expected) {
              // Кольцо на ESP начинается с 1 после перезагрузки. Вкладка при этом
              // живёт со старым курсором (203 → 1) - это не потеря сообщений, а
              // новый прогон. Настоящий разрыв - только прыжок вперёд: курсор
              // вытеснен из кольца (больше 32 событий между опросами).
              const deviceRestarted = messageCursor !== 0 && event.sequence < expected;
              // Молчать про откат счётчика нельзя: перезагрузка контроллера посреди
              // перегонки - это событие, о котором оператор обязан узнать (нагрев
              // снят, программа восстанавливается из снимка). Прошивка сама о старте
              // не сообщает, поэтому единственный признак - именно откат счётчика.
              activeSinks.message(deviceRestarted ? MESSAGE_REBOOT_WARNING : MESSAGE_GAP_WARNING, 1);
              notifyRuntimePairListeners(null, deviceRestarted ? 'reboot' : 'gap');
            }
            if (event.kind === 'message') {
              activeSinks.message(event.text, event.level);
            } else {
              activeSinks.log(
                event.text,
                Object.assign({}, data, { messageSequence: event.sequence })
              );
            }
            if (event.kind === 'message') {
              const pair = parseRuntimePair(event.text);
              if (pair) notifyRuntimePairListeners(pair, null);
            }
            messageCursor = event.sequence;
          }
        }
        updateHeaterAlarmLatched(heaterTelemetry.heaterAlarmLatched, heaterTelemetry.reason);
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

  async function loadUiBootstrap(applyBootstrap) {
    if (typeof applyBootstrap !== 'function') {
      throw new Error('Не задан обработчик начальных данных.');
    }
    if (bootstrapStarted) {
      showRequestError('Начальные данные уже загружены.');
      return false;
    }
    bootstrapStarted = true;
    bootstrapPending = true;
    document.body.inert = true;
    let response;
    try {
      response = await fetch('/ui-bootstrap', { cache: 'no-store' });
    } catch (err) {
      showRequestError('Ошибка сети при загрузке начальных данных.');
      return false;
    }
    if (!response.ok) {
      showRequestError('Начальные данные недоступны: HTTP ' + response.status + '.');
      return false;
    }
    let data;
    try {
      data = await response.json();
    } catch (err) {
      showRequestError('Некорректный JSON начальных данных.');
      return false;
    }
    if (!validateUiBootstrap(data)) {
      showRequestError('Некорректные начальные данные.');
      return false;
    }
    try {
      applyBootstrap(data);
    } catch (err) {
      showRequestError('Некорректные начальные данные: ' +
        (err && err.message ? err.message : err));
      return false;
    }
    bootstrapPending = false;
    document.body.inert = false;
    return true;
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
    if (pageOptions.onConnectionChange !== undefined &&
        typeof pageOptions.onConnectionChange !== 'function') {
      throw new Error('onConnectionChange должен быть функцией.');
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
    onConnectionChange = pageOptions.onConnectionChange || null;
    bindPageLock();
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

  function sendCommand(command, options) {
    assertOnline();
    return sendCommandRequest(command, options);
  }

  async function sendCommandRequest(command, options) {
    try {
      assertOnline();
      const commandBody = command.indexOf('=') === -1 ? command + '=1' : command;
      const resp = await fetch('/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: commandBody
      });
      const body = plainBodyText(await resp.text());
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
      function report(text, level) {
        addMessage(text, level);
      }
      if (knownToken && !result.ok) {
        showRequestError(result.text);
        report(result.text, result.level);
        return false;
      }
      if (!resp.ok) {
        const errorText = 'Ошибка команды HTTP ' + resp.status + ': ' + (detail || resp.statusText);
        showRequestError(errorText);
        report(errorText, 0);
        return false;
      }
      if (knownToken && result.ok) {
        clearRequestError();
        if (options && options.successMessage) report(options.successMessage, 2);
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

  function validateUiBootstrap(data) {
    const expectedKeys = data.timeZone === undefined ? UI_BOOTSTRAP_KEYS : UI_BOOTSTRAP_KEYS.concat('timeZone');
    if (!hasExactKeys(data, expectedKeys)) return false;
    for (let index = 0; index < UI_BOOTSTRAP_STRING_KEYS.length; index++) {
      if (typeof data[UI_BOOTSTRAP_STRING_KEYS[index]] !== 'string') return false;
    }
    if (descriptionByteLength(data.description) > 250) return false;
    for (let index = 0; index < UI_BOOTSTRAP_BOOLEAN_KEYS.length; index++) {
      if (typeof data[UI_BOOTSTRAP_BOOLEAN_KEYS[index]] !== 'boolean') return false;
    }
    for (let index = 0; index < UI_BOOTSTRAP_INTEGER_KEYS.length; index++) {
      if (!Number.isSafeInteger(data[UI_BOOTSTRAP_INTEGER_KEYS[index]])) return false;
    }
    if (data.timeZone !== undefined && (!Number.isSafeInteger(data.timeZone) || data.timeZone < 0 || data.timeZone > 23)) return false;
    for (let index = 0; index < UI_BOOTSTRAP_NUMBER_KEYS.length; index++) {
      if (!Number.isFinite(data[UI_BOOTSTRAP_NUMBER_KEYS[index]])) return false;
    }
    if (data.mode < 0 || data.mode > 7) return false;
    if (['allinone', 'herms', 'rims'].indexOf(data.beerBrewOrder) === -1 ||
        ['local', 'i2c'].indexOf(data.calibrationPump) === -1 ||
        ['pump', 'two-valves', 'unavailable'].indexOf(data.cheeseCoolingScheme) === -1) return false;
    return true;
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
            throw new Error('Операция ' + operationId + ' завершилась с ошибкой: ' + operationErrorText(result.error) + '.');
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
      assertOnline();
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

  function postProgram(form) {
    assertOnline();
    return postProgramRequest(form);
  }

  async function postProgramRequest(form) {
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
      } else if (name === 'Descr') {
        const byteLength = descriptionByteLength(fields[0].value);
        if (byteLength > 250) {
          const err = 'Описание длиннее 250 байт.';
          showRequestError(err);
          return { ok: false, err: err, program: '', httpStatus: 0, queued: false };
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
    const submittedProgramRevision = programRevision;
    programMutationPending = true;
    try {
      assertOnline();
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
      markProgramSaved(submittedProgramRevision);
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
      assertOnline();
      const resp = await fetch('/program', { method: 'POST', body: body });
      const result = await readProgramResponse(resp);
      if (!result.ok) {
        const failText =
          'Очистка не принята (HTTP ' + result.httpStatus + '): ' +
            (result.err || 'неизвестная ошибка');
        notify(
          failText,
          result.httpStatus === 400 || result.httpStatus === 409 || result.httpStatus === 503 ? 1 : 0
        );
        showRequestError('/program: HTTP ' + result.httpStatus + ' — ' + (result.err || 'очистка не принята'));
        return false;
      }
      if (!result.queued) throw new Error('Сервер не подтвердил постановку очистки в очередь.');
      await waitForOperation(result.operationId);
      clearRequestError();
      markProgramSaved();
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


  // ==================== Мнемосхема и карточки (новый интерфейс) ====================
  // Разметка описывает привязки атрибутами, а не id: data-tele="Ключ" (текст, data-fmt -
  // число знаков), data-on="Ключ" (класс is-on при истинном значении), data-show="Ключ"
  // (класс is-hidden при ложном), data-width="Ключ" (ширина в процентах),
  // data-jar="i" (i-я из трёх банок окна вокруг текущей ёмкости, см. jarWindow).
  // Ключи - поля /ajax плюс производные с подчёркиванием (см. deriveView).
  const telemetryListeners = [];
  const runtimePairListeners = [];

  function onTelemetry(fn) {
    if (typeof fn === 'function') telemetryListeners.push(fn);
  }

  function notifyTelemetryListeners(data) {
    telemetryListeners.forEach(function (fn) {
      try { fn(data); } catch (err) { console.error('telemetry listener', err); }
    });
  }

  function onRuntimePair(fn) {
    if (typeof fn === 'function') runtimePairListeners.push(fn);
  }

  function notifyRuntimePairListeners(pair, discontinuity) {
    runtimePairListeners.forEach(function (fn) {
      try { fn(pair, discontinuity); } catch (err) { console.error('runtime pair listener', err); }
    });
  }

  const LINE_TYPE_NAMES = {
    rect: { H: 'Головы', B: 'Тело', P: 'Пауза', T: 'Хвосты', C: 'Предзахлёб' },
    dist: { T: 'По Т куба', S: 'Спирт в кубе, отн.', A: 'Спирт в кубе, абс.', P: 'Спирт в паре, абс.', R: 'Спирт в паре, отн.' },
    bk: { T: 'По Т куба', S: 'Спирт в кубе, отн.', A: 'Спирт в кубе, абс.', P: 'Спирт в паре, абс.', R: 'Спирт в паре, отн.' },
    nbk: { H: 'Прогрев', S: 'Настройка', O: 'Оптимизация', W: 'Работа' },
    beer: { M: 'Засыпь солода', P: 'Пауза', B: 'Кипячение', C: 'Охлаждение', W: 'Ожидание', F: 'Брожение', L: 'Lua', A: 'Автотюнинг' },
    cheese: { M: 'Нагрев', P: 'Выдержка', C: 'Охлаждение', W: 'Ожидание', L: 'Lua', A: 'Кислотность', D: 'Слив' }
  };

  function schemeKind() {
    return (document.body && document.body.getAttribute('data-scheme')) || 'rect';
  }

  function programLines() {
    const textarea = byId('WProgram');
    if (!textarea) return [];
    return String(textarea.value || '').split('\n')
      .map(function (line) { return line.trim(); })
      .filter(function (line) { return line !== ''; });
  }

  function num(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function hoursText(hours) {
    if (!Number.isFinite(hours) || hours <= 0) return '—';
    const total = Math.round(hours * 60);
    const h = Math.floor(total / 60);
    const m = total % 60;
    return h > 0 ? h + ' ч ' + (m < 10 ? '0' : '') + m + ' мин' : m + ' мин';
  }

  // Разбор строки программы по формату режима. Поля, которых в формате нет, остаются null.
  function parseProgramLine(kind, line) {
    const f = line.split(';').map(function (s) { return s.trim(); });
    const names = LINE_TYPE_NAMES[kind] || {};
    const row = { type: f[0] || '', name: names[f[0]] || f[0] || '—', volume: null, speed: null,
      capacity: null, temp: null, power: null, value: null, time: null, steam: null, summary: '' };
    if (kind === 'rect') {
      // Ёмкости нумеруются с 0, поэтому 0 — настоящая ёмкость; у паузы поле — заполнитель, ёмкости нет.
      row.volume = num(f[1]); row.speed = num(f[2]); row.capacity = row.type === 'P' ? null : num(f[3]);
      row.temp = num(f[4]); row.power = num(f[5]);
      if (row.type === 'P') row.time = row.volume !== null ? row.volume / 3600 : null;
      else if (row.volume !== null && row.speed > 0) row.time = row.volume / (row.speed * 1000);
      row.summary = row.type === 'P'
        ? row.name + ' · ' + (row.volume !== null ? row.volume + ' с' : '')
        : row.name + ' · ' + (row.volume !== null ? row.volume + ' мл' : '') +
          (row.speed !== null ? ' · ' + row.speed + ' л/ч' : '') +
          (row.capacity !== null ? ' · ёмк. ' + row.capacity : '');
    } else if (kind === 'dist' || kind === 'bk') {
      row.value = num(f[1]); row.capacity = num(f[2]); row.power = num(f[3]); row.steam = num(f[4]);
      row.summary = row.name + (row.value !== null ? ' · ' + row.value : '') +
        (row.capacity !== null ? ' · ёмк. ' + row.capacity : '');
    } else if (kind === 'beer' || kind === 'cheese') {
      row.temp = num(f[1]); row.time = num(f[2]) !== null ? num(f[2]) / 60 : null;
      row.summary = row.name + (row.temp ? ' · ' + row.temp + ' °C' : '') +
        (row.time ? ' · ' + hoursText(row.time) : '');
    } else if (kind === 'nbk') {
      row.value = num(f[1]); row.speed = num(f[2]);
      row.summary = row.name + (row.value !== null ? ' · ' + row.value : '') +
        (row.speed !== null ? ' · ' + row.speed : '');
    } else {
      row.summary = line;
    }
    return row;
  }

  // Короткие имена типов строк для подписи под банками.
  const JAR_TYPE_NAMES = {
    rect: { H: 'головы', B: 'тело', P: 'пауза', T: 'хвосты', C: 'предзахлёб' },
    dist: { T: 'по Т куба', S: 'куб, отн.', A: 'куб, абс.', P: 'пар, абс.', R: 'пар, отн.' },
    bk: { T: 'по Т куба', S: 'куб, отн.', A: 'куб, абс.', P: 'пар, абс.', R: 'пар, отн.' }
  };

  // Окно из трёх банок вокруг ёмкости текущей строки: предыдущая, текущая, следующая.
  // У края окно сдвигается, чтобы банок было три. Банки — разные ёмкости программы в порядке
  // первого упоминания, подпись — тип первой строки с этой ёмкостью (у текущей — тип текущей строки).
  // Без программы или без текущей ёмкости показываем банки 0–2 без подсветки (ёмкости нумеруются с 0).
  function jarWindow(kind, lines, lineNum) {
    const names = JAR_TYPE_NAMES[kind] || {};
    const jars = [];
    lines.forEach(function (line) {
      const row = parseProgramLine(kind, line);
      if (row.capacity !== null && !jars.some(function (j) { return j.num === row.capacity; })) {
        jars.push({ num: row.capacity, type: names[row.type] || row.type, active: false });
      }
    });
    if (!jars.length) return [0, 1, 2].map(function (n) { return { num: n, type: '', active: false }; });
    const row = lineNum ? parseProgramLine(kind, lines[lineNum - 1]) : null;
    let idx = row && row.capacity !== null ? jars.findIndex(function (j) { return j.num === row.capacity; }) : -1;
    if (idx >= 0) { jars[idx].active = true; jars[idx].type = names[row.type] || row.type; }
    const start = Math.max(0, Math.min(idx < 0 ? 0 : idx - 1, jars.length - 3));
    return jars.slice(start, start + 3);
  }

  function deriveView(data) {
    const kind = schemeKind();
    const v = Object.assign({}, data);
    const steam = num(data.SteamTemp), pipe = num(data.PipeTemp);
    v._delta = steam !== null && pipe !== null ? pipe - steam : null;
    const bodySteam = num(data.BodyTemp_Steam), bodyPipe = num(data.BodyTemp_Pipe);
    v._steamSet = bodySteam > 0 ? bodySteam : null;
    v._pipeSet = bodyPipe > 0 ? bodyPipe : null;
    v._steamDev = v._steamSet !== null && steam !== null ? steam - v._steamSet : null;
    v._pipeDev = v._pipeSet !== null && pipe !== null ? pipe - v._pipeSet : null;
    v._heaterOn = Number(data.PowerOn) === 1;
    v._paused = Number(data.PauseOn) === 1 || Number(data.BeerManualPause) === 1;
    v._running = v._heaterOn && !v._paused;
    v._withdrawing = Number(data.WthdrwlStatus) > 0 && !v._paused;
    const rate = num(data.ActualVolumePerHour);
    v._pumpOn = kind === 'nbk' ? num(data.ISspd) > 0 && v._running
      : kind === 'beer' || kind === 'cheese' ? !!data.mixer && v._running
      : v._withdrawing && rate > 0;
    v._mixerOn = !!data.mixer && v._running;
    // Второй I2C-насос отбора голов над ЦП (ректификация): ЦП и насос на схеме только
    // если он включён в настройках и плата отвечает; анимация — пока насос качает.
    v._cp = kind === 'rect' && !!Number(data.i2c_second_pump);
    v._noCp = !v._cp;
    v._cpPumpOn = v._cp && !!Number(data.i2c_second_pump_running);
    // Варочный порядок пива (BeerBrewOrder): у HERMS/RIMS вместо мешалки — насос
    // рециркуляции и бойлер/труба с ТЭНом; сыр и су-вид всегда рисуют обычный котёл.
    const order = kind === 'beer' ? String(data.BeerBrewOrder || '') : '';
    v._herms = order === 'herms';
    v._rims = order === 'rims';
    v._recirc = v._herms || v._rims;
    v._allinone = !v._recirc;
    // Вода охлаждения: по клапану (valve_status прошивки) или работающему ШИМ-насосу.
    // У старой прошивки ключа valve нет — тогда, как раньше, по нагреву.
    v._flowOn = data.valve === undefined ? v._heaterOn : (!!data.valve || num(data.wp_spd) > 0);
    const unit = typeof window.pwr_unit === 'string' ? window.pwr_unit : 'V';
    const volt = num(data.current_power_volt), watt = num(data.current_power_p);
    v._powerUnit = unit === 'P' ? 'Вт' : 'В';
    v._powerValue = unit === 'P' ? watt : volt;
    v._heaterText = !v._heaterOn ? 'выключен'
      : unit === 'P' ? (watt !== null ? watt + ' Вт' : '—')
      : (volt !== null ? volt + ' В' : '—') + (watt !== null ? ' · ' + watt + ' Вт' : '');
    v._cubePressure = num(data.prvl);
    v._pressureLabel = v._cubePressure !== null ? 'В кубе' : 'На старте';
    v._pressureAlt = v._cubePressure !== null ? v._cubePressure : num(data.start_pressure);
    v._alcCube = typeof data.alc === 'number' && Number.isFinite(data.alc) && data.alc >= 0
      ? data.alc : null;
    const ds = Number(data.DetectorStatus);
    const detIdle = Number(data.DetectorIdle);
    v._detectorText = !data.useDetector ? 'выкл'
      : data.PrgType === 'H' ? 'наблюдение'
      : detIdle === 5 ? '⏳ ждёт пар'
      : detIdle === 3 || detIdle === 4 || detIdle === 6 ? '⏳ ожидание'
      : detIdle === 7 ? '⏸ пауза'
      : detIdle === 8 ? 'наблюдение'
      : detIdle === 1 ? '—'
      : ds === 0 ? '● стабильно' : ds === 1 ? (data.useautospeed ? '▲ снижаю скорость' : '▲ рост') : ds === 2 ? '■ проскок' : '—';
    v._alcSteam = typeof data.stm_alc === 'number' && Number.isFinite(data.stm_alc) && data.stm_alc >= 0
      ? data.stm_alc : null;

    const lines = programLines();
    const n = Number(data.ProgramNum) || 0;
    v._lineTotal = lines.length;
    v._lineNum = n > 0 && n <= lines.length ? n : null;
    const row = v._lineNum ? parseProgramLine(kind, lines[n - 1]) : null;
    const nextRow = v._lineNum && n < lines.length ? parseProgramLine(kind, lines[n]) : null;
    v._lineType = row ? row.type : '';
    v._lineName = row ? row.name : (lines.length ? 'ожидание' : 'нет программы');
    v._lineCap = row && row.capacity !== null ? row.capacity : null;
    v._jars = jarWindow(kind, lines, v._lineNum);
    v._lineCapText = v._lineCap !== null ? 'ёмкость ' + v._lineCap : '';
    v._lineVolume = row ? row.volume : null;
    v._lineSpeed = row ? row.speed : null;
    v._linePower = row && row.power ? row.power : null;
    v._lineTemp = row ? row.temp : null;
    v._lineValue = row ? row.value : null;
    v._lineSteam = row && row.steam ? row.steam : null;
    v._lineTime = row ? hoursText(row.time) : '—';
    v._lineOf = v._lineNum ? v._lineNum + ' из ' + lines.length : (lines.length ? '0 из ' + lines.length : '—');
    v._next = nextRow ? (n + 1) + ' · ' + nextRow.summary : (row ? 'последняя строка' : '—');
    const progress = num(data.WthdrwlProgress);
    v._progress = progress !== null ? Math.max(0, Math.min(100, progress)) : 0;
    return v;
  }

  function fmtValue(el, value) {
    if (value === undefined || value === null || value === '') return '—';
    if (typeof value === 'number') {
      const digits = el.getAttribute('data-fmt');
      const text = digits !== null ? value.toFixed(Number(digits)) : String(value);
      return el.hasAttribute('data-sign') && value > 0 ? '+' + text : text;
    }
    if (typeof value === 'boolean') return value ? 'да' : 'нет';
    return String(value);
  }

  function renderScheme(data) {
    const v = deriveView(data);
    const all = document.querySelectorAll('[data-tele],[data-on],[data-show],[data-width],[data-jar]');
    for (let i = 0; i < all.length; i++) {
      const el = all[i];
      const key = el.getAttribute('data-tele');
      if (key !== null) el.textContent = fmtValue(el, v[key]);
      const onKey = el.getAttribute('data-on');
      if (onKey !== null) el.classList.toggle('is-on', !!v[onKey]);
      const showKey = el.getAttribute('data-show');
      if (showKey !== null) el.classList.toggle('is-hidden', !v[showKey]);
      const widthKey = el.getAttribute('data-width');
      if (widthKey !== null) {
        const w = num(v[widthKey]);
        el.style.width = (w === null ? 0 : Math.max(0, Math.min(100, w))) + '%';
      }
      const jar = el.getAttribute('data-jar');
      if (jar !== null) {
        const j = v._jars[Number(jar)];
        el.classList.toggle('is-hidden', !j);
        el.classList.toggle('is-on', !!j && j.active);
        const numEl = el.querySelector('.jar-num'), typeEl = el.querySelector('.jar-type');
        if (numEl) numEl.textContent = j ? String(j.num) : '';
        if (typeEl) typeEl.textContent = j ? j.type : '';
        // Заливка текущей банки — процент отбора по строке (вся банка = 100 %).
        const body = el.querySelector('.jar'), fill = el.querySelector('.jar-fill');
        if (body && fill) {
          const inner = Number(body.getAttribute('height')) - 4;
          const fillH = j && j.active ? inner * v._progress / 100 : 0;
          fill.setAttribute('height', String(fillH));
          fill.setAttribute('y', String(2 + inner - fillH));
        }
      }
    }
    return v;
  }

  onTelemetry(renderScheme);

  // Шапка таблицы программы (все режимы). Поля строки на десктопе стоят подряд с
  // фиксированной шириной, а ячейки шапки раньше раскладывались процентами или
  // неразрывными пробелами и уезжали от своих колонок. Выравниваем шапку по первой
  // строке данных: каждой ячейке шапки - отступ и ширина соответствующего поля.
  // На телефоне (поля переносятся в две колонки) inline-стили снимаются.
  const PROGRAM_HEADER_SELECTOR = '#hdr, #cheeseProgramHeader';

  function programRowCells(row) {
    return Array.prototype.filter.call(row.children, function (el) {
      if (el.tagName === 'BUTTON' || el.type === 'hidden' || el.offsetWidth === 0) return false;
      return !(el.tagName === 'SPAN' && el.textContent.trim() === '');
    });
  }

  function programHeaderLabelText(cell) {
    const label = cell.tagName === 'LABEL' ? cell : (cell.querySelector('label') || cell);
    const copy = label.cloneNode(true);
    copy.querySelectorAll('.tooltiptext').forEach(function (t) { t.remove(); });
    return copy.textContent.trim();
  }

  // Телефон: шапка скрыта, у каждого поля своя подпись, строка - сетка «подпись-поле»
  // по две пары в линию. Всё, что вставлено/переопределено, снимается в clearProgramRowMobile().
  function applyProgramRowMobile(row, labels) {
    row.setAttribute('data-prg-mob', '1');
    // Пробельный текст между элементами (в nbk.htm - &nbsp;) в сетке становится
    // отдельной ячейкой; убираем его и возвращаем в clearProgramRowMobile.
    row._prgText = [];
    Array.prototype.slice.call(row.childNodes).forEach(function (n) {
      if (n.nodeType === 3 && !n.textContent.replace(/[\s\u00a0]/g, '')) {
        row._prgText.push([n, n.nextSibling]);
        n.remove();
      }
    });
    row.style.display = 'grid';
    row.style.gridTemplateColumns = 'max-content minmax(0, 1fr) max-content minmax(0, 1fr)';
    row.style.gap = '4px 6px';
    row.style.alignItems = 'center';
    const sources = programRowCells(row);
    Array.prototype.forEach.call(row.children, function (el) {
      if (el.tagName === 'BUTTON' || sources.indexOf(el) !== -1) return;
      el.setAttribute('data-prg-hidden', '1');
      el.style.display = 'none';
    });
    Array.prototype.forEach.call(row.children, function (el) {
      if (el.tagName === 'LABEL' || el.style.marginLeft === '') return;
      el.setAttribute('data-prg-ml', el.style.marginLeft);
      el.style.setProperty('margin-left', '0', 'important');
    });
    sources.forEach(function (el, i) {
      if (el.tagName === 'INPUT' || el.tagName === 'SELECT') el.style.width = '100%';
      // Метка без подписи (например, «№») занимает пару «подпись + поле», иначе
      // все следующие элементы сдвигаются на одну колонку сетки.
      if (el.tagName === 'LABEL' || !labels[i]) { el.style.gridColumn = 'span 2'; return; }
      const tag = document.createElement('span');
      tag.className = 'prg-col-label';
      tag.textContent = labels[i];
      row.insertBefore(tag, el);
    });
  }

  function clearProgramRowMobile(row) {
    if (!row.hasAttribute('data-prg-mob')) return;
    row.removeAttribute('data-prg-mob');
    (row._prgText || []).forEach(function (t) { row.insertBefore(t[0], t[1]); });
    row._prgText = null;
    ['display', 'grid-template-columns', 'gap', 'align-items'].forEach(function (k) { row.style.removeProperty(k); });
    row.querySelectorAll('.prg-col-label').forEach(function (t) { t.remove(); });
    row.querySelectorAll('[data-prg-hidden]').forEach(function (el) {
      el.removeAttribute('data-prg-hidden');
      el.style.removeProperty('display');
    });
    Array.prototype.forEach.call(row.children, function (el) {
      if (el.tagName === 'INPUT' || el.tagName === 'SELECT') el.style.removeProperty('width');
      el.style.removeProperty('grid-column');
      if (el.hasAttribute('data-prg-ml')) {
        el.style.setProperty('margin-left', el.getAttribute('data-prg-ml'), 'important');
        el.removeAttribute('data-prg-ml');
      }
    });
  }

  function programRows(header) {
    return Array.prototype.filter.call(header.parentNode.querySelectorAll('.prgline'), function (el) {
      return !el.matches(PROGRAM_HEADER_SELECTOR);
    });
  }

  function alignProgramHeader(header) {
    const cells = [];
    Array.prototype.slice.call(header.childNodes).forEach(function (node) {
      if (node.nodeType !== 1) { header.removeChild(node); return; }
      if (node.tagName === 'SPAN' && node.textContent.trim() === '') { header.removeChild(node); return; }
      cells.push(node);
    });
    const rows = programRows(header);
    const row = rows[0];
    // Вкладка «Программа» закрыта - мерить нечего; довыравняем при её открытии (openTab).
    if (row && row.getClientRects().length === 0) return;

    // Режим - по факту: сначала снимаем телефонную раскладку и смотрим, уложились ли
    // поля первой строки в одну линию при обычных стилях.
    rows.forEach(clearProgramRowMobile);
    header.style.removeProperty('display');
    const sources = row ? programRowCells(row) : [];
    let wrapped = false;
    if (sources.length > 1) {
      // Сравниваем центры по вертикали: строчная подпись «№» и поле в одной линии
      // отличаются по top на несколько пикселей, перенос - на высоту поля.
      const rects = sources.map(function (el) { return el.getBoundingClientRect(); });
      const tallest = Math.max.apply(null, rects.map(function (r) { return r.height; }));
      const cy0 = rects[0].top + rects[0].height / 2;
      wrapped = rects.some(function (r) { return Math.abs(r.top + r.height / 2 - cy0) > tallest * 0.6; });
    }

    if (wrapped) {
      const labels = cells.map(programHeaderLabelText);
      header.style.display = 'none';
      rows.forEach(function (r) { applyProgramRowMobile(r, labels); });
      return;
    }
    if (!row) {
      ['flex-wrap', 'align-items'].forEach(function (k) { header.style.removeProperty(k); });
      cells.forEach(function (cell) { cell.removeAttribute('style'); });
      return;
    }
    const rowLeft = row.getBoundingClientRect().left;
    header.style.display = 'flex';
    header.style.flexWrap = 'nowrap';
    header.style.alignItems = 'center';
    let prevRight = 0;
    cells.forEach(function (cell, i) {
      const src = sources[i];
      if (!src) { cell.removeAttribute('style'); return; }
      const r = src.getBoundingClientRect();
      cell.style.setProperty('margin-left', (r.left - rowLeft - prevRight) + 'px', 'important');
      cell.style.setProperty('width', r.width + 'px', 'important');
      cell.style.flex = '0 0 auto';
      cell.style.boxSizing = 'border-box';
      cell.style.display = 'flex';
      cell.style.justifyContent = 'center';
      cell.style.textAlign = 'center';
      cell.style.whiteSpace = 'normal';
      cell.style.lineHeight = '1.1';
      prevRight = r.right - rowLeft;
    });
  }

  function alignProgramHeaders() {
    document.querySelectorAll(PROGRAM_HEADER_SELECTOR).forEach(alignProgramHeader);
  }

  let programHeaderAlignPending = false;
  function scheduleProgramHeaderAlign() {
    if (programHeaderAlignPending) return;
    programHeaderAlignPending = true;
    window.requestAnimationFrame(function () {
      programHeaderAlignPending = false;
      alignProgramHeaders();
    });
  }

  // typeof-проверка: smoke-тесты гоняют app.js в Node (vm) без DOM-наблюдателя.
  if (typeof MutationObserver !== 'undefined') {
    new MutationObserver(function (mutations) {
      for (let i = 0; i < mutations.length; i++) {
        const added = mutations[i].addedNodes;
        for (let j = 0; j < added.length; j++) {
          const node = added[j];
          if (node.nodeType === 1 && (node.classList.contains('prgline') || node.matches(PROGRAM_HEADER_SELECTOR))) {
            scheduleProgramHeaderAlign();
            return;
          }
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
    window.addEventListener('resize', scheduleProgramHeaderAlign);
    window.addEventListener('load', scheduleProgramHeaderAlign);
  }

  // Реальная высота шапки .top (ряд вкладок переносится на вторую строку, и
  // фиксированные 56px в --top-h не совпадают). Всплывающие блоки берут --top-real.
  function trackHeaderHeight() {
    const top = document.querySelector('.top');
    if (!top) return;
    function apply() {
      document.documentElement.style.setProperty('--top-real', Math.round(top.getBoundingClientRect().height) + 'px');
    }
    apply();
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(apply).observe(top);
    window.addEventListener('resize', apply);
  }

  // Подсветка текущего раздела в навигации второстепенных страниц (расчёт, график, настройки).
  function markCurrentNavLink() {
    const path = location.pathname.replace(/^\/+/, '');
    document.querySelectorAll('.page-nav .nav-link').forEach(function (link) {
      const href = (link.getAttribute('href') || '').replace(/^\/+/, '');
      if (href && href === path) link.setAttribute('aria-current', 'page');
    });
  }

  function showCalculationNavForMode(mode) {
    const link = document.querySelector('.page-nav a[href="/program.htm"]');
    if (link) link.hidden = Number(mode) !== 0;
  }

  // На телефоне карточка «Действия» - фиксированная панель внизу, но лежит внутри
  // вкладки «Режим»: при переходе на «Программа» кнопка выключения нагрева пропадала.
  // Выносим панель из вкладки на узком экране и возвращаем на место на широком.
  function relocateActionsPanel() {
    if (typeof matchMedia !== 'function') return;
    const panel = document.querySelector('.sec-actions');
    const form = panel && panel.closest('form');
    if (!panel || !form) return;
    const placeholder = document.createComment('sec-actions');
    const mq = matchMedia('(max-width: 640px)');
    function apply() {
      if (mq.matches && panel.parentNode !== form) {
        panel.parentNode.insertBefore(placeholder, panel);
        form.appendChild(panel);
      } else if (!mq.matches && placeholder.parentNode) {
        placeholder.parentNode.insertBefore(panel, placeholder);
        placeholder.parentNode.removeChild(placeholder);
      }
    }
    apply();
    if (typeof mq.addEventListener === 'function') mq.addEventListener('change', apply);
  }

  // Несохранённые правки таблицы программы: вкладки «График», «Настройки», «Расчёт»
  // в шапке ведут на другие страницы, и правки терялись молча. Ссылки спрашивают
  // confirmLeave() - как confirmLeaveIfDirty() в setup.htm.
  let programDirty = false;
  let programRevision = 0;
  function markProgramDirty() {
    programDirty = true;
    programRevision += 1;
  }

  function trackProgramDirty() {
    const prog = byId('Prog');
    if (!prog) return;
    prog.addEventListener('input', markProgramDirty);
    prog.addEventListener('change', markProgramDirty);
  }

  function markProgramSaved(revision) {
    if (revision === undefined || revision === programRevision) programDirty = false;
  }

  function confirmLeave() {
    return !programDirty || confirm('Программа изменена, но не установлена. Уйти без сохранения?');
  }

  function setupPageChrome() {
    trackHeaderHeight();
    markCurrentNavLink();
    relocateActionsPanel();
    trackProgramDirty();
  }

  // Тесты грузят app.js в Node без DOM и location - тогда оформление страницы не нужно.
  if (typeof window !== 'undefined' && typeof location !== 'undefined' &&
      typeof document.querySelector === 'function') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setupPageChrome);
    else setupPageChrome();
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
    beerRowTypeOk: beerRowTypeOk,
    beerBrewOrders: beerBrewOrders,
    beerBrewOrder: beerBrewOrder,
    beerProgramMaxRows: BEER_PROGRAM_MAX_ROWS,
    beerProgramRow: beerProgramRow,
    beerSensorOptionHtml: beerSensorOptionHtml,
    normalizeMashStepType: normalizeMashStepType,
    effectiveMashKind: effectiveMashKind,
    applyBeerBrewOrderToProgramText: applyBeerBrewOrderToProgramText,
    buildBeerMashStageLines: buildBeerMashStageLines,
    setConfiguredBeerBrewOrder: setConfiguredBeerBrewOrder,
    currentBeerBrewOrderId: currentBeerBrewOrderId,
    clearProgram: clearProgram,
    clearHistory: clearHistory,
    clearMessages: clearMessages,
    closeDeviceScheduleModal: closeDeviceScheduleModal,
    clearRequestError: clearRequestError,
    clearRequestErrorIfUnchanged: clearRequestErrorIfUnchanged,
    cssVar: cssVar,
    detectorIdleText: detectorIdleText,
    currentRequestErrorRevision: currentRequestErrorRevision,
    descriptionByteLength: descriptionByteLength,
    deviceScheduleMaxSeconds: 65535,
    alignProgramHeaders: alignProgramHeaders,
    enhanceTooltips: enhanceTooltips,
    escapeHtml: escapeHtml,
    fetchJson: fetchJson,
    fieldLabelFromDom: fieldLabelFromDom,
    init: init,
    initTheme: initTheme,
    loadUiBootstrap: loadUiBootstrap,
    notify: notify,
    normalizeDeviceScheduleSeconds: normalizeDeviceScheduleSeconds,
    openDeviceScheduleModal: openDeviceScheduleModal,
    addLuaProgramArgument: addLuaProgramArgument,
    closeLuaProgramModal: closeLuaProgramModal,
    openLuaProgramModal: openLuaProgramModal,
    openTab: openTab,
    onRuntimePair: onRuntimePair,
    onTelemetry: onTelemetry,
    pollAjax: pollAjax,
    renderScheme: renderScheme,
    postProgram: postProgram,
    readOperationAcceptance: readOperationAcceptance,
    renderI2cPumpStatus: renderI2cPumpStatus,
    renderUiDetails: renderUiDetails,
    uiWaitReasonName: uiWaitReasonName,
    renderTelemetryCommon: renderTelemetryCommon,
    removeLastMessage: removeLastMessage,
    removeMessage: removeMessage,
    markProgramSaved: markProgramSaved,
    markProgramDirty: markProgramDirty,
    confirmLeave: confirmLeave,
    showCalculationNavForMode: showCalculationNavForMode,
    reportUiError: reportUiError,
    readNumericInput: readNumericInput,
    responseErrorText: responseErrorText,
    runLua: runLua,
    runLuaString: runLuaString,
    sendCommand: sendCommand,
    sendI2cPump: sendI2cPump,
    sendNumericCommand: sendNumericCommand,
    sendPowerCommand: sendPowerCommand,
    saveDeviceScheduleModal: saveDeviceScheduleModal,
    saveLuaProgramModal: saveLuaProgramModal,
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
