"""python -m zt.volc.cli 端到端：stdout 单个 JSON、退出码约定、密钥不出现在任何输出里。"""
from __future__ import annotations

import json

from tests.volc.helpers import FakeVe, run_volc_cli

SECRET = "SENTINEL-SECRET-VALUE"
RUNNING = "i-yeaaaaaaaa01"


def make_env(tmp_path):
    fake = FakeVe(tmp_path)
    for key in ("ecs.DescribeInstances", "ecs.StopInstance", "sts.GetCallerIdentity", "vpc.DescribeSecurityGroupAttributes",
                "vpc.AuthorizeSecurityGroupIngress", "vpc.RevokeSecurityGroupIngress"):
        fake.copy(key, f"{key}.json")
    cfg_dir = tmp_path / "配置 包"
    cfg_dir.mkdir()
    cfg = cfg_dir / "zhitong.config.json"
    cfg.write_text(json.dumps({
        "format": "zhitong.config/1",
        "tos": {"accessKeyId": "AKLTSENTINEL", "secretAccessKey": SECRET},
        "ssh": {"hosts": [{"alias": "zt-prod", "host": "10.0.0.8", "user": "root", "privateKey": SECRET}]},
        "volc": {"profile": "test-profile", "region": "cn-beijing"},
    }, ensure_ascii=False), encoding="utf-8")
    env = {"ZT_VE_BIN": str(fake.bin), "ZT_VOLC_CONFIG": str(cfg), "ZT_SSH_CONFIG": str(tmp_path / "no-ssh-config")}
    return fake, env


def test_whoami_and_list_read_names_from_config_file(tmp_path):
    fake, env = make_env(tmp_path)
    code, out, _ = run_volc_cli("whoami", env=env)
    assert code == 0 and out["status"] == "ok" and out["needs_manual"] is True
    assert out["data"]["profile"] == "test-profile" and out["data"]["identity"]["AccountId"] == "2100000001"
    code, out, _ = run_volc_cli("ecs-list", "--status", "RUNNING", env=env)
    assert code == 0 and out["data"]["total"] == 2
    argv = fake.calls("ecs.DescribeInstances")[0]
    assert argv[argv.index("--profile") + 1] == "test-profile" and argv[argv.index("--region") + 1] == "cn-beijing"


def test_missing_profile_fails_with_error_json(tmp_path):
    fake, env = make_env(tmp_path)
    env = {**env, "ZT_VOLC_CONFIG": ""}
    code, out, _ = run_volc_cli("ecs-list", env={**env, "ZT_VOLC_PROFILE": ""})
    assert code == 2 and out["error"]["code"] == "volc_profile_missing" and fake.calls() == []


def test_confirmation_gate_round_trip(tmp_path):
    fake, env = make_env(tmp_path)
    code, out, _ = run_volc_cli("ecs-stop", "--instance-id", RUNNING, env=env)
    assert code == 2 and out["error"]["code"] == "confirmation_required" and "zt-prod" in out["error"]["message"]
    assert "ecs.StopInstance" not in fake.keys()
    code, plan, _ = run_volc_cli("ecs-stop", "--instance-id", RUNNING, "--dry-run", env=env)
    assert code == 0 and plan["data"]["dry_run"] is True and "ecs.StopInstance" not in fake.keys()
    code, done, _ = run_volc_cli("ecs-stop", "--instance-id", RUNNING, "--yes", env=env)
    assert code == 0 and done["data"]["changed"] is True
    assert fake.calls("ecs.StopInstance")[0][-1] == "--yes"


