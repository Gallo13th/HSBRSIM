"""HSbg BepInEx bridge TCP JSON client（127.0.0.1:17890）。

只做进程内公开 API 的动作注入；不点击 UI、不写内存。
协议一行一个 JSON：
  {"cmd":"ping"} / {"cmd":"state"}
  {"cmd":"option","id":..,"main":..,"target":..,"sub":..,"pos":..}
  {"cmd":"choices","id":..,"picks":[..]} / {"cmd":"select","entity":..}
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


class BridgeError(RuntimeError):
    pass


@dataclass
class BridgeClient:
    host: str = "127.0.0.1"
    port: int = 17890
    timeout: float = 3.0
    connect_timeout: float = 2.0

    def __post_init__(self) -> None:
        self._sock: Optional[socket.socket] = None
        self._reader = None
        self._writer = None

    # ── 连接 ──
    def connect(self) -> bool:
        if self._sock is not None:
            return True
        try:
            sock = socket.create_connection((self.host, int(self.port)),
                                            timeout=self.connect_timeout)
            sock.settimeout(float(self.timeout))
            self._sock = sock
            self._reader = sock.makefile("r", encoding="utf-8", newline="\n")
            self._writer = sock.makefile("w", encoding="utf-8", newline="\n")
            return True
        except OSError:
            self.close()
            return False

    def close(self) -> None:
        for f in (self._reader, self._writer):
            try:
                if f is not None:
                    f.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:  # noqa: BLE001
            pass
        self._sock = None
        self._reader = None
        self._writer = None

    def request(self, cmd: str, **kwargs: Any) -> Dict[str, Any]:
        last: Optional[Exception] = None
        for attempt in range(2):
            if not self.connect():
                last = BridgeError("bridge connect failed")
                time.sleep(0.2)
                continue
            try:
                payload = {"cmd": str(cmd)}
                payload.update({k: v for k, v in kwargs.items() if v is not None})
                assert self._writer is not None and self._reader is not None
                self._writer.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._writer.flush()
                line = self._reader.readline()
                if not line:
                    raise BridgeError("bridge closed connection")
                out = json.loads(line)
                if not isinstance(out, dict):
                    raise BridgeError("bridge non-object response")
                return out
            except Exception as exc:  # noqa: BLE001
                last = exc
                self.close()
                time.sleep(0.2)
        raise BridgeError(f"bridge request {cmd!r} failed: {last}")

    # ── 命令 ──
    def ping(self) -> bool:
        try:
            r = self.request("ping")
            return bool(r.get("ok") and r.get("pong"))
        except BridgeError:
            return False

    def state(self) -> Dict[str, Any]:
        return self.request("state")

    def option(self, *, options_id: int, main: int, target: int = 0,
               sub: int = -1, pos: int = 0) -> Dict[str, Any]:
        return self.request("option", id=int(options_id), main=int(main),
                            target=int(target), sub=int(sub), pos=int(pos))

    def choices(self, *, choice_id: int, picks: List[int]) -> Dict[str, Any]:
        return self.request("choices", id=int(choice_id),
                            picks=[int(x) for x in picks])

    def select(self, *, entity: int) -> Dict[str, Any]:
        return self.request("select", entity=int(entity))


__all__ = ["BridgeClient", "BridgeError"]
