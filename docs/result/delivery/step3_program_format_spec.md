# Спецификация форматов программ режимов

Дата: `2026-03-19`

Назначение: зафиксировать exact grammar каждой program family как baseline contract для Шага 3.

Связь: этот документ является delivery-артефактом Task 3.2 (program format freeze) из
[03_program_codec_normalization_plan_ru.md](/srv/git_projects/Samovar/docs/refactoring/03_program_codec_normalization_plan_ru.md).

## Общие правила

- Разделитель полей внутри строки: `;`
- Разделитель строк: `\n`
- Пустые строки и trailing whitespace (`\r`, пробел, табуляция) игнорируются при parse
- Максимальное число строк программы: `CAPACITY_NUM * 2` (CAPACITY_NUM = 10, итого 20 строк)
- Максимальная длина входной строки: `MAX_PROGRAM_INPUT_LEN` (1024 байт)
- При ошибке parse: массив `program[]` обнуляется, `ProgramLen = 0`, отправляется `ALARM_MSG`
- Лишние поля (tokExtra) отвергаются — формат строго фиксирован
- Shared state: все families используют единый массив `program[CAPACITY_NUM * 2]` и `ProgramLen`

## 1. RECT family

**Используется режимами:** RECT, BK, LUA

**Codec owner:** `modes/rect/rect_program_codec.h`

**API:** `set_program(String WProgram)`, `get_program(uint8_t s)`

### Grammar строки

```
WType;Volume;Speed;capacity_num;Temp;Power\n
```

| Поле | Тип | Поле program[] | Ограничения |
| --- | --- | --- | --- |
| WType | string | `.WType` | непустая строка |
| Volume | uint16_t | `.Volume` | 0..65535 |
| Speed | float | `.Speed` | > 0 (кроме WType == "P") |
| capacity_num | uint8_t | `.capacity_num` | 0..CAPACITY_NUM |
| Temp | float | `.Temp` | — |
| Power | float | `.Power` | — |

### Производные поля

- Если WType == "P": `Time = Volume / 3600.0`
- Иначе: `Time = Volume / Speed / 1000.0`

### Serialization (get_program)

```
WType;Volume;Speed;capacity_num;Temp;Power\n
```

Порядок полей при stringify совпадает с порядком при parse.

`get_program(CAPACITY_NUM * 2)` возвращает все строки; `get_program(n)` возвращает одну строку `n`.

## 2. DIST family

**Используется режимами:** DIST

**Codec owner:** `modes/dist/dist_program_codec.h`

**API:** `set_dist_program(String WProgram)`, `get_dist_program()`

### Grammar строки

```
WType;Speed;capacity_num;Power\n
```

| Поле | Тип | Поле program[] | Ограничения |
| --- | --- | --- | --- |
| WType | string | `.WType` | непустая строка |
| Speed | float | `.Speed` | — |
| capacity_num | uint8_t | `.capacity_num` | 0..CAPACITY_NUM |
| Power | float | `.Power` | — |

### Serialization (get_dist_program)

```
WType;Speed;capacity_num;Power\n
```

Примечание: `capacity_num` сериализуется как `(int)`, т.е. без десятичной точки.

## 3. BEER family

**Используется режимами:** BEER, SUVID

**Codec owner:** `modes/beer/beer_program_codec.h`

**API:** `set_beer_program(String WProgram)`, `get_beer_program()`

### Grammar строки

```
WType;Temp;Time;devType^Speed^Volume^Power;TempSensor\n
```

| Поле | Тип | Поле program[] | Ограничения |
| --- | --- | --- | --- |
| WType | string | `.WType` | непустая строка |
| Temp | float | `.Temp` | — |
| Time | float | `.Time` | >= 0 |
| Device payload | composite | см. ниже | — |
| TempSensor | uint8_t | `.TempSensor` | 0..4 |

### Device payload (4-е поле, разделитель `^`)

| Subfield | Тип | Поле program[] | Ограничения |
| --- | --- | --- | --- |
| devType | uint8_t | `.capacity_num` | 0..255 |
| Speed | long | `.Speed` (как float) | — |
| Volume (onTime) | uint16_t | `.Volume` | 0..65535 |
| Power (offTime) | uint16_t | `.Power` | 0..65535 |

### Serialization (get_beer_program)

```
WType;Temp;Time;capacity_num^Speed^Volume^Power;TempSensor\n
```

Примечание: `Time` сериализуется как `(int)`.

### Два error path

1. Ошибка parse основных полей: `"Ошибка программы: неверный формат строки beer"`
2. Ошибка parse device payload: `"Ошибка программы: неверный шаблон устройства beer"`

## 4. NBK family

**Используется режимами:** NBK

**Codec owner:** `modes/nbk/nbk_program_codec.h`

**API:** `set_nbk_program(String WProgram)`, `get_nbk_program()`

### Grammar строки

```
WType;Speed;Power\n
```

| Поле | Тип | Поле program[] | Ограничения |
| --- | --- | --- | --- |
| WType | string | `.WType` | непустая строка |
| Speed | float | `.Speed` | — |
| Power | float | `.Power` | — |

### Serialization (get_nbk_program)

```
WType;Speed;Power\n
```

Примечание: `Power` сериализуется как `(int)`.

## 5. Сводная таблица families

| Family | Полей в строке | Составные поля | Codec owner | Alias modes |
| --- | --- | --- | --- | --- |
| RECT | 6 | нет | `modes/rect/rect_program_codec.h` | BK, LUA |
| DIST | 4 | нет | `modes/dist/dist_program_codec.h` | — |
| BEER | 5 (4-е составное) | device payload через `^` | `modes/beer/beer_program_codec.h` | SUVID |
| NBK | 3 | нет | `modes/nbk/nbk_program_codec.h` | — |

## 6. Тестовое покрытие

| Family | Тест | Что проверяет |
| --- | --- | --- |
| RECT | `test_modes_rect_program_codec_baseline.py` | parse field mapping, serialization order, baseline parity |
| DIST | `test_modes_dist_program_codec.py::DistFormatFreezeTest` | parse field order, field assignment, serialization order, error reset |
| BEER | `test_modes_beer_program_codec.py::BeerFormatFreezeTest` | parse field order, field assignment, device payload, serialization order, error reset |
| NBK | `test_modes_nbk_program_codec.py::NbkFormatFreezeTest` | parse field order, field assignment, serialization order, error reset |

## 7. Инварианты

- Форматы строк программ не должны меняться без отдельного решения.
- Все codec owners используют shared `program[]` и `ProgramLen`.
- Alias owners (`BK/LUA → RECT`, `SUVID → BEER`) зафиксированы в `mode_ownership.h` через `mode_program_owner()`.
- HTTP payload `WProgram` остаётся текстовой строкой с `\n`-разделителями.
