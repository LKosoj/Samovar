// ===================================================================================================
// ==================== CONNECTION STATUS ============================================================
// ===================================================================================================
var IsOffline = false; //признак обрыва связи
function ConnectError(Type) {
  if (Type) {
    document.getElementById('GreenT').style =
      'visibility: hidden;position: fixed;';
    document.getElementById('RedT').style = '';
    addMessage('Обрыв связи!', 0);
    setTimeout(() => {
      IsOffline = true;
    }, 100);
  } else {
    document.getElementById('GreenT').style = '';
    document.getElementById('RedT').style =
      'visibility: hidden;position: fixed;';
    IsOffline = false;
  }
}

// ===================================================================================================
// ==================== POWER UNIT ===================================================================
// ===================================================================================================
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
    document.getElementById('current_power_line').style = 'visibility: hidden';
    document.getElementById('PWR').style = '';
  } else if (pwr_unit === 'V') {
    setPowerLabel = 'Напряжение регулятора: ';
    setPowerButton = 'Установить напряжение';
    powerCurrent = 'Текущее напр.: ';
    powerTarget = 'Целевое напр.: ';
    powerUnit = ' V';
    document.getElementById('current_power_line').style = 'visibility: visible';
    document.getElementById('PWR').style = '';
  } else {
    document.getElementById('PWR').style =
      'visibility: hidden;position: fixed;';
  }
  document.getElementById('set_power_label').innerHTML = setPowerLabel;
  document.getElementById('SetVoltage').value = setPowerButton;
  document.getElementById('power_current').innerHTML = powerCurrent;
  document.getElementById('power_target').innerHTML = powerTarget;
  document.getElementById('power_unit_current').innerHTML = powerUnit;
  document.getElementById('power_unit_target').innerHTML = powerUnit;
}

// ===================================================================================================
// ==================== LUA BUTTONS ==================================================================
// ===================================================================================================
function AddLuaButtons() {
  let btn_list = '%btn_list%';
  if (btn_list !== '') {
    let btn_arr = btn_list.split(',');
    for (z = 0; z < btn_arr.length; z++) {
      if (btn_arr[z] !== '') {
        let arr = btn_arr[z].split('|');
        let btn = document.createElement('input');
        btn.type = 'submit';
        btn.name = 'luabtn' + z;
        btn.value = arr[1];
        btn.className = 'button';
        btn.setAttribute('onclick', 'run_lua("' + arr[0] + '");');
        document.getElementById('lua_btn_ln').appendChild(btn);
        document.getElementById('lua_btn').style = 'visibility: visible';
      }
    }
  }
}

// ===================================================================================================
// ==================== SOUND & MESSAGES QUEUE =======================================================
// ===================================================================================================
var sound_is_on = true; //признак включения звукв (будет изменён на настройку пользователя при ajax)
var IsCalmingPause = false; //признак паузы при отборе (чтобы не повторять вывод сообщения каждые 2 секунды)

var Messages_Array = []; //текущий массив сообщений
var sound_is_playing = false; //звук сейчас восспроизводится
var is_ALARM = false; //признак тревоги

const sound = new Audio('alarm.mp3');
sound.loop = true;
sound.preload = 'auto';
sound.autoplay = false;

function playSound(play) {
  if (!sound_is_playing && play) {
    sound.play();
    sound_is_playing = true;
  } else if (sound_is_playing && !play) {
    sound.pause();
    sound_is_playing = false;
  }
}

function addMessage(msg, lvl) {
  if (IsOffline) {
    return; //ничего не делаем чтобы не дублировать сообщения о продолжающемся разрыве связи
  } else {
    let time = new Date().toLocaleTimeString('ru-RU');
    let style = null;
    switch (lvl) {
      case 0:
        style = 'message_0';
        is_ALARM = true;
        break;
      case 1:
        style = 'message_1';
        break;
      case 2:
        style = 'message_2';
        break;
      default:
        style = 'message_0';
        is_ALARM = true;
        break;
    }
    let lastMsg = `
            <div align="left" class=${style} onclick=removeLastMessage() style="cursor: pointer">
              ${time}  ${msg}
            </div>`;
    Messages_Array.push(lastMsg); //добавляем сообщение в конец очереди
    if (Messages_Array.length > 1) {
      //убираем у предпоследнего сообщения обработчик удаления, активно всегда последнее
      previousMsg = Messages_Array[Messages_Array.length - 2];
      let changed = previousMsg.replace(
        'onclick=removeLastMessage() style="cursor: pointer"',
        ''
      );
      Messages_Array[Messages_Array.length - 2] = changed;
    }
    showMessages();
  }
}

function removeLastMessage() {
  //удаляям последнее сообщение
  Messages_Array.pop();
  if (Messages_Array.length > 0) {
    lastMsg = Messages_Array[Messages_Array.length - 1];
    let changed = lastMsg.replace(
      '<div align="left"',
      '<div align="left" onclick=removeLastMessage() style="cursor: pointer"'
    );
    Messages_Array[Messages_Array.length - 1] = changed;
  } else {
    is_ALARM = false;
    IsCalmingPause = false;
  }
  showMessages();
}

function showMessages() {
  //показываем обновлённый список сообщений
  if (Messages_Array.length > 0) {
    let alarm_is_there = []; //массив false/true для признаков тревоги
    document.getElementById('messages').innerHTML = '';
    Messages_Array.forEach(message => {
      document.getElementById('messages').innerHTML += message;
      alarm_is_there.push(message.includes('class=message_0'));
    });
    document.getElementById('messagesBox').style.display = 'block';
    let queue = document.getElementById('messagesBox');
    queue.scrollTop = queue.scrollHeight;
    function positive(item) {
      return item === true;
    }
    is_ALARM = alarm_is_there.some(positive); //содержит ли хоть одно сообщение признак тревоги
    if (sound_is_on & is_ALARM) {
      //играем звук тревоги, если включён
      playSound(true);
    } else {
      playSound(false);
    }
  } else {
    //убираем блок, если очередь пуста
    document.getElementById('messagesBox').style.display = 'none';
    playSound(false);
  }
}

function clearMessages() {
  Messages_Array = [];
  showMessages();
}

// ============= проверка сообщей кнопками =======================

function add_message_0() {
  //TODO
  let text =
    'Alert message ' +
    Math.floor(Math.random() * 100) +
    ' alert message alert message alert message alert message alert message ' +
    Math.floor(Math.random() * 100);
  addMessage(text, 0);
}
function add_message_1() {
  //TODO
  let text =
    'Warning message ' +
    Math.floor(Math.random() * 100) +
    ' warning message warning message warning message warning message warning message ' +
    Math.floor(Math.random() * 100);
  addMessage(text, 1);
}
function add_message_2() {
  //TODO
  let text =
    'Info message ' +
    Math.floor(Math.random() * 100) +
    ' just info message just info message just info message just info message just info message ' +
    Math.floor(Math.random() * 100);
  addMessage(text, 2);
}
