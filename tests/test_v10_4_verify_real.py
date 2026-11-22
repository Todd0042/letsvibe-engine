"""v10.4 claim checker on complaints from real v10.3 reports (mx5-dash, echoes-of-logos, letsvibe-reality-check),
against excerpts of the real files at the graded commits. Each verdict was checked by reading the code.

False complaints that must be dropped, and true or unverifiable ones that must be kept (never drop a true claim).
"""

from pathlib import Path

from letsvibe_engine.versions.v10_4_verified.verify import RepoIndex, check_claim

VEHICLE_DATA_H = "\n".join(
    ["#pragma once", "#include <stdint.h>"] + [f"// vehicle field {i}" for i in range(3, 33)]
    + ["    bool tireKnown[4] = {false, false, false, false};"] + [f"    uint16_t field{i} = 0;" for i in range(34, 107)]
)  # 106 lines, tireKnown once (line 33), like the real lib/mx5_config/VehicleData.h

BLE_ELM_CPP = """#include "BleElm.h"
#include <SPIFFS.h>

static bool logFsBegin() {
    bool ok = SPIFFS.begin(true);   // auto-format on very first boot
    if (!ok) {
        Serial.println("[conn] WARN: SPIFFS mount failed -> RAM-only logging");
        return false;
    }
    return true;
}

void BleElm::savePaired(const char* addr) {
    if (!SPIFFS.begin(true)) return;
    File f = SPIFFS.open("/paired.txt", FILE_WRITE);
    if (f) { f.print(addr); f.close(); }
}

bool BleElm::begin(const char* targetNamePrefix) {
    logFsBegin();
    return true;
}
"""

USER_PREFS_H = "\n".join(
    [f"// prefs {i}" for i in range(1, 32)]
    + ["    static uint8_t  getRotation();", "    static bool     getUnits();", "    static uint8_t  getThemeMode();",
       "    static uint8_t  getBrightness();", "    static bool     getAutoLog();", "    static bool     getSpeedMask();"]
)

SAVE_MANAGER_KT = """package com.voicerpg.android.engine

class SaveManager {
    fun load(): GameSaveData? {
        return try {
            val file = getSaveFile()
            val json = if (file != null && file.exists()) {
                file.readText()
            } else {
                inMemorySaveJson
            }

            if (json.isNullOrBlank()) return null
            gson.fromJson(json, GameSaveData::class.java)
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }
}
"""

SPEECH_MANAGER_KT = """package com.voicerpg.android.engine

class SpeechManager {
    private var autoListenAttemptCount = 0
    fun onRecognitionError() {
        autoListenAttemptCount = 0
        startListening()
    }
}
"""

EVALUATOR_PY = "\n".join(["import httpx", "", "LLAMA_URL = 'http://127.0.0.1:11435'"] + [f"# line {i}" for i in range(4, 289)])


def make_repo(tmp_path: Path) -> RepoIndex:
    files = {
        "lib/mx5_config/VehicleData.h": VEHICLE_DATA_H,
        # Real file is ~600 lines with the SPIFFS handling around 160 and 230: pad so cited lines are realistic.
        "lib/obd_ble/BleElm.cpp": BLE_ELM_CPP.replace('#include <SPIFFS.h>\n', '#include <SPIFFS.h>\n' + "".join(
            f"// connection helper {i}\n" for i in range(150))),
        "app/src/main/java/com/voicerpg/android/engine/SpeechManager.kt": SPEECH_MANAGER_KT,
        "lib/mx5_config/UserPrefs.h": USER_PREFS_H,
        "app/src/main/java/com/voicerpg/android/engine/SaveManager.kt": SAVE_MANAGER_KT,
        "letsvibe_rc/evaluator.py": EVALUATOR_PY,
    }
    for rel, text in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return RepoIndex(tmp_path)


FALSE = {  # real complaint -> part of the reason it must give
    "Duplicate tireKnown array in VehicleData.h (line 102 and 122)": "line 122",
    "Missing error handling for SPIFFS mount failure (lib/obd_ble/BleElm.cpp, line 102)": "if (!SPIFFS.begin(true)) return;",
    "Missing error handling for empty save file in SaveManager.load() when file exists but is empty": "SaveManager.kt",
}
KEPT = [
    # True, or not checkable from the code: never dropped.
    "No fallback for missing Llama server URL (uses default 127.0.0.1:11435) - letsvibe_rc/evaluator.py (line 12)",
    "Duplicate getter methods in UserPrefs.h (line 32, 34, 36)",  # generic: copy-paste logic can hide under other names
    "Uninitialized ring buffer in BleElm::begin() (line 52)",
    "No error handling for failed llama-server connection",
    "SpeechManager's auto-listen mode lacks proper error handling for repeated recognition failures",
    "Inconsistent unit display for speed (MPH/km/h)",
]


def test_real_false_complaints_are_dropped(tmp_path):
    repo = make_repo(tmp_path)
    for claim, why in FALSE.items():
        d = check_claim(claim, repo)
        assert d is not None and why in d.reason, (claim, d)


def test_real_true_or_unverifiable_complaints_are_kept(tmp_path):
    repo = make_repo(tmp_path)
    for claim in KEPT:
        assert check_claim(claim, repo) is None, (claim, check_claim(claim, repo))


# v10.4's real-model run on mx5-dash (1ba1595) kept three complaints the code disproves; none of them cites a file.
VEHICLE_H = """#pragma once
#include <stdint.h>
struct VehicleData {
    uint16_t rpm = 0;
    uint8_t coolantC = 0;          // 01 05 (minus 40)
    uint8_t oilTempC = 0;
    uint8_t coolantC2 = 0;
};
struct Broken {
    int speed = 0;
    int speed = 1;
};
"""
PREFS_CPP = """#include "VehicleData.h"
static char     sBlePrefix[32] = MX5_BLE_DEVICE_PREFIX;
static int      sRetries;
void load() {
    sRetries = readRetries();
    char     wheelDid[4][8];
}
"""


def test_mx5_complaints_without_a_file(tmp_path):
    (tmp_path / "VehicleData.h").write_text(VEHICLE_H)
    (tmp_path / "UserPrefs.cpp").write_text(PREFS_CPP)
    repo = RepoIndex(tmp_path, files=["VehicleData.h", "UserPrefs.cpp"])
    false = ["Duplicate field 'coolantC' in VehicleData struct causing data corruption",
             "Inconsistent TPMS tire mapping configuration (wheelDid vs. wheelDid)",
             "Uninitialized 'sBlePrefix' default value in UserPrefs"]
    for claim in false:
        assert check_claim(claim, repo), claim
    true = ["Duplicate field 'speed' in Broken struct",           # really declared twice
            "Uninitialized 'sRetries' used before load() runs",   # declared without a value; set later only
            "Inconsistent units: coolantC vs. oilTempC"]          # two different things
    for claim in true:
        assert check_claim(claim, repo) is None, claim
