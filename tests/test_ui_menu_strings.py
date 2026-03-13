from pathlib import Path
import unittest


MENU_STRINGS_HEADER = Path("ui/menu/strings.h")
MENU_SOURCE = Path("Menu.ino")
MENU_STRING_USERS = [
    Path("Menu.ino"),
    Path("Samovar.ino"),
]

EXPECTED_PROGMEM_STRINGS = {
    "str_BACK": "<BACK",
    "str_Steam_T": "Steam T: ",
    "str_Pipe_T": "Pipe T: ",
    "str_Water_T": "Water T: ",
    "str_Tank_T": "Tank T: ",
    "str_Pressure": "Atm: ",
    "str_Progress": "Progress: ",
    "str_Start": ">Start: ",
    "str_Speed": ">Speed l/h: ",
    "str_Pause": ">Pause: ",
    "str_Reset_W": ">Reset withdrawal: ",
    "str_Get_Power": ">Get power ",
    "str_Setup": "/Setup",
    "str_IP": "IP: ",
    "str_Set_Steam_T": "Set Steam T: ",
    "str_Set_Pipe_T": "Set Pipe T: ",
    "str_Set_Water_T": "Set Water T: ",
    "str_Set_Tank_T": "Set Tank T: ",
    "str_Step_Ml": "^Step/ml: ",
    "str_Calibrate": ">Calibrate: ",
    "str_Program": "Prog>",
    "str_Type": "^Type: ",
    "str_Volume": "^Volume: ",
    "str_Capacity": "^Capacity: ",
    "str_Temp": "^Temp: ",
    "str_Power": "^Power: ",
    "str_Reset_WiFi": ">Reset WiFi",
}

EXPECTED_RUNTIME_STRINGS = {
    "menu_text_continue": "Continue",
    "menu_text_pause": "Pause",
    "menu_text_stop": "Stop",
    "menu_text_start": "Start",
    "menu_text_program_number_first": "Prg No 1",
    "menu_text_program_number_prefix": "Prg No ",
    "menu_text_program_finish": "Prg finish",
    "menu_text_stopped": "Stoped",
    "menu_text_stopped_padded": "Stoped             ",
    "menu_text_power_on": "ON",
}

MOVED_MENU_LITERALS = [
    '"Continue"',
    '"Pause"',
    '"Stop"',
    '"Start"',
    '"Prg No 1"',
    '"Prg No "',
    '"Prg finish"',
    '"Stoped"',
    '"Stoped             "',
    '"ON"',
]


class MenuStringsStructureTest(unittest.TestCase):
    def test_menu_strings_header_exists_with_baseline_texts(self) -> None:
        self.assertTrue(MENU_STRINGS_HEADER.exists(), "ui/menu/strings.h must exist")
        text = MENU_STRINGS_HEADER.read_text(encoding="utf-8")

        for name, value in EXPECTED_PROGMEM_STRINGS.items():
            with self.subTest(name=name):
                self.assertIn(f'static const char {name}[] PROGMEM = "{value}";', text)

        for name, value in EXPECTED_RUNTIME_STRINGS.items():
            with self.subTest(name=name):
                self.assertIn(f'static const char {name}[] = "{value}";', text)

    def test_menu_string_users_include_header_directly(self) -> None:
        for path in MENU_STRING_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "ui/menu/strings.h"', text)

    def test_menu_source_no_longer_keeps_inline_menu_literals(self) -> None:
        text = MENU_SOURCE.read_text(encoding="utf-8")

        self.assertNotIn("const char str_BACK[] PROGMEM", text)
        for literal in MOVED_MENU_LITERALS:
            with self.subTest(literal=literal):
                self.assertNotIn(literal, text)


if __name__ == "__main__":
    unittest.main()
