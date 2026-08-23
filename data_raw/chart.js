(function () {
  'use strict';

  const SERIES = [
    { key: 'Steam', label: 'Температура пара', color: '#d9534f' },
    { key: 'Pipe', label: 'Температура в царге', color: '#2d7fb8' },
    { key: 'Water', label: 'Температура воды', color: '#168a96' },
    { key: 'Tank', label: 'Температура в кубе', color: '#4f8f45' },
    { key: 'Pressure', label: 'Давление', color: '#a66e00' },
    { key: 'ProgNum', label: 'Строка программы', color: '#777777' }
  ];
  // Давление живёт в единицах мм рт.ст. (около 760) - на общей шкале с температурами
  // (десятки градусов) оно сплющивает все линии температур в полосу у нижнего края.
  // Переносим его на отдельную шкалу справа средствами уже существующего самописного
  // canvas-графика (внешней библиотеки графиков в проекте нет). Список вынесен из SERIES
  // отдельной константой, чтобы не менять форму объектов SERIES (её пинит смоук-тест U-03).
  const RIGHT_AXIS_SERIES = { Pressure: true };
  const MAX_RENDER_POINTS = 600;
  const LOAD_TIMEOUT_MS = 15000;

  function parseNumber(value) {
    if (value === undefined || value === null || value === '') return null;
    const num = Number(String(value).replace(',', '.'));
    return Number.isFinite(num) ? num : null;
  }

  function parseCsvLine(line) {
    const cells = [];
    let current = '';
    let quoted = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (quoted && line[i + 1] === '"') {
          current += '"';
          i++;
        } else {
          quoted = !quoted;
        }
      } else if (ch === ',' && !quoted) {
        cells.push(current);
        current = '';
      } else {
        current += ch;
      }
    }
    cells.push(current);
    return cells;
  }

  function parseCsv(text) {
    const lines = text.split(/\r?\n/).filter(function (line) { return line.trim() !== ''; });
    if (lines.length === 0) return [];
    const headers = parseCsvLine(lines[0]).map(function (item) { return item.trim(); });
    const rows = [];
    for (let i = 1; i < lines.length; i++) {
      const cells = parseCsvLine(lines[i]);
      const row = {};
      headers.forEach(function (header, index) {
        row[header] = cells[index] === undefined ? '' : cells[index].trim();
      });
      rows.push(normalizeRow(row));
    }
    return rows;
  }

  function normalizeRow(row) {
    const normalized = { Date: row.Date || '' };
    SERIES.forEach(function (series) {
      normalized[series.key] = parseNumber(row[series.key]);
    });
    return normalized;
  }

  function ajaxToRow(data) {
    return normalizeRow({
      Date: data.crnt_tm || new Date().toLocaleTimeString('ru-RU'),
      Steam: data.SteamTemp,
      Pipe: data.PipeTemp,
      Water: data.WaterTemp,
      Tank: data.TankTemp,
      Pressure: data.bme_pressure,
      ProgNum: data.ProgNum
    });
  }

  function createCanvas(parent, hiddenSeries) {
    parent.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'chart-panel';
    const canvas = document.createElement('canvas');
    canvas.className = 'chart-canvas';
    canvas.height = 500;
    const status = document.createElement('div');
    status.className = 'chart-status';
    const legend = document.createElement('div');
    legend.className = 'chart-legend';
    SERIES.forEach(function (series) {
      if (hiddenSeries && hiddenSeries[series.key]) return;
      const item = document.createElement('span');
      item.className = 'chart-legend-item';
      const swatch = document.createElement('span');
      swatch.className = 'chart-legend-swatch';
      swatch.style.backgroundColor = series.color;
      item.appendChild(swatch);
      var labelText = series.label + (RIGHT_AXIS_SERIES[series.key] ? ' (шкала справа)' : '');
      item.appendChild(document.createTextNode(labelText));
      legend.appendChild(item);
    });
    wrap.appendChild(canvas);
    wrap.appendChild(status);
    wrap.appendChild(legend);
    parent.appendChild(wrap);
    return { canvas: canvas, status: status };
  }

  function decimate(rows) {
    if (rows.length <= MAX_RENDER_POINTS) return rows;
    const step = Math.ceil(rows.length / MAX_RENDER_POINTS);
    const result = [];
    for (let i = 0; i < rows.length; i += step) result.push(rows[i]);
    const last = rows[rows.length - 1];
    if (result[result.length - 1] !== last) result.push(last);
    return result;
  }

  function valueBounds(rows, keys) {
    let min = Infinity;
    let max = -Infinity;
    rows.forEach(function (row) {
      keys.forEach(function (key) {
        const value = row[key];
        if (value === null) return;
        if (value < min) min = value;
        if (value > max) max = value;
      });
    });
    if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const pad = (max - min) * 0.08;
    return { min: min - pad, max: max + pad };
  }

  function drawGrid(ctx, area, bounds, secondaryBounds, secondaryColor, textColor, gridColor) {
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.font = '12px sans-serif';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= 4; i++) {
      const y = area.top + area.height * i / 4;
      ctx.beginPath();
      ctx.moveTo(area.left, y);
      ctx.lineTo(area.left + area.width, y);
      ctx.stroke();
      if (bounds) {
        ctx.fillStyle = textColor;
        ctx.textAlign = 'right';
        const value = bounds.max - (bounds.max - bounds.min) * i / 4;
        ctx.fillText(value.toFixed(1), area.left - 8, y);
      }
      if (secondaryBounds) {
        ctx.fillStyle = secondaryColor || textColor;
        ctx.textAlign = 'left';
        const value2 = secondaryBounds.max - (secondaryBounds.max - secondaryBounds.min) * i / 4;
        ctx.fillText(value2.toFixed(1), area.left + area.width + 8, y);
      }
    }
  }

  function drawSeries(ctx, rows, area, bounds, series) {
    ctx.strokeStyle = series.color;
    ctx.lineWidth = series.key === 'ProgNum' ? 1.5 : 2;
    ctx.beginPath();
    let started = false;
    rows.forEach(function (row, index) {
      const value = row[series.key];
      if (value === null) {
        started = false;
        return;
      }
      const x = rows.length === 1 ? area.left : area.left + area.width * index / (rows.length - 1);
      const y = area.top + area.height - ((value - bounds.min) / (bounds.max - bounds.min)) * area.height;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();
  }

  function SamovarChart(elementId, options) {
    this.parent = document.getElementById(elementId);
    if (!this.parent) throw new Error('Chart container not found: ' + elementId);
    this.rows = [];
    this.loading = false;
    this.autoRefresh = true;
    this.lastDate = '';
    this.options = options || {};
    this.hiddenSeries = this.options.hidden || {};
    const elements = createCanvas(this.parent, this.hiddenSeries);
    this.canvas = elements.canvas;
    this.status = elements.status;
    window.addEventListener('resize', this.draw.bind(this));
  }

  // retryFn - необязательный обработчик кнопки "Повторить" для сообщений об ошибке;
  // без него график ведёт себя как раньше (просто текст статуса).
  SamovarChart.prototype.setStatus = function (text, isError, retryFn) {
    this.status.innerHTML = '';
    this.status.className = isError ? 'chart-status chart-status-error' : 'chart-status';
    this.status.appendChild(document.createTextNode(text || ''));
    if (isError && retryFn) {
      const retryBtn = document.createElement('button');
      retryBtn.type = 'button';
      retryBtn.className = 'button';
      retryBtn.style.marginLeft = '0.6em';
      retryBtn.textContent = 'Повторить';
      retryBtn.addEventListener('click', retryFn);
      this.status.appendChild(retryBtn);
    }
  };

  SamovarChart.prototype.setData = function (rows) {
    this.rows = rows || [];
    this.lastDate = this.rows.length ? this.rows[this.rows.length - 1].Date : '';
    this.draw();
  };

  // Загрузка графика была единственным местом в проекте без ограничения времени
  // ожидания: при обрыве связи fetch мог висеть бесконечно, и страница навсегда
  // оставалась на "Загрузка графика...". Таймаут и повторная попытка сделаны так же,
  // как в app.js (AbortController + showRequestError-подобное сообщение с кнопкой).
  SamovarChart.prototype.loadCsv = async function (url) {
    // Вторая загрузка поверх незавершённой первой дала бы две гонки за this.rows,
    // поэтому повторные вызовы (кнопка "Повторить", автообновление) отбиваются.
    if (this.loading) return false;
    this.loading = true;
    const self = this;
    const retry = function () { self.loadCsv(url); };
    this.setStatus('Загрузка графика...', false);
    const ctrl = new AbortController();
    const timer = setTimeout(function () { ctrl.abort(); }, LOAD_TIMEOUT_MS);
    let resp;
    try {
      resp = await fetch(url, { cache: 'no-store', signal: ctrl.signal });
    } catch (err) {
      const timedOut = err && err.name === 'AbortError';
      this.setStatus(
        'Ошибка загрузки графика: ' + (timedOut ? 'превышено время ожидания.' : err),
        true, retry
      );
      this.loading = false;
      return false;
    } finally {
      clearTimeout(timer);
    }
    if (!resp.ok) {
      this.setStatus('Ошибка загрузки графика: HTTP ' + resp.status, true, retry);
      this.loading = false;
      return false;
    }
    try {
      const text = await resp.text();
      this.setData(parseCsv(text));
      this.setStatus(this.rows.length ? 'Загружено точек: ' + this.rows.length : 'Нет данных графика.', false);
    } finally {
      this.loading = false;
    }
    return true;
  };

  SamovarChart.prototype.setAutoRefresh = function (enabled) {
    this.autoRefresh = !!enabled;
    this.setStatus(this.autoRefresh ? 'Автообновление графика включено.' : 'Автообновление графика остановлено.', false);
  };

  SamovarChart.prototype.appendAjaxPoint = function (data) {
    if (!this.autoRefresh || !data) return;
    const row = ajaxToRow(data);
    if (!row.Date || row.Date === this.lastDate) return;
    this.rows.push(row);
    this.lastDate = row.Date;
    this.draw();
  };

  SamovarChart.prototype.draw = function () {
    const canvas = this.canvas;
    const rect = this.parent.getBoundingClientRect();
    const width = Math.max(320, Math.floor(rect.width || canvas.clientWidth || 800));
    const height = Math.max(320, Math.floor(canvas.clientHeight || 500));
    const scale = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * scale);
    canvas.height = Math.floor(height * scale);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      this.setStatus('График недоступен: canvas не поддерживается.', true);
      return;
    }
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    const styles = getComputedStyle(document.documentElement);
    const bgColor = styles.getPropertyValue('--bg-form').trim() || '#fff';
    const textColor = styles.getPropertyValue('--text-strong').trim() || '#000';
    const gridColor = styles.getPropertyValue('--border-soft').trim() || '#ccc';
    ctx.fillStyle = bgColor;
    ctx.fillRect(0, 0, width, height);
    const rows = decimate(this.rows);
    const visibleSeries = SERIES.filter(function (series) { return !this.hiddenSeries[series.key]; }, this);
    // Раздельные шкалы: primary - температуры и номер строки программы (левая ось),
    // secondary - давление, у него совсем другой порядок значений (около 760).
    const primarySeries = visibleSeries.filter(function (series) { return !RIGHT_AXIS_SERIES[series.key]; });
    const secondarySeries = visibleSeries.filter(function (series) { return RIGHT_AXIS_SERIES[series.key]; });
    const bounds = valueBounds(rows, primarySeries.map(function (series) { return series.key; }));
    const secondaryBounds = valueBounds(rows, secondarySeries.map(function (series) { return series.key; }));
    const rightMargin = secondaryBounds ? 54 : 20;
    const area = { left: 54, top: 18, width: width - 54 - rightMargin, height: height - 58 };
    if (!bounds && !secondaryBounds) {
      ctx.fillStyle = textColor;
      ctx.font = '16px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Нет данных для графика', width / 2, height / 2);
      return;
    }
    const secondaryColor = secondarySeries.length ? secondarySeries[0].color : null;
    drawGrid(ctx, area, bounds, secondaryBounds, secondaryColor, textColor, gridColor);
    primarySeries.forEach(function (series) {
      drawSeries(ctx, rows, area, bounds, series);
    });
    secondarySeries.forEach(function (series) {
      drawSeries(ctx, rows, area, secondaryBounds, series);
    });
    ctx.fillStyle = textColor;
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    if (rows.length > 0) ctx.fillText(rows[0].Date || '', area.left, area.top + area.height + 12);
    if (rows.length > 1) {
      ctx.textAlign = 'right';
      ctx.fillText(rows[rows.length - 1].Date || '', area.left + area.width, area.top + area.height + 12);
    }
  };

  window.SamovarChart = SamovarChart;
})();
