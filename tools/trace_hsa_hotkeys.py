"""Trace HSA hotkey -> input calls without touching Hearthstone.

Attaches Frida to HSAng.exe (default) and logs user32 input/message calls.
Use while the user presses the five BG hotkeys (W/E/D/F/S) in a recruit turn:

    python tools/trace_hsa_hotkeys.py --process HSAng.exe \
        --out runs/live/hsa_hotkey_trace.jsonl

It does NOT inject into Hearthstone and does NOT send any input itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

JS = r"""
function log(o) { send(o); }
const fns = ["PostMessageW","SendMessageW","SetCursorPos","SendInput",
             "mouse_event","keybd_event","RegisterHotKey"];
for (const name of fns) {
  let addr = null;
  try { addr = Module.getExportByName("user32.dll", name); } catch (e) { }
  if (!addr) continue;
  Interceptor.attach(addr, {
    onEnter(args) {
      let caller = "?";
      try {
        caller = Thread.backtrace(this.context, Backtracer.ACCURATE)
          .slice(0, 3).map(a => {
            const m = Process.findModuleByAddress(a);
            return m ? (m.name + "+0x" + a.sub(m.base).toString(16)) : a.toString();
          }).join(" <- ");
      } catch (e) { caller = String(e); }
      const a = [];
      for (let i = 0; i < 6; i++) { try { a.push(args[i].toInt32()); } catch (e) { a.push(null); } }
      log({fn: name, args: a, caller, ts: Date.now()});
    }
  });
}
log({ready: true, pid: Process.id, name: Process.name});
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--process", default="HSAng.exe")
    ap.add_argument("--out", default="runs/live/hsa_hotkey_trace.jsonl")
    ap.add_argument("--seconds", type=float, default=600.0)
    args = ap.parse_args()

    import frida

    out = open(args.out, "a", encoding="utf-8")

    def on_message(msg, data):
        if msg.get("type") == "send":
            out.write(json.dumps(msg["payload"], ensure_ascii=False) + "\n")
            out.flush()
            print(json.dumps(msg["payload"], ensure_ascii=False)[:400], flush=True)

    target = int(args.process) if str(args.process).isdigit() else args.process
    try:
        session = frida.attach(target)
    except Exception as exc:
        print(f"attach failed: {exc}", file=sys.stderr)
        return 2
    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()
    print(f"tracing {args.process} for {args.seconds}s -> {args.out}", flush=True)
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            session.detach()
        except Exception:
            pass
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
