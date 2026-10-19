"""设置只读名称：配置文件里的密钥字段不进入设置；路径含空格与中文。"""
from __future__ import annotations

import json

import pytest

from zt.common.errors import ZtError
from zt.volc.config import ENV_CONFIG, ENV_PROFILE, ENV_REGION, ENV_SSH_CONFIG, load_settings

SECRET = "SENTINEL-SECRET-VALUE"


def write_config(path, **extra):
    doc = {
        "format": "zhitong.config/1",
        "tos": {"accessKeyId": "AKLTSENTINEL", "secretAccessKey": SECRET},
        "ssh": {"hosts": [{"alias": "zt-prod", "host": "10.0.0.8", "user": "root", "privateKey": SECRET},
                          {"alias": "-bad", "host": "h", "user": "u"}]},
        "volc": {"profile": "from-file", "region": "cn-shanghai"},
        **extra,
    }
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8-sig")
    return path


def test_precedence_cli_over_env_over_file(tmp_path):
    (tmp_path / "配置 目录").mkdir()
    cfg = write_config(tmp_path / "配置 目录" / "zhitong.config.json")
    s = load_settings(config=str(cfg), env={ENV_SSH_CONFIG: str(tmp_path / "none")})
    assert (s.profile, s.region) == ("from-file", "cn-shanghai")
    s = load_settings(config=str(cfg), env={ENV_PROFILE: "from-env", ENV_REGION: "cn-guangzhou", ENV_SSH_CONFIG: str(tmp_path / "none")})
    assert (s.profile, s.region) == ("from-env", "cn-guangzhou")
    s = load_settings(profile="from-cli", region="cn-beijing", config=str(cfg), env={ENV_PROFILE: "from-env", ENV_SSH_CONFIG: str(tmp_path / "none")})
    assert (s.profile, s.region) == ("from-cli", "cn-beijing")


def test_settings_never_hold_secret_values(tmp_path):
    cfg = write_config(tmp_path / "zhitong.config.json")
    s = load_settings(config=str(cfg), env={ENV_SSH_CONFIG: str(tmp_path / "none")})
    assert SECRET not in repr(s) and "AKLTSENTINEL" not in repr(s)
    assert s.ssh_aliases == ("zt-prod",), "不合法的别名被丢弃，host/privateKey 不读取"


def test_env_config_and_ssh_config_aliases_are_merged(tmp_path):
    cfg = write_config(tmp_path / "zhitong.config.json")
    ssh_cfg = tmp_path / "ssh_config"
    ssh_cfg.write_text("Host *\n  ServerAliveInterval 30\nHost zt-jump zt-prod\n  HostName x\nHost 10.*\nHost !bad\n# Host commented\n", encoding="utf-8")
    s = load_settings(env={ENV_CONFIG: str(cfg), ENV_SSH_CONFIG: str(ssh_cfg)})
    assert s.ssh_aliases == ("zt-prod", "zt-jump")


def test_missing_profile_is_reported_when_needed(tmp_path):
    s = load_settings(env={ENV_SSH_CONFIG: str(tmp_path / "none")})
    assert s.profile is None
    with pytest.raises(ZtError) as e:
        s.require_profile()
    assert e.value.code == "volc_profile_missing"


@pytest.mark.parametrize("kwargs,code", [
    ({"profile": "--bad"}, "invalid_profile"),
    ({"profile": "a b"}, "invalid_profile"),
    ({"region": "Beijing"}, "invalid_region"),
])
def test_invalid_names(tmp_path, kwargs, code):
    with pytest.raises(ZtError) as e:
        load_settings(env={ENV_SSH_CONFIG: str(tmp_path / "none")}, **kwargs)
    assert e.value.code == code


def test_config_errors(tmp_path):
    with pytest.raises(ZtError) as e:
        load_settings(config=str(tmp_path / "missing.json"), env={})
    assert e.value.code == "config_unreadable"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ZtError) as e:
        load_settings(config=str(bad), env={})
    assert e.value.code == "config_invalid"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ZtError) as e:
        load_settings(config=str(bad), env={})
    assert e.value.code == "config_invalid"
