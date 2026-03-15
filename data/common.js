/**
 * @file common.js
 * @brief Общий JavaScript функционал для веб-интерфейса Samovar
 * 
 * Этот файл содержит общие функции, используемые на нескольких HTML страницах:
 * - Управление соединением (ConnectError)
 * - Управление мощностью (setPowerUnit)
 * - Lua кнопки (AddLuaButtons)
 * - Звук и сообщения (playSound, addMessage, showMessages, и т.д.)
 * - История сообщений (getHistory, saveHistory, showHistory, clearHistory)
 * - Работа с вкладками (openTab)
 * - Проверка и расчет программ (check_program, calc_program, calc_time)
 * - Отправка команд (set_program, sendbutton, sendvoltage)
 * - Утилиты (sleep, get_time)
 */

// ==================== CONNECTION STATUS ============================================================
var IsOffline = false; // признак обрыва связи
var OfflineCounter = 0;

/**
 * @brief Обработка ошибок соединения
 * @param {boolean} Type true = ошибка, false = восстановление
 */
function ConnectError(Type) {
  if (Type) {
    if (OfflineCounter < 3) { // считаем 3 обрыва подряд
      OfflineCounter++;
    } else {
      document.getElementById('connection_indicator').innerHTML = `
        <img src="Red_light.gif" style="margin: 0!important; width: 20px">`;
      addMessage('Обрыв связи!', 0);
      setTimeout(() => {
        IsOffline = true;
        OfflineCounter++;
      }, 100);
    }
  } else {
    document.getElementById('connection_indicator').innerHTML = `
      <img src="Green.png" style="margin: 0 !important; width: 20px">`;
    IsOffline = false;
    if (OfflineCounter >= 3) { // связь вернулась, отключаем звук
      playSound(false);
    }
    OfflineCounter = 0;
  }
}

// ==================== POWER UNIT ===================================================================
var pwr_unit = "%pwr_unit%";

/**
 * @brief Установка единиц измерения мощности (Вт/В)
 */
function setPowerUnit() {
  let setPowerLabel;
  let setPowerButton;
  let powerCurrent;
  let powerTarget;
  let powerUnit;
  
  if (pwr_unit === 'P') {
    setPowerLabel = 'Мощность регулятора: ';
    setPowerButton = 'Установить мощность';
    powerCurrent = 'Текущая мощн.: ';
    powerTarget = 'Целевая мощн.: ';
    powerUnit = ' Вт';
    if (document.getElementById('current_power_line')) {
      document.getElementById('current_power_line').style = 'visibility: hidden; margin: 0; padding: 0';
    }
  } else if (pwr_unit === 'V') {
    setPowerLabel = 'Напряжение регулятора: ';
    setPowerButton = 'Установить напряжение';
    powerCurrent = 'Текущее напр.: ';
    powerTarget = 'Целевое напр.: ';
    powerUnit = ' V';
    if (document.getElementById('current_power_line')) {
      document.getElementById('current_power_line').style = 'visibility: visible';
    }
  } else {
    if (document.getElementById('PWR')) {
      document.getElementById('PWR').style = 'visibility: hidden;position: fixed;';
    }
  }
  
  if (document.getElementById('set_power_label')) {
    document.getElementById('set_power_label').innerHTML = setPowerLabel;
  }
  if (document.getElementById('SetVoltage')) {
    document.getElementById('SetVoltage').value = setPowerButton;
  }
  if (document.getElementById('power_current')) {
    document.getElementById('power_current').innerHTML = powerCurrent;
  }
  if (document.getElementById('power_target')) {
    document.getElementById('power_target').innerHTML = powerTarget;
  }
  if (document.getElementById('power_unit_current')) {
    document.getElementById('power_unit_current').innerHTML = powerUnit;
  }
  if (document.getElementById('power_unit_target')) {
    document.getElementById('power_unit_target').innerHTML = powerUnit;
  }
}

