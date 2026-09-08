#!/usr/bin/env python3
"""Статическая проверка формата V34/V35 и правила резюме сессии (T2, blynk-log-channel.md).

По аналогии с остальными smoke_blynk_*.py - извлекает РЕАЛЬНЫЕ тела нужных функций
(extract_function_body) и проверяет порядок значимых токенов (require_ordered_tokens),
без запуска прошивки. Покрывает:

- `format_log_base_fields()` (FS.ino) и `format_v34_tail_fields()` (Samovar.ino) собирают
  строку из ожидаемых полей в ожидаемом порядке (базовые 7 + хвостовые 18 = 25 полей
  log/4, см. PIN_SPEC.md); `build_idle_v34_line()` (FS.ino, простой) и
  `tick_publish_log_line()` (Samovar.ino, активный процесс) склеивают их в V34-формат
  `5,sessionId,statusInt,<25 полей>`.
- `session_begin()` формирует sessionId/resume по правилу «доступность резюме, выставленная
  restore_state_snapshot(), И укладывание в SESSION_RESUME_WINDOW_S от факта РЕАЛЬНОГО
  старта процесса» - именно в этой функции, а не в restore_state_snapshot() (там на старте
  millis() всегда около нуля независимо от того, сколько пользователь ждал).
- Негативная проверка (регресс п. 3.2 T2.md): session_begin() НЕ берёт BlynkLockGuard и не
  зовёт Blynk.virtualWrite напрямую - только формирует строку и кладёт в staging-буфер
  (blynk_stage_session_start(), Blynk.ino); иначе синхронный вызов из BLYNK_WRITE(V3) (уже
  под BlynkLockGuard в tick_blynk()) дал бы дедлок по таймауту.
- `restore_state_snapshot()` выставляет sessionResumeAvailable/sessionResumeId ДО первого
  содержательного return (по snapshot.powerOn/programLost), а не после.
- Все четыре точки старта процесса (Menu.ino::menu_samovar_start(), beer.h::beer_proc(),
  nbk.h::run_nbk_program(), mode_common.h::mode_tick_heating_session()) зовут
  session_begin(...) БЕЗУСЛОВНО - MQTT и его MqttSendMsg(..., "st") полностью удалены в T3,
  тест проверяет, что след MqttSendMsg/USE_MQTT в эти функции не вернулся.
- (T2-review-1.md) Стейджинг-буферы s_pendingV34Line/s_pendingV35Line (Blynk.ino) вмещают
  честный худший случай (посчитан по типам полей и клампу format_float, см. константы
  V34_WORST_CASE_BYTES/V35_WORST_CASE_BYTES ниже), а не оценку "на глаз". blynk_stage_log_line()
  при переполнении логирует и НЕ отправляет строку (сервер ждёт ровно 25 полей после
  sessionId,statusInt - обрезанный мусор хуже отсутствующей строки). blynk_stage_session_start()
  при переполнении режет по границе UTF-8-символа и логирует факт обрезания - буфер сайзится
  под лимит описания WebServer.ino (250 байт), но экранирование "%"->"&#37;" может раздуть
  описание сверх любого статического расчёта.
- (T2-review-1.md) current_power_volt в format_v34_tail_fields() идёт через format_float(v, 2),
  как и соседние поля - не через голый (String)current_power_volt без клампа.
- (T3, blynk-log-channel.md) copy_start_session_description() (runtime_helpers.h, переим.
  из copy_mqtt_session_description после удаления MQTT) меняет перенос строки в описании
  сессии на "; ", но БОЛЬШЕ НЕ экранирует запятую - единственный потребитель этой строки
  теперь V35, а сервер (SamovarLogDao.parseSessionStart) разбирает payload как
  split(",", 7): лимит в 7 полей оставляет любые запятые внутри description нетронутыми,
  в последнем поле. Также раскодирует "&#37;" -> "%" (веб-экранирование SessionDescription
  в commit_profile_operation() не должно попадать в LOG.DESCRIPTION).
"""
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


samovar = strip_cpp_comments(read_text("Samovar.ino"))
fs_ino = strip_cpp_comments(read_text("FS.ino"))
menu_ino = strip_cpp_comments(read_text("Menu.ino"))
beer_h = strip_cpp_comments(read_text("beer.h"))
nbk_h = strip_cpp_comments(read_text("nbk.h"))
mode_common_h = strip_cpp_comments(read_text("mode_common.h"))
blynk_ino = strip_cpp_comments(read_text("Blynk.ino"))
runtime_helpers_h = strip_cpp_comments(read_text("runtime_helpers.h"))

