"""测试用假 ``ssh``：记录 argv，按环境变量回放输出。

环境变量：``FAKE_SSH_LOG``（日志文件）、``FAKE_SSH_STDOUT``、``FAKE_SSH_STDERR``、``FAKE_SSH_EXIT``、``FAKE_SSH_SLEEP``。
"""
import json
import os
import sys
import time


def main(argv):
    with open(os.environ["FAKE_SSH_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(argv, ensure_ascii=False) + "\n")
    time.sleep(float(os.environ.get("FAKE_SSH_SLEEP", "0")))
    sys.stdout.buffer.write(os.environ.get("FAKE_SSH_STDOUT", "").encode("utf-8"))
    sys.stderr.buffer.write(os.environ.get("FAKE_SSH_STDERR", "").encode("utf-8"))
    return int(os.environ.get("FAKE_SSH_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
