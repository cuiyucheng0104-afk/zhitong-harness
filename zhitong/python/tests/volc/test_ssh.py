"""SSH：别名闸、只读分级、确认闸、连接失败与远端失败的区分、输出上限。"""
from __future__ import annotations

import json

import pytest

from tests.volc.helpers import HERE, make_wrapper
from zt.common.errors import ZtError
from zt.volc import ssh
from zt.volc.config import VolcSettings


@pytest.fixture
def fake(tmp_path, monkeypatch):
    log = tmp_path / "ssh calls.jsonl"
    wrapper = make_wrapper(tmp_path / "fake-ssh", HERE / "fake_ssh.py", {"FAKE_SSH_LOG": str(log)})
    settings = VolcSettings(ssh_bin=str(wrapper), ssh_aliases=("zt-prod", "zt-jump"))

    class Fake:
        def __init__(self):
            self.settings = settings

        def calls(self):
            return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

        def reply(self, *, stdout="", stderr="", code=0, sleep=0):
            monkeypatch.setenv("FAKE_SSH_STDOUT", stdout)
            monkeypatch.setenv("FAKE_SSH_STDERR", stderr)
            monkeypatch.setenv("FAKE_SSH_EXIT", str(code))
            monkeypatch.setenv("FAKE_SSH_SLEEP", str(sleep))

    return Fake()


@pytest.mark.parametrize("command,readonly", [
    ("df -h", True),
    ("ls -la /work/project | head -20", True),
    ("docker ps --format '{{.Names}}'", True),
    ("docker logs --tail 50 api", True),
    ("systemctl status nginx", True),
    ("tail -n 100 /var/log/syslog && uptime", True),
    ("journalctl -u api -n 50", True),
    ("grep -c error /var/log/api.log", True),
    ("docker stop api", False),
    ("docker rm -f api", False),
    ("systemctl restart nginx", False),
    ("rm -rf /tmp/x", False),
    ("ls > /tmp/out", False),
    ("echo $(whoami)", False),
    ("echo `id`", False),
    ("ls & sleep 100", False),
    ("cat a\nrm b", False),
    ("sort -o /etc/passwd /tmp/x", False),
    ("date -s '2020-01-01'", False),
    ("journalctl --vacuum-size=1M", False),
    ("sudo ls", False),
    ("echo 'unterminated", False),
    ("ls | ", False),
])
def test_classify(command, readonly):
    assert ssh.classify(command)[0] is readonly


@pytest.mark.parametrize("command", ["tail -f /var/log/syslog", "journalctl -f", "docker logs -f api", "tail --follow x"])
def test_follow_is_refused(command):
    with pytest.raises(ZtError) as e:
        ssh.classify(command)
    assert e.value.code == "follow_not_supported"


def test_empty_command():
    with pytest.raises(ZtError) as e:
        ssh.classify("   ")
    assert e.value.code == "empty_command"


def test_readonly_command_runs_without_yes_with_safe_argv(fake):
    fake.reply(stdout="Filesystem  Size\n")
    env = ssh.exec_envelope(fake.settings, "zt-prod", "df -h", yes=False, dry_run=False)
    assert env.data["stdout"] == "Filesystem  Size\n" and env.data["exit_code"] == 0 and env.data["readonly"] is True
    (argv,) = fake.calls()
    assert argv == ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", "zt-prod", "df -h"]


def test_non_readonly_needs_yes_and_does_not_connect_without_it(fake):
    with pytest.raises(ZtError) as e:
        ssh.exec_envelope(fake.settings, "zt-prod", "docker restart api", yes=False, dry_run=False)
    assert e.value.code == "confirmation_required" and "zt-prod" in e.value.message
    assert fake.calls() == []
    env = ssh.exec_envelope(fake.settings, "zt-prod", "docker restart api", yes=True, dry_run=False)
    assert env.data["readonly"] is False and len(fake.calls()) == 1


def test_dry_run_never_connects(fake):
    env = ssh.exec_envelope(fake.settings, "zt-prod", "rm -rf /x", yes=False, dry_run=True)
    assert env.data["dry_run"] is True and env.data["readonly"] is False and fake.calls() == []


def test_unknown_or_option_like_alias_is_refused(fake):
    with pytest.raises(ZtError) as e:
        ssh.exec_envelope(fake.settings, "other", "df", yes=False, dry_run=False)
    assert e.value.code == "ssh_host_unknown" and "zt-prod" in e.value.hint
    with pytest.raises(ZtError) as e:
        ssh.exec_envelope(fake.settings, "-oProxyCommand=evil", "df", yes=True, dry_run=False)
    assert e.value.code == "invalid_ssh_alias"
    assert fake.calls() == []


def test_connection_failure_vs_remote_failure(fake):
    fake.reply(stderr="Permission denied (publickey).", code=255)
    with pytest.raises(ZtError) as e:
        ssh.exec_envelope(fake.settings, "zt-prod", "df", yes=False, dry_run=False)
    assert e.value.code == "ssh_connect_failed" and "Permission denied" in e.value.message
    fake.reply(stderr="ls: cannot access", code=2)
    env = ssh.exec_envelope(fake.settings, "zt-prod", "ls /nope", yes=False, dry_run=False)
    assert env.data["exit_code"] == 2 and [w.code for w in env.warning_items] == ["remote_nonzero_exit"]


def test_output_is_capped_and_redacted(fake):
    fake.reply(stdout="x" * 5000, stderr="token secret-key=HUNTER2")
    env = ssh.exec_envelope(fake.settings, "zt-prod", "cat /var/log/x", yes=False, dry_run=False, max_output_bytes=1000)
    assert len(env.data["stdout"]) == 1000 and env.data["stdout_truncated"] is True
    assert "HUNTER2" not in env.data["stderr"]
    assert "output_truncated" in [w.code for w in env.warning_items]


def test_timeout_and_missing_binary(fake):
    fake.reply(sleep=3)
    with pytest.raises(ZtError) as e:
        ssh.exec_envelope(fake.settings, "zt-prod", "df", yes=False, dry_run=False, timeout=0.3)
    assert e.value.code == "ssh_timeout"
    missing = VolcSettings(ssh_bin="no-such-ssh-binary", ssh_aliases=("zt-prod",))
    with pytest.raises(ZtError) as e:
        ssh.exec_envelope(missing, "zt-prod", "df", yes=False, dry_run=False)
    assert e.value.code == "ssh_not_found"


def test_hosts_listing():
    assert ssh.hosts_envelope(VolcSettings(ssh_aliases=("a", "b"))).data == {"hosts": ["a", "b"], "total": 2}
    with pytest.raises(ZtError) as e:
        ssh.hosts_envelope(VolcSettings())
    assert e.value.code == "ssh_no_hosts"
