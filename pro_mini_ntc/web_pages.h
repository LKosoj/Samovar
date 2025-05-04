#pragma once
#include <Arduino.h>
 
// Главная страница
const char MAIN_PAGE[] PROGMEM = R"=====(
<!doctype html>
<html>
<head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Измеритель</title>
<style>
body{font-family:Arial,sans-serif;background:#121212;color:#eee;margin:0;padding:10px}
.c{max-width:800px;margin:0 auto}h1,h2{text-align:center}
.d{background:#1e1e1e;border-radius:10px;padding:15px;margin:10px 0}
.g{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.v{font-size:1.2em;color:#4CAF50}.a{color:#ff5555}.n{margin:20px 0}
.b{background:#4CAF50;border:0;padding:8px 15px;border-radius:5px;cursor:pointer;min-width:120px}
.no-data{color:#ff5555}
@media (max-width:600px){.c{max-width:100%;padding:0 10px}}
</style>
<script>
let lastUpdateTime = 0;
function r(){if(confirm("Перезагрузить?"))fetch('/restart',{method:'POST'})}
function updateDataStatus() {
const now = Date.now();
const elements = document.querySelectorAll('.v');
elements.forEach(el => {
if (now - lastUpdateTime > 10000) {
el.innerText = "???";
el.classList.add('no-data');
} else {
el.classList.remove('no-data');
}
});
}
function u(){
fetch('/get_data')
.then(r=>{
if(!r.ok) throw new Error('Network error');
return r.json();
})
.then(d=>{
lastUpdateTime = Date.now();
for(let i=0;i<8;i++){
let e=document.getElementById('t'+i);
if(e) e.innerText=d.temps[i]!==null?d.temps[i].toFixed(2)+" °C":"---";
}
for(let i=0;i<4;i++){
let e=document.getElementById('p'+i);
if(e) e.innerText=d['p'+i]!==null?d['p'+i].toFixed(2)+" мм.р.ст":"---";
}
document.getElementById('a').innerText=d.alc!=null?d.alc.toFixed(1)+" %":"---";
document.getElementById('s').innerText=d.spk_on?"ON(T>"+d.t_target+")":"OFF";
document.getElementById('s').className=d.spk_on?"a":"";
document.getElementById('zs').innerText = d.spk_sensor;
document.getElementById('r').innerText=d.rssi+" dBm";
})
.catch(e=>{
console.error('Error fetching data:', e);
});
}
setInterval(updateDataStatus, 1000);
setInterval(u, 2000);
u();
</script>
</head>
<body>
<div class=c>
<h1>Измеритель</h1>
<div class=d>
<h2>Температуры</h2>
<div class=g>
<p>T пара: <span id=t1 class=v>---</span></p>
<p>T царги: <span id=t2 class=v>---</span></p>
<p>T куба: <span id=t3 class=v>---</span></p>
<p>T воды: <span id=t4 class=v>---</span></p>
<p>T тса: <span id=t5 class=v>---</span></p>
<p>T спирта: <span id=t6 class=v>---</span></p>
</div></div>
<div class=d>
<h2>Давления</h2>
<div class=g>
<p>Pt: <span id=p0 class=v>---</span></p>
<p>P1: <span id=p1 class=v>---</span></p>
<p>P2: <span id=p2 class=v>---</span></p>
<p>P3: <span id=p3 class=v>---</span></p>
</div></div>
<div class=d>
<p>Попугай: <span id=a class=v>---</span></p>
<p>Зуммер (<span id=zs>---</span>): <span id=s>---</span></p>
</div>
<div class=n>
<a href=/setup_wifi><button class=b>Wi-Fi</button></a>
<a href=/setup_mqtt><button class=b>MQTT</button></a>
<a href=/setup_ntc><button class=b>Термисторы</button></a>
<a href=/pressure_setup><button class=b>Д.давления</button></a>
<a href=/setup_alc><button class=b>Попугай</button></a>
<a href=/setup_spk><button class=b>Зуммер</button></a><br><br>
<button class=b onclick=r()>Перезагрузка</button>
</div>
<p>RSSI:<span id=r class=v>---</span></p>
</div>
</body></html>
)=====";

// Страница настройки Wi-Fi
const char WIFI_PAGE[] PROGMEM = R"=====(
<!doctype html>
<html>
<head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Wi-Fi</title>
<style>
body{font-family:Arial,sans-serif;background:#121212;color:#eee;margin:0;padding:10px}
.c{max-width:800px;margin:0 auto}
h1,h2{text-align:center;color:#4CAF50}
.d{background:#1e1e1e;border-radius:10px;padding:15px;margin:10px 0;box-shadow:0 2px 5px rgba(0,0,0,0.3)}
.f{margin:15px 0}
label{display:block;margin-bottom:5px;color:#bbb}
input,select{width:100%;padding:10px;box-sizing:border-box;background:#333;color:#eee;border:1px solid #444;border-radius:5px;font-size:16px}
.b{background:#4CAF50;border:0;padding:10px 20px;border-radius:5px;cursor:pointer;color:#fff;font-weight:bold;margin:5px;transition:background 0.3s}
.b:hover{background:#45a049}
.n{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0;justify-content:center}
@media (max-width:600px){.c{padding:0 10px}}
</style>
</head>
<body>
<div class=c>
<h1>Wi-Fi</h1>
<div class=d>
<form action=/save_wifi method=POST>
<div class=f>
<label>SSID:</label>
<input type=text name=ssid value="%s%">
</div>
<div class=f>
<label>Пароль:</label>
<input type=password name=pass value="%p%">
</div>
<button type=submit class=b>Сохранить</button>
</form>
</div>
<div class=n>
<a href=/><button class=b>Назад</button></a>
</div>
</div>
</body>
</html>
)=====";

// Страница настройки MQTT
const char MQTT_PAGE[] PROGMEM = R"=====(
<!doctype html>
<html>
<head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>MQTT</title>
<style>
body{font-family:Arial,sans-serif;background:#121212;color:#eee;margin:0;padding:10px}
.c{max-width:800px;margin:0 auto}
h1,h2{text-align:center;color:#4CAF50}
.d{background:#1e1e1e;border-radius:10px;padding:15px;margin:10px 0;box-shadow:0 2px 5px rgba(0,0,0,0.3)}
.f{margin:15px 0}
label{display:block;margin-bottom:5px;color:#bbb}
input,select{width:100%;padding:10px;box-sizing:border-box;background:#333;color:#eee;border:1px solid #444;border-radius:5px;font-size:16px}
.b{background:#4CAF50;border:0;padding:10px 20px;border-radius:5px;cursor:pointer;color:#fff;font-weight:bold;margin:5px}
.b:hover{background:#45a049}
.n{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0;justify-content:center}
.l{margin-top:20px}
@media (max-width:600px){.c{padding:0 10px}}
</style>
</head>
<body>
<div class=c>
<h1>MQTT</h1>
<div class=d>
<form action=/save_mqtt method=POST>
<div class=f>
<label>Сервер:</label>
<input type=text name=server value="%s%">
</div>
<div class=f>
<label>Порт:</label>
<input type=number name=port value="%o%">
</div>
<div class=f>
<label>Пользователь:</label>
<input type=text name=user value="%u%">
</div>
<div class=f>
<label>Пароль:</label>
<input type=password name=pass value="%p%">
<div class="form-group">
<label for="attempts">Количество попыток подключения (0-10):</label>
<input type="number" class="form-control" id="attempts" name="attempts" min="0" max="10" value="%a%">
</div>
</div>
<button type=submit class=b>Сохранить</button>
</form>
</div>
<div class=l>
<h3>Подключение:</h3>
<p><b>Статус:</b> %st%</p>
<p><b>Лог:</b><br>%lg%</p>
<p><b>Ошибка:</b> %er%</p>
</div>
<div class=n>
<a href=/><button class=b>Назад</button></a>
</div>
</div>
</body>
</html>
)=====";

// Страница настройки термисторов
const char NTC_PAGE[] PROGMEM = R"=====(
<!doctype html>
<html>
<head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Термисторы</title>
<style>
body{font-family:Arial,sans-serif;background:#121212;color:#eee;margin:0;padding:10px}
.c{max-width:800px;margin:0 auto}
h1,h2{text-align:center;color:#4CAF50}
.d{background:#1e1e1e;border-radius:10px;padding:15px;margin:10px 0;box-shadow:0 2px 5px rgba(0,0,0,0.3)}
.f{margin:15px 0}
label{display:block;margin-bottom:5px;color:#bbb}
input,textarea{width:100%;padding:10px;box-sizing:border-box;background:#333;color:#eee;border:1px solid #444;border-radius:5px;font-size:16px}
.b{background:#4CAF50;border:none;padding:10px 20px;border-radius:5px;cursor:pointer;color:#fff;font-weight:bold;margin:5px}
.b:hover{background:#45a049}
.n{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0;justify-content:center}
.t{background:#1e1e1e;padding:15px;border-radius:5px;margin:15px 0}
textarea{min-height:150px;font-family:monospace}
@media (max-width:600px){.c{padding:0 10px}}
</style>
<script>
function calculateB(){
 var R25=parseFloat(d('R25').value),
 R100=parseFloat(d('R100').value),
 T25=parseFloat(d('T25').value)+273.15,
 T100=parseFloat(d('T100').value)+273.15;
 div1=(1/T25-1/T100);
 log1=Math.log(R25*1000)-Math.log(R100*1000);
 d('B25').value=(log1/div1).toFixed(0);
}
function validateText(){
 let t=d('adcText').value.split(',').filter(x=>x.trim()!='');
 if(t.length!=151||t.some(x=>isNaN(x))){alert('Неверный формат');return false;}
 return true;
}
function c(){fetch('/calculateCurve',{method:'POST',body:new FormData(d('ntcForm'))}).then(r=>r.text()).then(t=>d('adcText').value=t)}
function a(){
    if(!validateText()) return;
    let formData = new FormData();
    formData.append('plain', d('adcText').value);
    fetch('/applyNTCText', {
        method: 'POST',
        body: formData
    }).then(r=>alert('Применено'))
}
function s(){if(!validateText())return;fetch('/saveNTCToEEPROM',{method:'POST'}).then(r=>alert('Сохранено'))}
function x(){let a=document.createElement('a');a.href='data:text/plain,'+d('adcText').value;a.download='ntc.txt';a.click()}
function i(){let f=document.createElement('input');f.type='file';f.onchange=e=>{let r=new FileReader();r.onload=e=>d('adcText').value=e.target.result;r.readAsText(e.target.files[0])};f.click()}
function updateTemps(){
 fetch('/getTemps').then(r=>r.text()).then(t=>{
 document.getElementById('temps').innerHTML=t;
 setTimeout(updateTemps, 1000);
 });
 }
 function d(e){return document.getElementById(e)}
 document.addEventListener('DOMContentLoaded', function() {
 updateTemps();
 if(d('adcText').value.trim() == '') {
    fetch('/getCurrentCurve').then(r=>r.text()).then(t=>d('adcText').value=t);
 }
 });
</script>
</head>
<body>
<div class=c>
<h1>Термисторы</h1>
<div class=d>
<form id=ntcForm>
<h2>Параметры</h2>
<div class=f>
<label>R25 (kΩ):</label>
<input type=number step=0.01 id=R25 name=R25 value="%r25%">
</div>
<div class=f>
<label>R100 (kΩ):</label>
<input type=number step=0.001 id=R100 name=R100 value="%r100%">
</div>
<div class=f>
<label>T25 (°C):</label>
<input type=number step=0.1 id=T25 name=T25 value="%t25%">
</div>
<div class=f>
<label>T100 (°C):</label>
<input type=number step=0.1 id=T100 name=T100 value="%t100%">
</div>
<div class=f>
<label>B25/100:</label>
<input type=number step=0.1 id=B25 name=B25 value="%b25%">
<button type=button onclick=calculateB() class=b>Вычислить B25</button>
</div>
<h2>Схема</h2>
<div class=f>
<label>U33 (V):</label>
<input type=number step=0.01 id=U33 name=U33 value="%u33%">
</div>
<div class=f>
<label>Uref (V):</label>
<input type=number step=0.001 id=Uref name=Uref value="%uref%">
</div>
<div class=f>
<label>R62 (kΩ):</label>
<input type=number step=0.001 id=R62 name=R62 value="%r62%">
</div>
<div class=f>
<label>R10 (kΩ):</label>
<input type=number step=0.001 id=R10 name=R10 value="%r10%">
</div>
<button type=button onclick=c() class=b>Рассчитать</button>
</form>
</div>
<div class=d>
<h2>Характеристика</h2>
<textarea id=adcText>%adc%</textarea>
<div class=n>
<button onclick=a() class=b>Применить</button>
<button onclick=s() class=b>Сохранить</button>
<button onclick=x() class=b>Экспорт</button>
<button onclick=i() class=b>Импорт</button>
</div>
</div>
<div class=d>
<h2>Температуры</h2>
<div id=temps class=t>Загрузка...</div>
</div>
<div class=n>
<a href=/><button class=b>Назад</button></a>
</div>
</div>
</body>
</html>
)=====";

// Страница настройки давления
const char PRESSURE_PAGE[] PROGMEM = R"=====(
<!DOCTYPE html>
<html>
<head>
<meta charset=UTF-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Настройка давления</title>
<style>
body{font-family:Arial,sans-serif;background:#121212;color:#eee;margin:0;padding:8px}
.c{max-width:600px;margin:0 auto}h1,h2{text-align:center;color:#4CAF50;font-size:1.3em}
.fg{margin:8px 0}label{display:block;margin-bottom:3px;color:#bbb;font-size:0.8em}
input,select,textarea{width:100%;padding:6px;box-sizing:border-box;background:#333;color:#eee;border:1px solid #444;border-radius:3px;font-size:0.8em}
button{background:#4CAF50;border:none;padding:6px 12px;border-radius:3px;cursor:pointer;color:white;font-weight:bold;margin:3px;font-size:0.8em}
button:hover{background:#45a049}.n{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0;justify-content:center}
.s{background:#1e1e1e;border-radius:6px;margin-bottom:10px;padding:8px}
.v{background:#252525;border-radius:3px;margin:6px 0;padding:5px;font-size:0.8em}
</style>
<script>
function u(){fetch('/getPressureValues').then(r=>r.json()).then(d=>{
 for(let i=1;i<=3;i++){
if(document.getElementById('s'+i).checked){
 document.getElementById('sv'+i).innerText=d['sensor'+i].toFixed(2)+' мм.рт.ст.';
 document.getElementById('st'+i).innerText=d['temp'+i].toFixed(1)+' °C'
}
 }
 setTimeout(u,1e3)
})}
function s(){
 let f=new FormData();
 for(let i=1;i<=3;i++) f.append('sensor'+i,document.getElementById('s'+i).checked?'1':'0');
 f.append('k1',document.getElementById('k1').value);
 f.append('b1',document.getElementById('b1').value);
 f.append('a',document.getElementById('a').value);
 f.append('p',document.getElementById('p').value);
 f.append('h',document.getElementById('h').value);
 f.append('k3',document.getElementById('k3').value);
 f.append('b3',document.getElementById('b3').value);
 fetch('/savePressureSettings',{method:'POST',body:f}).then(r=>alert('Сохранено!'))
}
function a(){
 let f=new FormData();
 for(let i=1;i<=3;i++) f.append('sensor'+i,document.getElementById('s'+i).checked?'1':'0');
 f.append('k1',document.getElementById('k1').value);
 f.append('b1',document.getElementById('b1').value);
 f.append('a',document.getElementById('a').value);
 f.append('p',document.getElementById('p').value);
 f.append('h',document.getElementById('h').value);
 f.append('k3',document.getElementById('k3').value);
 f.append('b3',document.getElementById('b3').value);
 fetch('/applyPressureSettings',{method:'POST',body:f})
}
function z(n){fetch('/zeroPressureSensor?sensor='+n).then(r=>alert('Датчик '+n+' обнулен!'))}
window.onload=function(){
 u();
 for(let i=1;i<=3;i++){
document.getElementById('s'+i).addEventListener('change',function(){
 document.getElementById('ss'+i).style.display=this.checked?'block':'none'
});
document.getElementById('ss'+i).style.display=document.getElementById('s'+i).checked?'block':'none'
 }
}
</script>
</head>
<body>
<div class=c>
<h1>Настройка давления</h1>
<div class=s>
 <div class=fg><input type=checkbox id=s1%S1%><label for=s1>XGZP6897D (I2C)</label></div>
 <div id=ss1%D1%>
<div class=fg><label>Коэф.термокомп.(Ktk):</label><input type=number step=0.01 id=k1 value=%KT1%></div>
<div class=fg><label>Базовая t°C:</label><input type=number step=0.1 id=b1 value=%BT1%></div>
<div class=v>Давление: <span id=sv1>--</span></div>
<div class=v>Температура: <span id=st1>--</span></div>
<button onclick=z(1)>Обнулить</button>
 </div>
</div>
<div class=s>
 <div class=fg><input type=checkbox id=s2%S2%><label for=s2>MPX5010DP (ADC)</label></div>
 <div class=fg><label>Базовое АЦП:</label><input type=number id=a value=%BADS%></div>
 <div class=fg><label>Квант давления:</label><input type=number step=0.0001 id=p value=%PQ%></div>
 <div id=ss2%D2%>
<div class=v>Давление: <span id=sv2>--</span></div>
<div class=v>Температура: <span id=st2>--</span></div>
<button onclick=z(2)>Обнулить</button>
 </div>
</div>
<div class=s>
 <div class=fg><input type=checkbox id=s3%S3%><label for=s3>HX710B (ADC)</label></div>
 <div class=fg><label>Множитель HX710B:</label><input type=number step=0.01 id=h value=%HXM%></div>
 <div class=fg><label>Коэф.термокомп.(Ktk):</label><input type=number step=0.01 id=k3 value=%KT3%></div>
 <div class=fg><label>Базовая t°C:</label><input type=number step=0.1 id=b3 value=%BT3%></div>
 <div id=ss3%D3%>
<div class=v>Давление: <span id=sv3>--</span></div>
<div class=v>Температура: <span id=st3>--</span></div>
<button onclick=z(3)>Обнулить</button>
 </div>
</div>
<div class=n>
 <button onclick=a()>Применить</button>
 <button onclick=s()>Сохранить</button>
 <a href=/><button>На главную</button></a>
</div>
</div>
</body>
</html>
)=====";

// Страница настройки зуммера
const char SPK_PAGE[] PROGMEM = R"=====(
<!doctype html>
<html>
<head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Зуммер</title>
<style>
body{font-family:Arial,sans-serif;background:#121212;color:#eee;margin:0;padding:10px}
.c{max-width:800px;margin:0 auto}
h1,h2{text-align:center;color:#4CAF50}
.d{background:#1e1e1e;border-radius:10px;padding:15px;margin:10px 0;box-shadow:0 2px 5px rgba(0,0,0,0.3)}
.f{margin:15px 0}
label{display:block;margin-bottom:5px;color:#bbb}
input,select{width:100%;padding:10px;box-sizing:border-box;background:#333;color:#eee;border:1px solid #444;border-radius:5px;font-size:16px}
.b{background:#4CAF50;border:none;padding:10px 20px;border-radius:5px;cursor:pointer;color:#fff;font-weight:bold;margin:5px}
.b:hover{background:#45a049}
.n{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0;justify-content:center}
@media (max-width:600px){.c{padding:0 10px}}
</style>
<script>
function updateTemps(){
 fetch('/getTemps').then(r=>r.text()).then(t=>{
document.getElementById('temps').innerHTML=t;
setTimeout(updateTemps, 1000);
 });
}
window.onload=updateTemps;
</script>
</head>
<body>
<div class=c>
<h1>Зуммер</h1>
<div class=d>
<form action=/save_spk method=POST>
<div class=f>
<label>Датчик:</label>
<select name=sensor>
<option value=-1%s0>Отключено</option>
<option value=0%s1>P (давление)</option>
<option value=1%s2>T1 (Пар)</option>
<option value=2%s3>T2 (Царга)</option>
<option value=3%s4>T3 (Куб)</option>
<option value=4%s5>T4 (Вода)</option>
</select>
</div>
<div class=f>
<label>Порог (°C):</label>
<input type=number name=t_target value="%tt" step=0.1 min=0 max=150>
</div>
<div class=f>
<label>Гудков:</label>
<input type=number name=spk_count value="%cc" min=1 max=20>
</div>
<button type=submit class=b>Сохранить</button>
</form>
</div>
<div class=d>
<h2>Температуры</h2>
<div id=temps class=t>Загрузка...</div>
</div>
<div class=n>
<a href=/><button class=b>Назад</button></a>
</div>
</div>
</body>
</html>
)=====";

// Страница настройки электронного попугая
const char ALC_PAGE[] PROGMEM = R"=====(
<!doctype html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Настройка электронного попугая</title>
<style>
body{font-family:Arial,sans-serif;background:#121212;color:#eee;margin:0;padding:10px;}
.container{max-width:800px;margin:0 auto;}
h1,h2{text-align:center;color:#4CAF50;}
.card{background:#1e1e1e;border-radius:10px;padding:15px;margin:10px 0;box-shadow:0 2px 5px rgba(0,0,0,0.3);}
.form-group{margin:15px 0;}
label{display:block;margin-bottom:5px;color:#bbb;}
input,select,textarea{width:100%;padding:10px;box-sizing:border-box;background:#333;color:#eee;border:1px solid #444;border-radius:5px;font-size:16px;}
button{background:#4CAF50;border:none;padding:10px 20px;border-radius:5px;cursor:pointer;color:white;font-weight:bold;margin:5px;transition:background 0.3s;}
button:hover{background:#45a049;}
.nav{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0;justify-content:center;}
.temp-display{background:#1e1e1e;padding:15px;border-radius:5px;margin:15px 0;}
.checkbox-container{display:flex;align-items:center;margin:15px 0;}
.checkbox-container input[type="checkbox"]{width:auto;margin-right:10px;}
@media (max-width:600px){.container{padding:0 10px;}}
</style>
<script>
function updateAlc() {
 fetch('/getAlcData').then(r=>r.json()).then(data=>{
 document.getElementById('alcValue').innerText = data.alc.toFixed(1);
 document.getElementById('alcTempValue').innerText = data.alcTemp.toFixed(1);
 document.getElementById('pressureValue').innerText = data.pressure.toFixed(2);
 document.getElementById('tempValue').innerText = data.temp.toFixed(1);
 setTimeout(updateAlc, 1000);
 });
}
function setSensor() {
 var sel = document.getElementById('sensorSelect');
 fetch('/setAlcSensor?num=' + sel.value);
}
function setThermoCorr() {
 var enabled = document.getElementById('thermoCheckbox').checked;
 fetch('/setAlcThermo?value=' + (enabled ? '0.3' : '0'));
}

function calibrateAlc() {
 var target = document.getElementById('alcTarget').value;
 fetch('/calibrateAlc?target=' + target).then(r=>r.text()).then(text=>{
 if(!text.includes("Invalid")) {
 document.getElementById('kValue').value = text.split(": ")[1];
 }
 });
}

function saveToEEPROM() {
    var kValue = document.getElementById('kValue').value;
    fetch('/saveAlcToEEPROM?k=' + kValue).then(r=>r.text()).then(text=>{
        alert(text);
    });
}
document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('sensorSelect').value = "%ALCSENSOR%";
    document.getElementById('thermoCheckbox').checked = %THERMOENABLED%;
    updateAlc(); // Запускаем автоматическое обновление
});
</script>
</head>
<body>
<div class="container">
<h1>Настройка электронного попугая</h1>
<div class="card">
<h2>Выбор датчика давления</h2>
<div class="form-group">
<select id="sensorSelect" onchange="setSensor()">
<option value="1">Датчик 1 (XGZP6897D)</option>
<option value="2">Датчик 2 (MPX5010DP)</option>
<option value="3">Датчик 3 (HX710B)</option>
</select>
</div>
</div>
<div class="card">
<h2>Термокоррекция</h2>
<div class="checkbox-container">
<input type="checkbox" id="thermoCheckbox" onchange="setThermoCorr()">
<label for="thermoCheckbox">Включить термокоррекцию</label>
</div>
</div>
<div class="card">
<h2>Калибровка</h2>
<div class="form-group">
<label>Целевое значение алкоголя (%):</label>
<input type="number" step="0.1" id="alcTarget" value="%ALCTARGET%">
</div>
<div class="form-group">
<label>Коэффициент калибровки:</label>
<input type="number" step="0.1" id="kValue" value="%ALCK%">
</div>
<button onclick="calibrateAlc()">Калибровать</button>
<button onclick="saveToEEPROM()">Сохранить настройки в EEPROM</button>
</div>
<div class="card">
<h2>Текущие измерения</h2>
<table style="width:100%">
<tr><th>Параметр</th><th>Значение</th></tr>
<tr><td>Алкоголь (%):</td><td id="alcValue">--</td></tr>
<tr><td>Алкоголь с коррекцией (%):</td><td id="alcTempValue">--</td></tr>
<tr><td>Давление (мм.рт.ст.):</td><td id="pressureValue">--</td></tr>
<tr><td>Температура (°C):</td><td id="tempValue">--</td></tr>
</table>
</div>
<div class="nav">
<a href="/"><button>Назад</button></a>
</div>
</div>
</body>
</html>
)=====";
const char DEBUG_PAGE[] PROGMEM = R"=====(
<!DOCTYPE html>
<html>
<head>
<meta charset=utf-8>
<title>Эмулятор</title>
<style>
body { font-family: Arial, sans-serif; margin: 20px; }
.form-group { margin-bottom: 15px; }
label { display: inline-block; width: 150px; }
input { width: 100px; }
button { padding: 8px 15px; background: #4CAF50; color: white; border: none; }
</style>
</head>
<body>
<h1>Эмулятор датчиков</h1>
<form action="/save_debug" method="POST">
<div class="form-group">
<label>Режим отладки:</label>
<input type="checkbox" name="debug_mode" %debug_checked%>
</div>
<div class="form-group">
<label>Давление:</label>
<input type="number" step="0.1" name="temp0" value="%temp0%"> мм.рт.ст.
</div>
<div class="form-group">
<label>Температура пара:</label>
<input type="number" step="0.1" name="temp1" value="%temp1%"> °C
</div>
<div class="form-group">
<label>Температура царги:</label>
<input type="number" step="0.1" name="temp2" value="%temp2%"> °C
</div>
<div class="form-group">
<label>Температура куба:</label>
<input type="number" step="0.1" name="temp3" value="%temp3%"> °C
</div>
<div class="form-group">
<label>Температура воды:</label>
<input type="number" step="0.1" name="temp4" value="%temp4%"> °C
</div>
<div class="form-group">
<label>Температура ТСА:</label>
<input type="number" step="0.1" name="temp5" value="%temp5%"> °C
</div>
<div class="form-group">
<label>Температура 6:</label>
<input type="number" step="0.1" name="temp6" value="%temp6%"> °C
</div>
<div class="form-group">
<label>Температура 7:</label>
<input type="number" step="0.1" name="temp7" value="%temp7%"> °C
</div>
<button type="submit">Применить</button>
</form>
<p><a href="/">На главную</a></p>
</body>
</html>
)=====";