# --- Базовые 7 полей (FS.ino): Crt + 4 температуры + давление [+ номер программы] ---
if fs_ino:
    base_fields_body = body(
        fs_ino,
        "static String format_log_base_fields(const float sensorTemp[], float pressure, uint8_t programNum)",
    )
    require_ordered_tokens(
        "format_log_base_fields (базовые 7 полей V34/append_data в фиксированном порядке)",
        base_fields_body,
        [
            "str = Crt;",
            "for (uint8_t i = 0; i < DS_LOGGED_SENSOR_COUNT; i++)",
            "format_float(sensorTemp[i], 3)",
            "format_float(pressure, 2)",
            "#ifdef WRITE_PROGNUM_IN_LOG",
            "programNum + 1",
        ],
        errors,
    )

    idle_body = body(fs_ino, "static String build_idle_v34_line()")
    require_ordered_tokens(
        "build_idle_v34_line (V34 в простое: sessionId=0, статус, базовые+хвостовые поля)",
        idle_body,
        [
            "format_log_base_fields(sensorTemp, bme_pressure, ProgramNum)",
            '"5,0,"',
            "String((int)SamovarStatusInt)",
            "base",
            "format_v34_tail_fields()",
        ],
        errors,
    )

# --- Хвостовые 18 полей (Samovar.ino): общие для активного процесса и простоя ---
if samovar:
    tail_body = body(samovar, "static String format_v34_tail_fields()")
    require_ordered_tokens(
        "format_v34_tail_fields (хвостовые поля V34/log-4 в фиксированном порядке)",
        tail_body,
        [
            "format_float(ACPSensor.avgTemp, 3)",
            "format_float(ActualVolumePerHour, 3)",
            "format_float(current_power_volt, 2)",
            "format_float(WFflowRate, 2)",
            "format_float(get_alcohol(TankSensor.avgTemp), 2)",
            "get_steam_alcohol(",
            "format_float(pressure_value, 2)",
            "format_float(CalculatedTargetFR, 2)",
            "format_float(CalculatedTargetFR, 2)",
            "impurityDetector.currentTrend",
            "impurityDetector.detectorStatus",
            "eventCode = program_Wait ? 1 : 0;",
            "SamSetup.PackDens",
            "format_float(SamSetup.ColHeight, 2)",
            "format_float(SamSetup.ColDiam, 1)",
            "format_float(CurrentHeatLoss, 0)",
            "program_type_to_string(logProgramType)",
            "String((int)Samovar_Mode)",
        ],
        errors,
    )

    tick_body = body(samovar, "static void tick_publish_log_line(const String &baseLine)")
    require_ordered_tokens(
        "tick_publish_log_line (V34 активного процесса)",
        tick_body,
        [
            "s += format_v34_tail_fields();",
            "#ifdef SAMOVAR_USE_BLYNK",
            'blynk_stage_log_line("5," + String(currentSessionId) + "," + String((int)SamovarStatusInt) + "," + s);',
            "#endif",
        ],
        errors,
    )
    if tick_body and ("MqttSendMsg" in tick_body or "USE_MQTT" in tick_body):
        errors.append(
            "tick_publish_log_line: MQTT удалён в T3, но в теле функции остался след "
            "MqttSendMsg/USE_MQTT"
        )

    # --- session_begin(): правило резюме именно здесь, не в restore_state_snapshot() ---
    session_begin_body = body(samovar, "void session_begin(const String& sessionDescription)")
    require_ordered_tokens(
        "session_begin (резюм-правило: доступность И окно времени ИМЕННО на старте процесса)",
        session_begin_body,
        [
            "const bool resume = sessionResumeAvailable && (millis() / 1000UL < SESSION_RESUME_WINDOW_S);",
            "sessionResumeAvailable = false;",
            "currentSessionId = sessionResumeId;",
            "const uint32_t epoch = ntp_snapshot_epoch_now();",
            "(epoch > NTP_PLAUSIBLE_MIN_EPOCH) ? epoch : esp_random();",
            "blynk_stage_session_start(line);",
        ],
        errors,
    )
    if session_begin_body:
        for forbidden in ("BlynkLockGuard", "Blynk.virtualWrite", "Blynk.run("):
            if forbidden in session_begin_body:
                errors.append(
                    f"session_begin must NOT call Blynk library directly ({forbidden} found) - "
                    "оно вызывается синхронно из BLYNK_WRITE(V3), уже под BlynkLockGuard "
                    "(tick_blynk()); повторный захват/вызов даст дедлок по таймауту"
                )

    # --- restore_state_snapshot(): резюм-флаги ДО первого содержательного return ---
    restore_body = body(samovar, "static void restore_state_snapshot()")
    require_ordered_tokens(
        "restore_state_snapshot (резюм-флаги выставляются ДО return по powerOn/programLost)",
        restore_body,
        [
            "sessionResumeAvailable = snapshot.powerOn && restored && snapshot.sessionId != 0;",
            "sessionResumeId = snapshot.sessionId;",
            "if (!snapshot.powerOn && !programLost) return;",
        ],
        errors,
    )

