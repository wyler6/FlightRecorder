"""Export FlightRecorder SavedVariables to flights.json (one flight per line).

Usage: python flightmap_export.py [input.lua] [output.json]

Defaults: reads the WoW SavedVariables file below and writes <repo>\map\flights.json,
plus flights-data.js next to it (both generated and git-ignored).
Python 3.10, standard library only.
"""
import json
import re
import sys
from pathlib import Path

DEFAULT_IN = r"F:\World of Warcraft\_forever_\WTF\Account\WYLER6\SavedVariables\FlightRecorder.lua"
# Relative to this script, so the repo can live anywhere.
DEFAULT_OUT = str(Path(__file__).resolve().parent.parent / "map" / "flights.json")

_NUM = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


class LuaParser:
    def __init__(self, text):
        self.s = text
        self.i = 0

    def err(self, msg):
        line = self.s.count("\n", 0, self.i) + 1
        raise ValueError(f"Lua parse error at line {line}: {msg}")

    def ws(self):
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif s.startswith("--", self.i):
                m = re.match(r"--\[(=*)\[", s[self.i:])
                if m:
                    end = s.find("]" + m.group(1) + "]", self.i)
                    self.i = n if end < 0 else end + len(m.group(1)) + 2
                else:
                    nl = s.find("\n", self.i)
                    self.i = n if nl < 0 else nl + 1
            else:
                break

    def parse_file(self):
        """Return dict of top-level assignments, e.g. {'FlightRecorderDB': {...}}."""
        out = {}
        while True:
            self.ws()
            if self.i >= len(self.s):
                return out
            m = _IDENT.match(self.s, self.i)
            if not m:
                self.err("expected identifier")
            self.i = m.end()
            self.ws()
            if self.s[self.i:self.i + 1] != "=":
                self.err("expected '='")
            self.i += 1
            out[m.group(0)] = self.value()

    def value(self):
        self.ws()
        s = self.s
        c = s[self.i:self.i + 1]
        if c == "{":
            return self.table()
        if c in ('"', "'"):
            return self.string()
        m = _NUM.match(s, self.i)
        if m:
            self.i = m.end()
            t = m.group(0)
            if t.lower().lstrip("-").startswith("0x"):
                return int(t, 16)
            f = float(t)
            return int(f) if re.fullmatch(r"-?\d+", t) else f
        m = _IDENT.match(s, self.i)
        if m:
            self.i = m.end()
            w = m.group(0)
            if w == "true":
                return True
            if w == "false":
                return False
            if w == "nil":
                return None
            self.err(f"unexpected identifier {w!r}")
        self.err(f"unexpected character {c!r}")

    def string(self):
        s = self.s
        q = s[self.i]
        self.i += 1
        buf = []
        while True:
            if self.i >= len(s):
                self.err("unterminated string")
            c = s[self.i]
            if c == q:
                self.i += 1
                return "".join(buf)
            if c == "\\":
                self.i += 1
                e = s[self.i]
                if e.isdigit():
                    m = re.compile(r"\d{1,3}").match(s, self.i)
                    buf.append(chr(int(m.group(0))))
                    self.i = m.end()
                    continue
                if e == "\n":
                    buf.append("\n")
                else:
                    buf.append(_ESC.get(e, e))
                self.i += 1
            else:
                buf.append(c)
                self.i += 1

    def table(self):
        s = self.s
        self.i += 1  # {
        items, keyed = [], {}
        while True:
            self.ws()
            c = s[self.i:self.i + 1]
            if c == "":
                self.err("unterminated table")
            if c == "}":
                self.i += 1
                break
            if c in ",;":
                self.i += 1
                continue
            if c == "[":
                self.i += 1
                k = self.value()
                self.ws()
                if s[self.i:self.i + 1] != "]":
                    self.err("expected ']'")
                self.i += 1
                self.ws()
                if s[self.i:self.i + 1] != "=":
                    self.err("expected '='")
                self.i += 1
                v = self.value()
                if v is not None:
                    keyed[k] = v
                continue
            m = _IDENT.match(s, self.i)
            if m and m.group(0) not in ("true", "false", "nil"):
                j = m.end()
                save = self.i
                self.i = j
                self.ws()
                if s[self.i:self.i + 1] == "=" and s[self.i + 1:self.i + 2] != "=":
                    self.i += 1
                    v = self.value()
                    if v is not None:
                        keyed[m.group(0)] = v
                    continue
                self.i = save
            items.append(self.value())
        if keyed:
            for n, v in enumerate(items, 1):
                keyed.setdefault(n, v)
            return {str(k): v for k, v in keyed.items()}
        return items


def convert_flight(f):
    out = {}
    for k, v in f.items():
        if k == "points":
            pts = []
            for p in v:
                if isinstance(p, list) and len(p) >= 5 and p[3] is not None and p[4] is not None:
                    pts.append([p[0], round(p[3], 5), round(p[4], 5)])
            out[k] = pts
        else:
            out[k] = v
    out.setdefault("points", [])
    return out


def fmt_dur(sec):
    sec = int(round(sec or 0))
    return f"{sec // 60}:{sec % 60:02d}"


def main(argv):
    src = Path(argv[1]) if len(argv) > 1 else Path(DEFAULT_IN)
    dst = Path(argv[2]) if len(argv) > 2 else Path(DEFAULT_OUT)
    data = LuaParser(src.read_text(encoding="utf-8", errors="replace")).parse_file()
    db = data.get("FlightRecorderDB")
    if not isinstance(db, dict):
        raise SystemExit("FlightRecorderDB not found in input")
    flights = [convert_flight(f) for f in db.get("flights", []) if isinstance(f, dict)]
    dst.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=True keeps the JSON valid as a JS literal (no raw U+2028/U+2029) and pure ASCII.
    lines = [json.dumps(f, separators=(",", ":"), ensure_ascii=True) for f in flights]
    text = "[\n" + ",\n".join(lines) + "\n]" if lines else "[]"
    dst.write_text(text + "\n", encoding="utf-8")
    js = dst.with_name("flights-data.js")
    js.write_text("// Generated by flightmap_export.py - do not edit.\nwindow.FLIGHT_DATA = " + text + ";\n", encoding="utf-8")
    for f in flights:
        print(f"{f.get('char')}: {f.get('from')} -> {f.get('to')}, {fmt_dur(f.get('duration'))}, "
              f"{f.get('distance')} yd, {len(f['points'])} points, "
              f"{'complete' if f.get('complete') else 'partial'} ({f.get('note')})")
    print(f"Wrote {len(flights)} flight(s) to {dst}")
    print(f"Wrote {js}")


if __name__ == "__main__":
    main(sys.argv)