// ==================== LUA BUTTONS ==================================================================
/**
 * @brief Добавление кнопок Lua из списка
 */
function AddLuaButtons() {
  let btn_list = '%btn_list%';
  if (btn_list !== '') {
    let btn_arr = btn_list.split(',');
    for (let z = 0; z < btn_arr.length; z++) {
      if (btn_arr[z] !== '') {
        let arr = btn_arr[z].split('|');
        let btn = document.createElement('input');
        btn.type = 'submit';
        btn.name = 'luabtn' + z;
        btn.value = arr[1];
        btn.className = 'button';
        btn.setAttribute('onclick', 'run_lua("' + arr[0] + '");');
        
        let luaBtnLn = document.getElementById('lua_btn_ln');
        if (luaBtnLn) {
          luaBtnLn.appendChild(btn);
        }
        
        let luaBtn = document.getElementById('lua_btn');
        if (luaBtn) {
          luaBtn.style = 'visibility: visible';
        }
      }
    }
  }
}

// ==================== SOUND & MESSAGES QUEUE =======================================================
var sound_is_on = true; // признак включения звука
var IsCalmingPause = false; // признак паузы при отборе
var Messages_Array = []; // текущий массив сообщений
var sound_is_playing = false; // звук сейчас воспроизводится
var is_ALARM = false; // признак тревоги

const sound = new Audio('alarm.mp3');
sound.loop = true;
sound.preload = 'auto';
sound.autoplay = false;

/**
 * @brief Воспроизведение/пауза звука тревоги
 * @param {boolean} play true = играть, false = пауза
 */
function playSound(play) {
  if (!sound_is_playing && play) {
    sound.play();
    sound_is_playing = true;
  } else if (sound_is_playing && !play) {
    sound.pause();
    sound_is_playing = false;
  }
}

// ==================== MESSAGE HISTORY =============================================================
/**
 * @brief Получение истории сообщений из localStorage
 * @returns {Array} Массив сообщений
 */
function getHistory() {
  let history = [];
  let fromStorage = localStorage.getItem('samovarHistory');
  try {
    let parsed = JSON.parse(fromStorage);
    history = parsed ? parsed : [];
  } catch (err) {
    console.log('ERR parsed: ', err);
    history = [];
  }
  return history;
}

/**
 * @brief Сохранение сообщения в историю
 * @param {string} message Сообщение для сохранения
 */
function saveHistory(message) {
  let saved = getHistory();
  saved.push(message);
  localStorage.setItem('samovarHistory', JSON.stringify(saved));
}

let historyShown = false;

/**
 * @brief Показать/скрыть историю сообщений
 */
function showHistory() {
  if (historyShown) {
    if (document.getElementById('historyBox')) {
      document.getElementById('historyBox').style.display = 'none';
    }
    historyShown = false;
  } else {
    let historyArray = getHistory();
    if (document.getElementById('historyList')) {
      document.getElementById('historyList').innerHTML = historyArray;
    }
    if (document.getElementById('historyBox')) {
      document.getElementById('historyBox').style.display = 'block';
      let queue = document.getElementById('historyBox');
      queue.scrollTop = queue.scrollHeight;
    }
    historyShown = true;
  }
}

/**
 * @brief Очистка истории сообщений
 */
function clearHistory() {
  localStorage.setItem('samovarHistory', JSON.stringify([]));
  showHistory();
}

// ==================== MESSAGE QUEUE ==============================================================
/**
 * @brief Добавление сообщения в очередь
 * @param {string} msg Текст сообщения
 * @param {number} lvl Уровень (0=alarm, 1=warning, 2=info)
 */