# --- Четыре точки старта процесса: session_begin(...) вызывается БЕЗУСЛОВНО. MQTT удалён
# в T3 - тест дополнительно сторожит регресс (след MqttSendMsg/USE_MQTT не должен вернуться). ---
START_SITES = [
    ("Menu.ino", menu_ino, "void menu_samovar_start()", "session_begin(sessionDescription);"),
    ("beer.h", beer_h, "void beer_proc()", "session_begin(sessionDescription);"),
    ("nbk.h", nbk_h, "void run_nbk_program(uint8_t num, bool workConfirmed, bool optimumEntry)",
     "session_begin(sessionDescription);"),
    ("mode_common.h", mode_common_h, "inline ModeHeatingStartResult mode_tick_heating_session(int16_t activeStatus)",
     "session_begin(modeHeatingStart.sessionDescription);"),
]
for file_name, source, fn_signature, call_token in START_SITES:
    if not source:
        continue
    fn_body = body(source, fn_signature)
    fn_name = fn_signature.split('(')[0].split()[-1]
    require_ordered_tokens(
        f"{file_name}::{fn_name} (session_begin вызывается безусловно)",
        fn_body,
        [call_token],
        errors,
    )
    if fn_body and ("MqttSendMsg" in fn_body or "USE_MQTT" in fn_body):
        errors.append(
            f"{file_name}::{fn_name}: MQTT удалён в T3, но в теле функции остался след "
            "MqttSendMsg/USE_MQTT"
        )

# --- Размеры стейджинг-буферов V34/V35 (T2-review-1.md CRITICAL/WARNING): полезная ёмкость
# (sizeof - 1 байт под '\0') обязана вмещать честный худший случай по типам полей, а не
# оценку "на глаз", которая когда-то дала 220/160 байт при реальных 236/293. ---

# V34: "5," + sessionId uint32_t(10) + "," + statusInt int16_t "-32768"(6) + "," = 20;
# format_log_base_fields(): Crt "MM-DD HH:MM:SS"(14) + 4 датчика по format_float(,3)
# "-99999.000"(","+10=11 каждый, 44) + давление format_float(,2)(","+9=10)
# + programNum+1 до 3 цифр(","+3=4) = 72;
# format_v34_tail_fields(), 18 полей с клампом format_float(±99999): 9 float-полей на
# 2-3 знака (11+11+10+10+10+10+10+10+10=92) + temp_delta format_float(,3)(11)
# + detectorStatus/PackDens uint8_t до 3 цифр(4+4=8) + event_code 0/1(2)
# + col_height format_float(,2)(10) + col_diameter format_float(,1)(","+8=9)
# + heat_loss format_float(,0)(","+6=7) + program_type 0-1 символ(2)
# + mode (int)Samovar_Mode(","+2=3) = 144.
V34_WORST_CASE_BYTES = 20 + 72 + 144  # 236

# V35: sessionId uint32_t(10) + "," + resume "0"/"1"(1) + "," + chipId uint32_t(10) + ","
# + SamSetup.TimeZone uint8_t(3) + "," + SAMOVAR_VERSION "7.00"(4) + "," + resetReason,
# худшее "deepsleep"/"brownout"(9) + "," + description, лимит WebServer.ino(250) = 293.
V35_WORST_CASE_BYTES = 10 + 1 + 1 + 1 + 10 + 1 + 3 + 1 + 4 + 1 + 9 + 1 + 250  # 293