def test_invalid_arguments_never_reach_ve(tmp_path):
    fake, env = make_env(tmp_path)
    cases = [
        (["ecs-status", "--instance-id=--evil"], "invalid_instance_id"),
        (["ecs-status", "--instance-id", "--evil"], "usage"),
        (["sg-show", "--sg-id", "bad"], "invalid_sg_id"),
        (["sg-authorize", "--sg-id", "sg-aaaaaaaa01", "--protocol", "tcp", "--port-start", "22", "--port-end", "22",
          "--cidr", "0.0.0.0/0", "--yes"], "world_open_refused"),
        (["sg-authorize", "--sg-id", "sg-aaaaaaaa01", "--protocol", "tcp", "--port-start", "0", "--port-end", "22",
          "--cidr", "120.55.10.1/32", "--yes"], "invalid_port"),
        (["sg-sync-ip", "--sg-id", "sg-aaaaaaaa01", "--ip", "192.168.1.9", "--yes"], "ip_not_public"),
        (["sg-sync-ip", "--sg-id", "sg-aaaaaaaa01", "--yes"], "public_ip_unknown"),
        (["tos-ls", "--bucket", "zt-company", "--prefix", "../x"], "invalid_prefix"),
        (["tos-stat", "--bucket", "Bad_Bucket"], "invalid_bucket"),
        (["ssh-exec", "--host", "nope", "--command", "df"], "ssh_host_unknown"),
        (["ecs-list", "--timeout", "0"], "invalid_timeout"),
        (["no-such-command"], "usage"),
    ]
    for args, code_expected in cases:
        code, out, _ = run_volc_cli(*args, env=env)
        assert code == 2 and out["error"]["code"] == code_expected, (args, out)
    assert fake.calls() == []


def test_sg_sync_ip_cli_dry_run_then_apply(tmp_path):
    fake, env = make_env(tmp_path)
    args = ["sg-sync-ip", "--sg-id", "sg-aaaaaaaa01", "--ip", "120.55.10.20"]
    code, plan, _ = run_volc_cli(*args, "--dry-run", env=env)
    assert code == 0 and plan["data"]["to_add_ports"] == [22] and "vpc.AuthorizeSecurityGroupIngress" not in fake.keys()
    code, out, _ = run_volc_cli(*args, env=env)
    assert code == 2 and out["error"]["code"] == "confirmation_required"
    code, done, _ = run_volc_cli(*args, "--yes", env=env)
    assert code == 0 and done["data"]["revoked"] == [{"cidr": "120.55.10.9/32", "port": 22}]


def test_ssh_hosts_and_exec_through_config_aliases(tmp_path):
    fake, env = make_env(tmp_path)
    code, out, _ = run_volc_cli("ssh-hosts", env=env)
    assert code == 0 and out["data"]["hosts"] == ["zt-prod"]
    code, out, _ = run_volc_cli("ssh-exec", "--host", "zt-prod", "--command", "rm -rf /x", "--dry-run", env=env)
    assert code == 0 and out["data"]["readonly"] is False
    code, out, _ = run_volc_cli("ssh-exec", "--host", "zt-prod", "--command", "rm -rf /x", env=env)
    assert code == 2 and out["error"]["code"] == "confirmation_required"


def test_out_file_and_no_secret_in_any_output(tmp_path):
    fake, env = make_env(tmp_path)
    out_dir = tmp_path / "工作" / "2026-10-19-运维"
    out_dir.mkdir(parents=True)
    texts = []
    for args in (["ecs-list"], ["ssh-hosts"], ["ssh-exec", "--host", "zt-prod", "--command", "rm x", "--dry-run"],
                 ["ecs-stop", "--instance-id", RUNNING], ["--help"]):
        code, out, err = run_volc_cli(*args, env=env) if args != ["--help"] else (0, {}, "")
        texts += [json.dumps(out, ensure_ascii=False), err]
    code, summary, _ = run_volc_cli("ecs-list", "--out", f"{out_dir}/", env=env)
    assert code == 0 and summary["out"].endswith("result.json")
    texts.append((out_dir / "result.json").read_text(encoding="utf-8"))
    for text in texts:
        assert SECRET not in text and "AKLTSENTINEL" not in text
