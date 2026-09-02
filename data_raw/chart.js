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
  // Три шкалы как в 6.27: температуры слева, давление справа, номер программы
  // на своей оси на всю высоту. Форму объектов SERIES не меняем (смоук U-03).
  const RIGHT_AXIS_SERIES = { Pressure: true };
  const PROG_AXIS_SERIES = { ProgNum: true };
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
      ProgNum: data.ProgramNum
    });
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  // Ручка границы участка. Это не <input type="range">: две отдельные ручки на
  // одной полосе, как у скроллбара amCharts, нужны именно как границы окна.
  function createGrip(label) {
    const grip = document.createElement('div');
    grip.className = 'chart-range-grip';
    grip.tabIndex = 0;
    grip.setAttribute('role', 'slider');
    grip.setAttribute('aria-label', label);
    return grip;
  }

  function setGripValue(grip, index, total, row) {
    grip.setAttribute('aria-valuemin', '1');
    grip.setAttribute('aria-valuemax', String(total));
    grip.setAttribute('aria-valuenow', String(index + 1));
    grip.setAttribute('aria-valuetext', (row && row.Date) ? row.Date : String(index + 1));
  }

  function createCanvas(parent) {
    parent.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'chart-panel';
    const canvas = document.createElement('canvas');
    canvas.className = 'chart-canvas';
    canvas.height = 500;
    canvas.setAttribute('role', 'img');
    canvas.setAttribute(
      'aria-label',
      'График. Наведение показывает значения; участок задают ползунки под графиком.'
    );
    const status = document.createElement('div');
    status.className = 'chart-status';
    const legend = document.createElement('div');
    legend.className = 'chart-legend';
    legend.setAttribute('role', 'group');
    legend.setAttribute('aria-label', 'Ряды графика, нажатие включает и выключает');
    const range = document.createElement('div');
    range.className = 'chart-range';
    range.setAttribute('role', 'group');
    range.setAttribute('aria-label', 'Участок графика');
    const fill = document.createElement('div');
    fill.className = 'chart-range-fill';
    const gripFrom = createGrip('Начало участка');
    const gripTo = createGrip('Конец участка');
    // Стартовый вид до первой отрисовки: участок во всю полосу, ручки по краям.
    fill.style.width = '100%';
    gripTo.style.left = '100%';
    range.appendChild(fill);
    range.appendChild(gripFrom);
    range.appendChild(gripTo);
    const readout = document.createElement('div');
    readout.className = 'chart-readout';
    wrap.appendChild(canvas);
    wrap.appendChild(range);
    wrap.appendChild(readout);
    wrap.appendChild(status);
    wrap.appendChild(legend);
    parent.appendChild(wrap);
    return {
      canvas: canvas, status: status, legend: legend,
      range: range, fill: fill, gripFrom: gripFrom, gripTo: gripTo, readout: readout
    };
  }

  function yFromValue(value, bounds, area) {
    return area.top + area.height - ((value - bounds.min) / (bounds.max - bounds.min)) * area.height;
  }

  function seriesStrokeWidth(key) {
    if (key === 'ProgNum') return 1.5;
    if (key === 'Pressure') return 2;
    return 3;
  }

  function seriesAxis(key) {
    if (RIGHT_AXIS_SERIES[key]) return 'pressure';
    if (PROG_AXIS_SERIES[key]) return 'prog';
    return 'temp';
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
    if (!bounds || rows.length === 0) return;
    ctx.strokeStyle = series.color;
    ctx.lineWidth = seriesStrokeWidth(series.key);
    ctx.beginPath();
    const n = rows.length;
    const cols = Math.max(1, Math.floor(area.width));
    let started = false;
    function plotX(px, value) {
      const y = yFromValue(value, bounds, area);
      if (!started) {
        ctx.moveTo(px, y);
        started = true;
      } else {
        ctx.lineTo(px, y);
      }
    }
    if (n <= cols) {
      rows.forEach(function (row, index) {
        const value = row[series.key];
        if (value === null) {
          started = false;
          return;
        }
        const x = n === 1 ? area.left : area.left + area.width * index / (n - 1);
        plotX(x, value);
      });
    } else {
      // По каждому столбцу пикселя берём min и max всех точек в корзине - так
      // видны пики всего лога, а не каждая N-я точка (лимит 600 это прятал).
      for (let col = 0; col < cols; col++) {
        const i0 = Math.floor(col * n / cols);
        const i1 = Math.max(i0 + 1, Math.floor((col + 1) * n / cols));
        let min = Infinity;
        let max = -Infinity;
        for (let i = i0; i < i1 && i < n; i++) {
          const value = rows[i][series.key];
          if (value === null) continue;
          if (value < min) min = value;
          if (value > max) max = value;
        }
        if (!Number.isFinite(min)) {
          started = false;
          continue;
        }
        const px = area.left + col + 0.5;
        plotX(px, max);
        if (max !== min) ctx.lineTo(px, yFromValue(min, bounds, area));
      }
    }
    ctx.stroke();
  }

  function formatHoverValue(key, value) {
    if (value === null) return null;
    if (key === 'ProgNum') return String(Math.round(value));
    if (key === 'Pressure') return value.toFixed(2);
    return value.toFixed(3);
  }

  function drawHoverCursor(ctx, area, x, dateText, labels, bgColor, textColor) {
    ctx.save();
    ctx.strokeStyle = textColor;
    ctx.globalAlpha = 0.45;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, area.top);
    ctx.lineTo(x, area.top + area.height);
    ctx.stroke();
    ctx.globalAlpha = 1;

    ctx.font = '12px sans-serif';
    ctx.textBaseline = 'middle';
    const placeRight = x < area.left + area.width * 0.62;
    const padX = 6;
    const boxH = 18;
    labels.sort(function (a, b) { return a.y - b.y; });
    let lastBottom = area.top - 2;
    labels.forEach(function (item) {
      let y = clamp(item.y, area.top + 9, area.top + area.height - 9);
      if (y < lastBottom + boxH) y = Math.min(area.top + area.height - 9, lastBottom + boxH);
      lastBottom = y;
      ctx.beginPath();
      ctx.fillStyle = item.color;
      ctx.arc(x, clamp(item.y, area.top, area.top + area.height), 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = bgColor;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      const tw = ctx.measureText(item.text).width;
      const bw = tw + padX * 2;
      let bx = placeRight ? x + 10 : x - 10 - bw;
      bx = clamp(bx, area.left, area.left + area.width - bw);
      const by = y - boxH / 2;
      ctx.fillStyle = bgColor;
      ctx.globalAlpha = 0.92;
      ctx.fillRect(bx, by, bw, boxH);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = item.color;
      ctx.lineWidth = 1;
      ctx.strokeRect(bx, by, bw, boxH);
      ctx.fillStyle = item.color;
      ctx.textAlign = 'left';
      ctx.fillText(item.text, bx + padX, y);
    });

    if (dateText) {
      const tw = ctx.measureText(dateText).width;
      const bw = tw + 10;
      let bx = clamp(x - bw / 2, area.left, area.left + area.width - bw);
      const by = area.top + area.height + 2;
      ctx.fillStyle = bgColor;
      ctx.fillRect(bx, by, bw, 16);
      ctx.fillStyle = textColor;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(dateText, bx + bw / 2, by + 1);
    }
    ctx.restore();
  }

  function SamovarChart(elementId, options) {
    this.parent = document.getElementById(elementId);
    if (!this.parent) throw new Error('Chart container not found: ' + elementId);
    this.rows = [];
    this.loading = false;
    this.autoRefresh = true;
    this.lastDate = '';
    this.options = options || {};
    this.hiddenSeries = Object.assign({}, this.options.hidden || {});
    this.viewFrom = 0;
    this.viewTo = null;
    this.hoverIndex = null;
    this._plot = { left: 54, width: 1 };
    const elements = createCanvas(this.parent);
    this.canvas = elements.canvas;
    this.status = elements.status;
    this.legend = elements.legend;
    this.range = elements.range;
    this.fill = elements.fill;
    this.gripFrom = elements.gripFrom;
    this.gripTo = elements.gripTo;
    this.readout = elements.readout;
    this.renderLegend();
    this.bindPlot();
    window.addEventListener('resize', this.draw.bind(this));
  }

  SamovarChart.prototype.renderLegend = function () {
    const self = this;
    this.legend.innerHTML = '';
    SERIES.forEach(function (series) {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'chart-legend-item';
      if (self.hiddenSeries[series.key]) item.classList.add('is-hidden');
      item.setAttribute('aria-pressed', self.hiddenSeries[series.key] ? 'false' : 'true');
      const swatch = document.createElement('span');
      swatch.className = 'chart-legend-swatch';
      swatch.style.backgroundColor = series.color;
      item.appendChild(swatch);
      var labelText = series.label;
      if (RIGHT_AXIS_SERIES[series.key]) labelText += ' (шкала справа)';
      else if (PROG_AXIS_SERIES[series.key]) labelText += ' (своя шкала)';
      item.appendChild(document.createTextNode(labelText));
      item.addEventListener('click', function () { self.toggleSeries(series.key); });
      self.legend.appendChild(item);
    });
  };

  SamovarChart.prototype.toggleSeries = function (key) {
    this.hiddenSeries[key] = !this.hiddenSeries[key];
    this.renderLegend();
    this.draw();
  };

  SamovarChart.prototype.span = function () {
    const n = this.rows.length;
    if (n === 0) return { from: 0, to: 0 };
    const from = clamp(this.viewFrom | 0, 0, n - 1);
    const to = this.viewTo == null ? n - 1 : clamp(this.viewTo | 0, from, n - 1);
    return { from: from, to: to };
  };

  SamovarChart.prototype.viewRows = function () {
    const span = this.span();
    return this.rows.slice(span.from, span.to + 1);
  };

  SamovarChart.prototype.setView = function (from, to) {
    const n = this.rows.length;
    if (n === 0) {
      this.viewFrom = 0;
      this.viewTo = null;
      return;
    }
    let a = clamp(Math.min(from, to) | 0, 0, n - 1);
    let b = clamp(Math.max(from, to) | 0, 0, n - 1);
    if (b - a < 4) b = clamp(a + 4, 0, n - 1);
    this.viewFrom = a;
    this.viewTo = b >= n - 1 ? null : b;
    this.draw();
  };

  SamovarChart.prototype.resetView = function () {
    this.viewFrom = 0;
    this.viewTo = null;
    this.draw();
  };

  SamovarChart.prototype.xToIndex = function (offsetX) {
    const span = this.span();
    const n = Math.max(1, span.to - span.from);
    const t = (offsetX - this._plot.left) / this._plot.width;
    return clamp(span.from + Math.round(t * n), 0, Math.max(0, this.rows.length - 1));
  };

  SamovarChart.prototype.bindPlot = function () {
    const self = this;
    const canvas = this.canvas;
    let hoverRaf = 0;

    canvas.addEventListener('pointermove', function (event) {
      self.hoverIndex = self.xToIndex(event.offsetX);
      if (hoverRaf) return;
      hoverRaf = requestAnimationFrame(function () {
        hoverRaf = 0;
        self.draw();
      });
    });
    canvas.addEventListener('pointerleave', function () {
      self.hoverIndex = null;
      self.draw();
    });

    this.bindRange();
  };

  // Масштаб задают только две ручки под графиком: колёсико и выделение рамкой
  // умели лишь приближать, а вернуть обзор на приборе было нечем.
  SamovarChart.prototype.bindRange = function () {
    const self = this;
    const range = this.range;
    const MIN_SPAN = 4;

    // Полоса всегда показывает ВЕСЬ лог, поэтому точка под курсором считается
    // от полной длины, а не от видимого участка.
    function indexAt(clientX) {
      const rect = range.getBoundingClientRect();
      const t = clamp((clientX - rect.left) / Math.max(1, rect.width), 0, 1);
      return Math.round(t * Math.max(0, self.rows.length - 1));
    }

    let drag = null;
    range.addEventListener('pointerdown', function (event) {
      if (self.rows.length < 8) return;
      range.setPointerCapture(event.pointerId);
      event.preventDefault();
      if (event.target === self.gripFrom || event.target === self.gripTo) {
        drag = { mode: event.target === self.gripFrom ? 'from' : 'to' };
        return;
      }
      const count = self.span().to - self.span().from + 1;
      if (event.target !== self.fill) {
        // Щелчок мимо участка переносит окно того же размера сюда.
        const from = clamp(indexAt(event.clientX) - Math.round(count / 2), 0, self.rows.length - count);
        self.setView(from, from + count - 1);
      }
      drag = { mode: 'pan', at: indexAt(event.clientX), from: self.span().from, count: count };
    });

    range.addEventListener('pointermove', function (event) {
      if (!drag) return;
      const idx = indexAt(event.clientX);
      const span = self.span();
      if (drag.mode === 'from') self.setView(Math.min(idx, span.to - MIN_SPAN), span.to);
      else if (drag.mode === 'to') self.setView(span.from, Math.max(idx, span.from + MIN_SPAN));
      else {
        const from = clamp(drag.from + idx - drag.at, 0, self.rows.length - drag.count);
        self.setView(from, from + drag.count - 1);
      }
    });

    function stopDrag() { drag = null; }
    range.addEventListener('pointerup', stopDrag);
    range.addEventListener('pointercancel', stopDrag);
    range.addEventListener('dblclick', function () { self.resetView(); });

    // Ручка объявлена слайдером, значит обязана слушаться стрелок.
    function nudge(which, delta) {
      const span = self.span();
      if (which === 'from') self.setView(clamp(span.from + delta, 0, span.to - MIN_SPAN), span.to);
      else self.setView(span.from, clamp(span.to + delta, span.from + MIN_SPAN, self.rows.length - 1));
    }
    function onKey(which) {
      return function (event) {
        const step = Math.max(1, Math.round(self.rows.length / 50));
        if (event.key === 'ArrowLeft') nudge(which, -step);
        else if (event.key === 'ArrowRight') nudge(which, step);
        else if (event.key === 'Home') nudge(which, -self.rows.length);
        else if (event.key === 'End') nudge(which, self.rows.length);
        else return;
        event.preventDefault();
      };
    }
    this.gripFrom.addEventListener('keydown', onKey('from'));
    this.gripTo.addEventListener('keydown', onKey('to'));
  };

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
    this.viewFrom = 0;
    this.viewTo = null;
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
      this.setStatus(
        (this.rows.length ? 'Загружено точек: ' + this.rows.length + '. ' : 'Нет данных графика. ') +
        'Ползунки под графиком задают участок, двойной щелчок по полосе — весь график, легенда — вкл/выкл, наведение — значения.',
        false
      );
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
    const atEnd = this.viewTo == null || this.viewTo >= this.rows.length - 1;
    this.rows.push(row);
    this.lastDate = row.Date;
    if (atEnd) this.viewTo = null;
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
    const rows = this.viewRows();
    const visibleSeries = SERIES.filter(function (series) { return !this.hiddenSeries[series.key]; }, this);
    const tempSeries = visibleSeries.filter(function (series) { return seriesAxis(series.key) === 'temp'; });
    const pressureSeries = visibleSeries.filter(function (series) { return seriesAxis(series.key) === 'pressure'; });
    const progSeries = visibleSeries.filter(function (series) { return seriesAxis(series.key) === 'prog'; });
    const tempBounds = valueBounds(rows, tempSeries.map(function (series) { return series.key; }));
    const pressureBounds = valueBounds(rows, pressureSeries.map(function (series) { return series.key; }));
    const progBounds = valueBounds(rows, progSeries.map(function (series) { return series.key; }));
    const rightMargin = pressureBounds ? 54 : 20;
    const area = { left: 54, top: 18, width: width - 54 - rightMargin, height: height - 58 };
    this._plot = { left: area.left, width: Math.max(1, area.width) };
    if (!tempBounds && !pressureBounds && !progBounds) {
      ctx.fillStyle = textColor;
      ctx.font = '16px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Нет данных для графика', width / 2, height / 2);
      this.updateChrome(rows);
      return;
    }
    const pressureColor = pressureSeries.length ? pressureSeries[0].color : null;
    drawGrid(ctx, area, tempBounds, pressureBounds, pressureColor, textColor, gridColor);
    tempSeries.forEach(function (series) {
      drawSeries(ctx, rows, area, tempBounds, series);
    });
    pressureSeries.forEach(function (series) {
      drawSeries(ctx, rows, area, pressureBounds, series);
    });
    progSeries.forEach(function (series) {
      drawSeries(ctx, rows, area, progBounds, series);
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
    if (this.hoverIndex != null && rows.length > 0) {
      const span = this.span();
      const hi = clamp(this.hoverIndex, span.from, span.to);
      const local = hi - span.from;
      const x = rows.length === 1 ? area.left : area.left + area.width * local / Math.max(1, rows.length - 1);
      const row = this.rows[hi];
      const axisBounds = { temp: tempBounds, pressure: pressureBounds, prog: progBounds };
      const labels = [];
      visibleSeries.forEach(function (series) {
        const value = row[series.key];
        const bounds = axisBounds[seriesAxis(series.key)];
        const text = formatHoverValue(series.key, value);
        if (text === null || !bounds) return;
        labels.push({
          y: yFromValue(value, bounds, area),
          color: series.color,
          text: text
        });
      });
      drawHoverCursor(ctx, area, x, row.Date || '', labels, bgColor, textColor);
    }
    this.updateChrome(rows);
  };

  SamovarChart.prototype.updateChrome = function (viewRows) {
    const n = this.rows.length;
    const span = this.span();
    if (this.fill) {
      // Без данных полоса показывает пустой участок целиком: иначе обе ручки
      // встают в ноль и накладываются друг на друга.
      const last = Math.max(1, n - 1);
      const from = n > 1 ? span.from / last * 100 : 0;
      const to = n > 1 ? span.to / last * 100 : 100;
      this.fill.style.left = from + '%';
      this.fill.style.width = Math.max(1, to - from) + '%';
      this.gripFrom.style.left = from + '%';
      this.gripTo.style.left = to + '%';
      setGripValue(this.gripFrom, span.from, n, this.rows[span.from]);
      setGripValue(this.gripTo, span.to, n, this.rows[span.to]);
    }
    if (!this.readout) return;
    const idx = this.hoverIndex;
    if (idx == null || !this.rows[idx]) {
      this.readout.textContent = n
        ? ('Точек: ' + n + (span.from === 0 && span.to === n - 1 ? '' : (', показан участок ' + (span.from + 1) + '–' + (span.to + 1))))
        : '';
      return;
    }
    const row = this.rows[idx];
    const parts = [row.Date || ''];
    SERIES.forEach(function (series) {
      if (this.hiddenSeries[series.key]) return;
      const value = row[series.key];
      parts.push(series.label + ': ' + (value === null ? '—' : value));
    }, this);
    this.readout.textContent = parts.join('  ·  ');
  };

  window.SamovarChart = SamovarChart;
})();
