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
  const MAX_RENDER_POINTS = 600;

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
      item.appendChild(document.createTextNode(series.label));
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

  function drawGrid(ctx, area, bounds, textColor, gridColor) {
    ctx.strokeStyle = gridColor;
    ctx.fillStyle = textColor;
    ctx.lineWidth = 1;
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= 4; i++) {
      const y = area.top + area.height * i / 4;
      ctx.beginPath();
      ctx.moveTo(area.left, y);
      ctx.lineTo(area.left + area.width, y);
      ctx.stroke();
      const value = bounds.max - (bounds.max - bounds.min) * i / 4;
      ctx.fillText(value.toFixed(1), area.left - 8, y);
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
    this.autoRefresh = true;
    this.lastDate = '';
    this.options = options || {};
    this.hiddenSeries = this.options.hidden || {};
    const elements = createCanvas(this.parent, this.hiddenSeries);
    this.canvas = elements.canvas;
    this.status = elements.status;
    window.addEventListener('resize', this.draw.bind(this));
  }

  SamovarChart.prototype.setStatus = function (text, isError) {
    this.status.textContent = text || '';
    this.status.className = isError ? 'chart-status chart-status-error' : 'chart-status';
  };

  SamovarChart.prototype.setData = function (rows) {
    this.rows = rows || [];
    this.lastDate = this.rows.length ? this.rows[this.rows.length - 1].Date : '';
    this.draw();
  };

  SamovarChart.prototype.loadCsv = async function (url) {
    this.setStatus('Загрузка графика...', false);
    const resp = await fetch(url, { cache: 'no-store' });
    if (!resp.ok) {
      this.setStatus('Ошибка загрузки графика: HTTP ' + resp.status, true);
      return false;
    }
    const text = await resp.text();
    this.setData(parseCsv(text));
    this.setStatus(this.rows.length ? 'Загружено точек: ' + this.rows.length : 'Нет данных графика.', false);
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
    const area = { left: 54, top: 18, width: width - 74, height: height - 58 };
    const rows = decimate(this.rows);
    const visibleSeries = SERIES.filter(function (series) { return !this.hiddenSeries[series.key]; }, this);
    const bounds = valueBounds(rows, visibleSeries.map(function (series) { return series.key; }));
    if (!bounds) {
      ctx.fillStyle = textColor;
      ctx.font = '16px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Нет данных для графика', width / 2, height / 2);
      return;
    }
    drawGrid(ctx, area, bounds, textColor, gridColor);
    visibleSeries.forEach(function (series) {
      drawSeries(ctx, rows, area, bounds, series);
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