function addMessage(msg, lvl) {
  if (IsOffline) {
    return; // ничего не делаем чтобы не дублировать сообщения о продолжающемся разрыве связи
  } else {
    let time = new Date().toLocaleTimeString('ru-RU');
    let cssClass = null;
    
    switch (lvl) {
      case 0:
        cssClass = 'message_0';
        is_ALARM = true;
        break;
      case 1:
        cssClass = 'message_1';
        break;
      case 2:
        cssClass = 'message_2';
        break;
      default:
        cssClass = 'message_0';
        is_ALARM = true;
        break;
    }
    
    let lastMsg = `
      <div align="left" class=${cssClass} onclick=removeLastMessage() style="cursor: pointer;">
        ${time}  ${msg}
      </div>`;

    let msg4history = `<div align="left" class=${cssClass} style="margin-top: 0"> <span style="text-decoration: underline">${time}</span>  ${msg}</div>`;
    saveHistory(msg4history);

    Messages_Array.push(lastMsg); // добавляем сообщение в конец очереди
    
    if (Messages_Array.length > 1) {
      // убираем у предпоследнего сообщения обработчик удаления, активно всегда последнее
      let previousMsg = Messages_Array[Messages_Array.length - 2];
      let changed = previousMsg.replace(
        'onclick=removeLastMessage() style="cursor: pointer"',
        ''
      );
      Messages_Array[Messages_Array.length - 2] = changed;
    }
    
    showMessages();
  }
}

/**
 * @brief Удаление последнего сообщения
 */
function removeLastMessage() {
  Messages_Array.pop();
  
  if (Messages_Array.length > 0) {
    let lastMsg = Messages_Array[Messages_Array.length - 1];
    let changed = lastMsg.replace(
      '<div align="left"',
      '<div align="left" onclick=removeLastMessage() style="cursor: pointer"'
    );
    Messages_Array[Messages_Array.length - 1] = changed;
  } else {
    is_ALARM = false;
  }
  
  showMessages();
}

/**
 * @brief Отображение очереди сообщений
 */
function showMessages() {
  // показываем обновлённый список сообщений
  if (Messages_Array.length > 0) {
    let alarm_is_there = []; // массив false/true для признаков тревоги
    
    if (document.getElementById('messages')) {
      document.getElementById('messages').innerHTML = '';
      
      Messages_Array.forEach(message => {
        if (document.getElementById('messages')) {
          document.getElementById('messages').innerHTML += message;
        }
        alarm_is_there.push(message.includes('class=message_0'));
      });
    }
    
    if (document.getElementById('messagesBox')) {
      document.getElementById('messagesBox').style.display = 'block';
      let queue = document.getElementById('messagesBox');
      queue.scrollTop = queue.scrollHeight;
    }
    
    function positive(item) {
      return item === true;
    }
    
    is_ALARM = alarm_is_there.some(positive); // содержит ли хоть одно сообщение признак тревоги
    
    if (sound_is_on && is_ALARM) {
      // играем звук тревоги, если включён
      playSound(true);
    } else {
      playSound(false);
    }
  } else {
    // убираем блок, если очередь пуста
    if (document.getElementById('messagesBox')) {
      document.getElementById('messagesBox').style.display = 'none';
    }
    playSound(false);
  }
}

/**
 * @brief Очистка очереди сообщений
 */
function clearMessages() {
  Messages_Array = [];
  showMessages();
}

// ==================== SPOILER HEADERS ==============================================================
var _lnIdx = 0;

/**
 * @brief Обработчик клика по заголовку спойлера
 */
function headerClick() {
  if (this.nextElementSibling) {
    this.nextElementSibling.classList.toggle("spoiler-body");
  }
  let s = this.parentNode.getElementsByClassName("spoiler-sign");
  if (s[0].innerHTML == "[+]") {
    s[0].innerHTML = "[-]";
  } else {
    s[0].innerHTML = "[+]";
  }
}

// ==================== TABS =========================================================================
/**
 * @brief Открытие вкладки
 * @param {Event} evt Событие клика
 * @param {string} tabName Имя вкладки
 */
