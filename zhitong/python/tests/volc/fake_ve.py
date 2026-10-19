"""测试用假 ``ve``：按 argv 回放夹具文件，并把每次调用追加到日志。

环境变量：``FAKE_VE_DIR``（夹具目录，日志也写在这里的 ``calls.jsonl``）。

夹具文件名：

- OpenAPI 调用 ``ve <service> <Action> ...`` → ``<service>.<Action>.json``；
- 透传 ``ve tosutil <verb> ...`` → ``tosutil.<verb>.txt``；
- 同一键的第 N 次调用（从 1 起）优先用 ``<键>.<N>.<扩展名>``，没有就用不带序号的文件；
- 失败夹具 ``<键>.fail.json``（或 ``<键>.<N>.fail.json``）：``{"exit": 1, "stderr": "..."}``。
"""
import json
import os
import sys
from pathlib import Path


def main(argv):
    d = Path(os.environ["FAKE_VE_DIR"])
    log = d / "calls.jsonl"
    service, action = argv[0], argv[1] if len(argv) > 1 else ""
    if service == "tosutil":
        key, ext = f"tosutil.{action}", "txt"
    else:
        key, ext = f"{service}.{action}", "json"
    n = 1
    if log.exists():
        n += sum(1 for line in log.read_text(encoding="utf-8").splitlines() if json.loads(line)["key"] == key)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"key": key, "n": n, "argv": argv}, ensure_ascii=False) + "\n")
    for stem in (f"{key}.{n}", key):
        fail = d / f"{stem}.fail.json"
        if fail.exists():
            spec = json.loads(fail.read_text(encoding="utf-8"))
            sys.stderr.write(spec.get("stderr", ""))
            return spec.get("exit", 1)
        body = d / f"{stem}.{ext}"
        if body.exists():
            sys.stdout.buffer.write(body.read_bytes())
            return 0
    sys.stderr.write(f"fake ve: no fixture for {key} call {n}\n")
    return 9


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
