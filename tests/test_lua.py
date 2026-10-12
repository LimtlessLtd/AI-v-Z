"""Checks of the mod's Lua against the installed game, which is the only place it runs.

1. Every file compiles with Project Zomboid's own Lua compiler: tests/LuaCheck.java, built with `javac` and run on
   the game's Java runtime against projectzomboid.jar. Nothing is executed. A syntax error stops the whole mod.
2. Every method name the mod calls (`obj:name(`, `X.name(`) exists somewhere in the game: a method or field in
   projectzomboid.jar, or a function in the game's Lua or the mod's own. This catches invented names, such as
   `Stats:getEndurance()` (backlog, "Lessons"), though not a real name called on the wrong class.

Both skip where the game isn't installed, as in the cloud; the compile check also needs `javac`. The game's folder
comes from the PZ_DIR environment variable, else Steam's library list (registry SteamPath, libraryfolders.vdf).
"""

import os
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD_LUA = ROOT / "mod" / "AIvZ" / "42" / "media" / "lua"
LUA = sorted(MOD_LUA.rglob("*.lua"))

# Lua's own functions and Kahlua's instanceof, which the jar and the game's Lua don't define by name
LUA_STD = set("""assert error ipairs pairs next pcall print rawget rawset select setmetatable getmetatable tonumber
tostring type unpack require format sub gsub gmatch match find len lower upper rep byte char reverse insert remove
concat sort floor ceil abs max min sqrt sin cos tan atan atan2 exp log pow random fmod modf instanceof""".split())


def game_dir():
    """Project Zomboid's install folder, or None."""
    cands = [os.environ.get("PZ_DIR")]
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
        vdf = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        libs = [steam] + [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf)]
        cands += [str(lib / "steamapps" / "common" / "ProjectZomboid") for lib in libs]
    except (ImportError, OSError):
        pass
    for c in cands:
        if c and (Path(c) / "projectzomboid.jar").is_file():
            return Path(c)
    return None


def member_names(data):
    """The field and method names declared in one .class file."""
    n = struct.unpack(">H", data[8:10])[0]
    p, i, utf = 10, 1, {}
    while i < n:   # the constant pool: keep its strings, skip the rest by tag size
        tag = data[p]
        if tag == 1:
            ln = struct.unpack(">H", data[p + 1:p + 3])[0]
            utf[i] = data[p + 3:p + 3 + ln].decode("utf-8", "replace")
            p += 3 + ln
        elif tag in (5, 6):   # long, double: two slots
            p += 9
            i += 1
        else:
            p += {3: 5, 4: 5, 7: 3, 8: 3, 16: 3, 19: 3, 20: 3, 9: 5, 10: 5, 11: 5, 12: 5, 17: 5, 18: 5, 15: 4}[tag]
        i += 1
    p += 6
    p += 2 + 2 * struct.unpack(">H", data[p:p + 2])[0]   # interfaces
    names = set()
    for _ in range(2):   # fields, then methods
        count = struct.unpack(">H", data[p:p + 2])[0]
        p += 2
        for _ in range(count):
            names.add(utf[struct.unpack(">H", data[p + 2:p + 4])[0]])
            attrs = struct.unpack(">H", data[p + 6:p + 8])[0]
            p += 8
            for _ in range(attrs):
                p += 6 + struct.unpack(">I", data[p + 2:p + 6])[0]
    return names


def mod_calls():
    """{method name: ["file:line", ...]} for every `:name(` and `.name(` in the mod's Lua, outside comments and strings."""
    calls = {}
    for f in LUA:
        for ln, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = re.sub(r'"[^"]*"|\'[^\']*\'', '""', line).split("--", 1)[0]
            for m in re.finditer(r"[:.](\w+)\s*\(", code):
                calls.setdefault(m.group(1), []).append(f"{f.name}:{ln}")
    return calls


class LuaAgainstTheGameTest(unittest.TestCase):
    def setUp(self):
        self.pz = game_dir()
        if not self.pz:
            self.skipTest("needs Project Zomboid (PZ_DIR or Steam)")
        self.assertTrue(LUA)

    def test_every_mod_file_compiles_with_the_games_compiler(self):
        javac = shutil.which("javac")
        java = next((x for x in (self.pz / "jre64" / "bin" / "java.exe", self.pz / "jre64" / "bin" / "java")
                     if x.is_file()), None)
        if not (javac and java):
            self.skipTest("needs javac and the game's Java runtime")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([javac, "--release", "11", "-d", tmp, str(ROOT / "tests" / "LuaCheck.java")], check=True,
                           capture_output=True, timeout=120)
            r = subprocess.run([str(java), "-cp", os.pathsep.join([str(self.pz / "projectzomboid.jar"), tmp]), "LuaCheck"]
                               + [str(f) for f in LUA], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("OK "), len(LUA), r.stdout)

    def test_every_method_name_the_mod_calls_exists_in_the_game(self):
        known = set(LUA_STD)
        with zipfile.ZipFile(self.pz / "projectzomboid.jar") as z:
            for name in z.namelist():
                if name.endswith(".class"):
                    known |= member_names(z.read(name))
        defined = re.compile(r"function\s+[\w.:]*?(\w+)\s*\(|(\w+)\s*=\s*function\b")
        for f in list((self.pz / "media" / "lua").rglob("*.lua")) + LUA:
            for m in defined.finditer(f.read_text(encoding="utf-8", errors="replace")):
                known.add(m.group(1) or m.group(2))
        unknown = {k: v for k, v in mod_calls().items() if k not in known}
        self.assertEqual(unknown, {}, "method names found nowhere in the game (first uses listed)")


if __name__ == "__main__":
    unittest.main()