function openTab(evt, tabName) {
  let i, tabcontent, tablinks;
  
  tabcontent = document.getElementsByClassName("tabcontent");
  for (i = 0; i < tabcontent.length; i++) {
    tabcontent[i].style.display = "none";
  }
  
  tablinks = document.getElementsByClassName("tablinks");
  for (i = 0; i < tablinks.length; i++) {
    tablinks[i].className = tablinks[i].className.replace(" active", "");
  }
  
  let tab = document.getElementById(tabName);
  if (tab) {
    tab.style.display = "block";
  }
  
  if (evt && evt.currentTarget) {
    evt.currentTarget.className += " active";
  }
  
  return 0;
}

// ==================== PROGRAM VALIDATION =========================================================
/**
 * @brief Проверка корректности программы
 * @param {string} str Текст программы
 * @returns {boolean} true если программа корректна
 */
function check_program(str) {
  let arrayOfStrings = str.split("\n");
  let prevcnt = 0;
  let ret = true;
  let cnt;
  
  for (let i = 0; i < arrayOfStrings.length; i++) {
    let arrayOfDelim = arrayOfStrings[i].split(";");
    cnt = arrayOfDelim.length;
    
    if (cnt == 1 && arrayOfDelim[0] != "" && i == arrayOfStrings.length - 1) {
      ret = false;
    } else if (prevcnt > 0 && cnt > 1) {
      if (prevcnt != cnt) ret = false;
    }
    prevcnt = cnt;
  }
  
  return ret;
}

/**
 * @brief Расчет времени программы
 */
function calc_program() {
  if (!check_program(document.getElementById('WProgram').value)) {
    alert("Program error!");
    return;
  }
  
  let t = document.getElementsByClassName("prgline");
  let k, s;
  s = "";
  
  for (let i = 0; i < t.length; i++) {
    if (t[i].childNodes[2]) {
      if (t[i].childNodes[2].value.indexOf(".") > 0) {
        t[i].childNodes[2].value = t[i].childNodes[2].value.substring(0, t[i].childNodes[2].value.indexOf("."));
      }
      if (t[i].childNodes[2].value.indexOf(",") > 0) {
        t[i].childNodes[2].value = t[i].childNodes[2].value.substring(0, t[i].childNodes[2].value.indexOf(","));
      }
    }
    
    if (t[i].childNodes[3]) {
      t[i].childNodes[3].value = t[i].childNodes[3].value.replace(",", ".");
    }
    
    if (t[i].childNodes[6]) {
      t[i].childNodes[6].value = t[i].childNodes[6].value.replace(",", ".");
    }

    k = t[i].childNodes;
    for (let j = 1; j < 7; j++) {
      if (k[j] && k[j].value) {
        s = s + k[j].value + ";";
      }
    }
    s = s.slice(0, -1);
    s = s + "\n";
  }

  if (document.getElementById('WProgram')) {
    document.getElementById('WProgram').value = s;
  }
  
  if (typeof set_num === 'function') {
    set_num();
  }
  
  calc_time();
}

var totalTime = 0;

/**
 * @brief Форматирование времени
 * @param {number} time Время в часах
 * @returns {string} Форматированное время
 */
function get_time(time) {
  let hours = Math.floor(time);
  let minutes = Math.floor((time - hours) * 60);
  return hours + "ч " + minutes + "м";
}

/**
 * @brief Расчет времени выполнения программы
 */
function calc_time() {
  totalTime = 0;
  let stringTime = 0;
  let program = document.getElementsByClassName("prgline");
  
  for (let i = 0; i < program.length; i++) {
    let line = program[i];
    
    if (line.childNodes[1] && line.childNodes[1].value === 'P') {
      if (line.childNodes[2]) {
        stringTime = line.childNodes[2].value / 3600;
      }
    } else {
      let volume = 0;
      let speed = 0;
      
      if (line.childNodes[2]) {
        volume = line.childNodes[2].value / 1000;
      }
      if (line.childNodes[3]) {
        speed = line.childNodes[3].value;
      }
      
      stringTime = speed > 0 ? volume / speed : 0;
    }
    
    let time = line.childNodes[7];
    if (time) {
      time.textContent = get_time(stringTime);
    }
    
    totalTime = totalTime + stringTime;
  }
  
  let totalTimeEl = document.getElementById('totalTime');
  if (totalTimeEl) {
    totalTimeEl.textContent = get_time(totalTime);
  }
}

