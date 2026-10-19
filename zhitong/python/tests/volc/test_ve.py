"""ve 封装：argv 形态、响应解析、失败映射与脱敏。"""
from __future__ import annotations

import subprocess

import pytest

from tests.volc.helpers import FakeVe
from zt.common.errors import ZtError
from zt.volc.config import VolcSettings
from zt.volc.ve import Ve, flatten_params, redact


def test_flatten_params_uses_space_separated_one_based_arrays():
    assert flatten_params({"InstanceIds": ["i-a", "i-b"], "MaxResults": 100, "ForceStop": True, "Name": "x y"}) == [
        "--InstanceIds.1", "i-a", "--InstanceIds.2", "i-b", "--MaxResults", "100", "--ForceStop", "true", "--Name", "x y"]


def test_argv_has_profile_region_json_output_and_optional_yes(tmp_path):
    fake = FakeVe(tmp_path)
    ve = Ve(fake.settings())
    argv = ve.argv("ecs", "StopInstance", {"InstanceId": "i-x"})
    assert argv[1:] == ["ecs", "StopInstance", "--profile", "test-profile", "--region", "cn-beijing",
                        "--InstanceId", "i-x", "--output", "json"]
    assert ve.argv("ecs", "StopInstance", {"InstanceId": "i-x"}, confirm=True)[-1] == "--yes"
    no_region = Ve(fake.settings(region=None)).argv("sts", "GetCallerIdentity", {})
    assert "--region" not in no_region


def test_call_returns_result_and_passes_args(tmp_path):
    fake = FakeVe(tmp_path)
    fake.copy("sts.GetCallerIdentity", "sts.GetCallerIdentity.json")
    result = Ve(fake.settings()).call("sts", "GetCallerIdentity")
    assert result["AccountId"] == "2100000001"
    assert fake.calls("sts.GetCallerIdentity")[0][:2] == ["sts", "GetCallerIdentity"]


def test_business_error_in_response_metadata(tmp_path):
    fake = FakeVe(tmp_path)
    fake.fixture("ecs.DescribeInstances", {"ResponseMetadata": {"Error": {"Code": "AccessDenied", "Message": "no permission, secret-key=ABCDEF"}}})
    with pytest.raises(ZtError) as e:
        Ve(fake.settings()).call("ecs", "DescribeInstances")
    assert e.value.code == "ve_api_error"
    assert "AccessDenied" in e.value.message and "ABCDEF" not in e.value.message


def test_nonzero_exit_is_redacted_and_bounded(tmp_path):
    fake = FakeVe(tmp_path)
    fake.fail("ecs.DescribeInstances", exit_code=3, stderr="login failed access-key AKLTabcdefghijklmnop12 " + "x" * 2000)
    with pytest.raises(ZtError) as e:
        Ve(fake.settings()).call("ecs", "DescribeInstances")
    assert e.value.code == "ve_failed" and "退出码 3" in e.value.message
    assert "AKLTabcdefghijklmnop12" not in e.value.message and len(e.value.message) < 800


def test_non_json_stdout_is_an_error_not_empty_success(tmp_path):
    fake = FakeVe(tmp_path)
    (fake.dir / "ecs.DescribeInstances.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ZtError) as e:
        Ve(fake.settings()).call("ecs", "DescribeInstances")
    assert e.value.code == "ve_bad_output"
    (fake.dir / "ecs.DescribeInstances.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(ZtError) as e:
        Ve(fake.settings()).call("ecs", "DescribeInstances")
    assert e.value.code == "ve_bad_output"


def test_missing_binary_and_timeout():
    with pytest.raises(ZtError) as e:
        Ve(VolcSettings(ve_bin="definitely-not-installed-ve", profile="p")).call("sts", "GetCallerIdentity")
    assert e.value.code == "ve_not_found"

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    with pytest.raises(ZtError) as e:
        Ve(VolcSettings(profile="p"), timeout=1, runner=slow).call("sts", "GetCallerIdentity")
    assert e.value.code == "ve_timeout"


def test_profile_required_before_any_subprocess():
    def boom(*a, **k):
        raise AssertionError("must not spawn")

    with pytest.raises(ZtError) as e:
        Ve(VolcSettings(), runner=boom).call("sts", "GetCallerIdentity")
    assert e.value.code == "volc_profile_missing"


def test_redact_patterns():
    assert "SECRET123" not in redact("secret_key: SECRET123")
    assert "AKLTabcdefghijkl1234" not in redact("id AKLTabcdefghijkl1234 end")
    assert redact("nothing here") == "nothing here"