def staging_buffer_capacity(name: str) -> int:
    if not blynk_ino:
        return 0
    match = re.search(rf"static char {re.escape(name)}\[(\d+)\]\s*;", blynk_ino)
    if not match:
        errors.append(f"{name}: объявление 'static char {name}[N];' не найдено в Blynk.ino")
        return 0
    return int(match.group(1)) - 1  # -1 байт под завершающий '\0'


v34_capacity = staging_buffer_capacity("s_pendingV34Line")
if v34_capacity and v34_capacity < V34_WORST_CASE_BYTES:
    errors.append(
        f"s_pendingV34Line: полезная ёмкость {v34_capacity} байт меньше честного худшего "
        f"случая {V34_WORST_CASE_BYTES} байт - strlcpy молча обрежет строку с меньшим числом "
        "полей 25, чем ждёт парсер сервера (T2-review-1.md CRITICAL/WARNING)"
    )

v35_capacity = staging_buffer_capacity("s_pendingV35Line")
if v35_capacity and v35_capacity < V35_WORST_CASE_BYTES:
    errors.append(
        f"s_pendingV35Line: полезная ёмкость {v35_capacity} байт меньше честного худшего "
        f"случая {V35_WORST_CASE_BYTES} байт (описание до 250 байт по лимиту WebServer.ino) - "
        "T2-review-1.md CRITICAL"
    )

# --- blynk_stage_log_line(): переполнение -> лог и НЕ отправлять (не резать по живому). ---
if blynk_ino:
    stage_log_body = body(blynk_ino, "void blynk_stage_log_line(const String& line)")
    require_ordered_tokens(
        "blynk_stage_log_line (переполнение - лог и пропуск ДО критической секции, не мусор в буфере)",
        stage_log_body,
        [
            "line.length() > sizeof(s_pendingV34Line) - 1",
            "WriteConsoleLog(",
            "return;",
            "portENTER_CRITICAL(&s_blynkLogLineMux);",
            "strlcpy(s_pendingV34Line",
            "portEXIT_CRITICAL(&s_blynkLogLineMux);",
        ],
        errors,
    )

    # --- blynk_stage_session_start(): переполнение -> обрезка по границе UTF-8 + лог. ---
    stage_session_body = body(blynk_ino, "void blynk_stage_session_start(const String& line)")
    require_ordered_tokens(
        "blynk_stage_session_start (переполнение - обрезка по границе UTF-8-символа с логом)",
        stage_session_body,
        [
            "capacity = sizeof(s_pendingV35Line) - 1",
            "line.length() <= capacity",
            "0xC0) == 0x80",
            "WriteConsoleLog(",
            "line.substring(0, cut)",
            "portENTER_CRITICAL(&s_blynkSessionMux);",
            "strlcpy(s_pendingV35Line",
            "portEXIT_CRITICAL(&s_blynkSessionMux);",
        ],
        errors,
    )

# --- format_v34_tail_fields(): current_power_volt строго через format_float, без голого
# (String)current_power_volt без клампа (T2-review-1.md WARNING). ---
if samovar and tail_body and "(String)current_power_volt" in tail_body:
    errors.append(
        "format_v34_tail_fields must not use (String)current_power_volt (без клампа) - "
        "нужен format_float(current_power_volt, 2), как у соседних полей"
    )

# --- copy_start_session_description() (T3: переим. из copy_mqtt_session_description):
# перенос строки -> "; "; запятую НЕ экранируем - см. docstring (V35/split(",", 7)). ---
if runtime_helpers_h:
    copy_start_desc_body = body(
        runtime_helpers_h,
        "inline bool copy_start_session_description(String& description, "
        "TickType_t timeout = pdMS_TO_TICKS(500))",
    )
    require_ordered_tokens(
        "copy_start_session_description (перенос строки -> \"; \", без экранирования запятой)",
        copy_start_desc_body,
        [
            "description = SessionDescription;",
            r'description.replace("\r\n", "; ");',
            r'description.replace("\n", "; ");',
            r'description.replace("\r", "; ");',
            r'description.replace("&#37;", "%");',
        ],
        errors,
    )
    if copy_start_desc_body and 'description.replace(",", ";")' in copy_start_desc_body:
        errors.append(
            "copy_start_session_description больше не должен экранировать запятую - "
            'V35 единственный потребитель, сервер разбирает payload как split(",", 7)'
        )

if errors:
    print("Blynk V34/V35 format smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Blynk V34/V35 format smoke check passed")