/**
 * @brief Установка программы на сервер
 * @returns {number} 0
 */
function set_program() {
  calc_program();
  
  let wProgramEl = document.getElementById("WProgram");
  if (wProgramEl) {
    wProgramEl.value = wProgramEl.value.replace(",", ".");
  }
  
  let server = '/program';
  let request = new XMLHttpRequest();
  
  request.onreadystatechange = function() {
    if (this.readyState == 4 && this.status == 200) {
      let myObj = this.responseText;
      if (myObj != "OK") {
        if (wProgramEl) {
          wProgramEl.value = myObj;
        }
        alert("Программа установлена");
      }
    }
  };
  
  request.open('POST', server, false);
  
  let formData = new FormData(document.forms.mainform);
  request.send(formData);
  
  if (request.status != 200) {
    alert("set_program ERROR! " + request.status + ': ' + request.statusText);
  }
  
  return 0;
}

// ==================== UTILITIES ==================================================================
/**
 * @brief Синхронная задержка (blocking sleep)
 * @param {number} milliseconds Задержка в мс
 */
function sleep(milliseconds) {
  let start = new Date().getTime();
  for (let i = 0; i < 1e7; i++) {
    if ((new Date().getTime() - start) > milliseconds) {
      break;
    }
  }
}

/**
 * @brief Отправка команды на сервер
 * @param {string} command Команда
 * @returns {number} 0
 */
function sendbutton(command) {
  let server = '/command?' + command;
  let request = new XMLHttpRequest();
  
  request.open('GET', server, false);
  request.send();
  
  if (request.status != 200) {
    alert("sendbutton ERROR! " + request.status + ': ' + request.statusText);
  }
  
  sleep(1000);
  return 0;
}

/**
 * @brief Отправка напряжения/мощности на сервер
 * @returns {number} 0 или 1 при ошибке
 */
function sendvoltage() {
  let voltageEl = document.getElementById('Voltage');
  if (!voltageEl) {
    return 1;
  }
  
  voltageEl.value = voltageEl.value.replace(",", ".");
  let num = voltageEl.value;
  
  if (!num.match(/^\d+\.\d+$/) && !num.match(/^-{0,1}\d+$/)) {
    alert("Введите значение!");
    return 0;
  }
  
  let command = 'voltage=' + num;
  sendbutton(command);
  return 0;
}

/**
 * @brief Загрузка документа (AJAX)
 */
function loadDoc() {
  // Базовая функция для AJAX запросов
  // Переопределяется в конкретных страницах
}

/**
 * @brief Отправка команды I2C насоса
 */
function sendI2CPump() {
  // Реализация зависит от конкретной страницы
}

/**
 * @brief Остановка I2C насоса
 */
function stopI2CPump() {
  // Реализация зависит от конкретной страницы
}

/**
 * @brief Запуск Lua скрипта
 * @param {number} num Номер скрипта
 */
function run_lua(num) {
  let command = 'lua=' + num;
  sendbutton(command);
}

/**
 * @brief Запуск строки Lua скрипта
 */
function run_strlua() {
  // Реализация зависит от конкретной страницы
}

// ==================== INITIALIZATION =============================================================
/**
 * @brief Инициализация обработчиков событий при загрузке страницы
 */
document.addEventListener('DOMContentLoaded', function() {
  // Инициализация спойлеров
  let headers = document.querySelectorAll("[data-name='spoiler-title']");
  for (let i = 0; i < headers.length; i++) {
    headers[i].addEventListener('click', headerClick);
  }
  
  // Инициализация power unit
  setPowerUnit();
  
  // Инициализация Lua кнопок
  AddLuaButtons();
});
