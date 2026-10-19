"""ECS 查询与启停：状态闸、确认闸、dry-run 不写、轮询。"""
from __future__ import annotations

import copy
import json

import pytest

from tests.volc.helpers import FIXTURES, FakeVe
from zt.common.errors import ZtError
from zt.volc import ecs
from zt.volc.ve import Ve

RUNNING = "i-yeaaaaaaaa01"
STOPPED = "i-yebbbbbbbb02"


def base_fixtures(fake: FakeVe) -> Ve:
    fake.copy("ecs.DescribeInstances", "ecs.DescribeInstances.json")
    fake.copy("ecs.StopInstance", "ecs.StopInstance.json")
    for action in ("StartInstance", "RebootInstance"):
        fake.fixture(f"ecs.{action}", {"ResponseMetadata": {}, "Result": {}})
    return Ve(fake.settings())


def only(instance_id: str, status: str) -> dict:
    doc = json.loads((FIXTURES / "ecs.DescribeInstances.json").read_text(encoding="utf-8"))
    inst = [i for i in doc["Result"]["Instances"] if i["InstanceId"] == instance_id]
    inst = copy.deepcopy(inst)
    inst[0]["Status"] = status
    doc["Result"]["Instances"] = inst
    return doc


def writes(fake: FakeVe) -> list[str]:
    return [k for k in fake.keys() if k.split(".")[1] in ("StartInstance", "StopInstance", "RebootInstance")]


def test_list_summarizes_instances(tmp_path):
    ve = base_fixtures(FakeVe(tmp_path))
    env = ecs.list_envelope(ve, status=None, name=None)
    assert env.status.value == "ok" and env.data["total"] == 2
    first = env.data["instances"][0]
    assert first == {"instance_id": RUNNING, "name": "zt-prod", "status": "RUNNING", "zone_id": "cn-beijing-a",
                     "private_ip": "10.0.0.8", "public_ip": "120.55.10.77", "security_group_ids": ["sg-aaaaaaaa01"]}
    second = env.data["instances"][1]
    assert second["public_ip"] is None and second["security_group_ids"] == ["sg-aaaaaaaa01", "sg-bbbbbbbb02"]


def test_list_passes_filters_and_paginates(tmp_path):
    fake = FakeVe(tmp_path)
    page1 = only(RUNNING, "RUNNING")
    page1["Result"]["NextToken"] = "tok2"
    fake.fixture("ecs.DescribeInstances", page1, n=1)
    fake.fixture("ecs.DescribeInstances", only(STOPPED, "RUNNING"), n=2)
    items, truncated = ecs.list_instances(Ve(fake.settings()), status="running", name="zt-")
    assert [i["instance_id"] for i in items] == [RUNNING, STOPPED] and not truncated
    first, second = fake.calls("ecs.DescribeInstances")
    assert "--Status" in first and first[first.index("--Status") + 1] == "RUNNING"
    assert first[first.index("--InstanceName") + 1] == "zt-" and "--NextToken" not in first
    assert second[second.index("--NextToken") + 1] == "tok2"


def test_list_truncation_is_partial_with_warning(tmp_path, monkeypatch):
    fake = FakeVe(tmp_path)
    page = only(RUNNING, "RUNNING")
    page["Result"]["NextToken"] = "more"
    fake.fixture("ecs.DescribeInstances", page)
    monkeypatch.setattr(ecs, "MAX_PAGES", 3)
    env = ecs.list_envelope(Ve(fake.settings()), status=None, name=None)
    assert env.status.value == "partial" and env.data["total"] == 3
    assert any(w.code == "listing_truncated" for w in env.warning_items)


def test_status_and_not_found(tmp_path):
    ve = base_fixtures(FakeVe(tmp_path))
    assert ecs.status_envelope(ve, RUNNING).data["instance"]["name"] == "zt-prod"
    with pytest.raises(ZtError) as e:
        ecs.status_envelope(ve, "i-yezzzzzzzz99")
    assert e.value.code == "instance_not_found"


def test_stop_requires_yes_and_makes_no_write_call_without_it(tmp_path):
    fake = FakeVe(tmp_path)
    ve = base_fixtures(fake)
    with pytest.raises(ZtError) as e:
        ecs.power_envelope(ve, "stop", RUNNING, yes=False, dry_run=False)
    assert e.value.code == "confirmation_required" and "zt-prod" in e.value.message
    assert writes(fake) == []


def test_dry_run_returns_plan_without_writing(tmp_path):
    fake = FakeVe(tmp_path)
    env = ecs.power_envelope(base_fixtures(fake), "reboot", RUNNING, yes=False, dry_run=True, force_stop=True)
    assert env.data["dry_run"] is True and env.data["needs_yes"] is True
    cmd = env.data["command"]
    assert cmd[1:3] == ["ecs", "RebootInstance"] and "--yes" not in cmd and cmd[cmd.index("--ForceStop") + 1] == "true"
    assert writes(fake) == []


def test_stop_with_yes_forwards_yes_to_ve(tmp_path):
    fake = FakeVe(tmp_path)
    env = ecs.power_envelope(base_fixtures(fake), "stop", RUNNING, yes=True, dry_run=False)
    assert env.data["changed"] is True and env.status.value == "ok"
    (call,) = fake.calls("ecs.StopInstance")
    assert call[call.index("--InstanceId") + 1] == RUNNING and call[-1] == "--yes"


def test_start_needs_no_yes_and_is_not_given_one(tmp_path):
    fake = FakeVe(tmp_path)
    env = ecs.power_envelope(base_fixtures(fake), "start", STOPPED, yes=False, dry_run=False)
    assert env.data["changed"] is True
    (call,) = fake.calls("ecs.StartInstance")
    assert "--yes" not in call


def test_already_in_target_state_makes_no_write_call(tmp_path):
    fake = FakeVe(tmp_path)
    ve = base_fixtures(fake)
    assert ecs.power_envelope(ve, "start", RUNNING, yes=False, dry_run=False).data["reason"] == "already_running"
    assert ecs.power_envelope(ve, "stop", STOPPED, yes=False, dry_run=False).data["changed"] is False
    assert writes(fake) == []


def test_state_conflicts(tmp_path):
    fake = FakeVe(tmp_path)
    ve = base_fixtures(fake)
    with pytest.raises(ZtError) as e:
        ecs.power_envelope(ve, "reboot", STOPPED, yes=True, dry_run=False)
    assert e.value.code == "instance_state_conflict"
    fake.fixture("ecs.DescribeInstances", only(RUNNING, "STOPPING"))
    with pytest.raises(ZtError) as e:
        ecs.power_envelope(ve, "stop", RUNNING, yes=True, dry_run=False)
    assert e.value.code == "instance_state_conflict" and writes(fake) == []
    with pytest.raises(ZtError) as e:
        ecs.power_envelope(ve, "start", STOPPED, yes=False, dry_run=False, force_stop=True)
    assert e.value.code == "invalid_option"


def test_wait_polls_until_target(tmp_path):
    fake = FakeVe(tmp_path)
    ve = base_fixtures(fake)
    fake.fixture("ecs.DescribeInstances", only(STOPPED, "STOPPED"), n=1)
    fake.fixture("ecs.DescribeInstances", only(STOPPED, "STARTING"), n=2)
    fake.fixture("ecs.DescribeInstances", only(STOPPED, "RUNNING"), n=3)
    sleeps: list[float] = []
    env = ecs.power_envelope(ve, "start", STOPPED, yes=False, dry_run=False, wait_seconds=100, poll_interval=7,
                             sleep=sleeps.append, clock=lambda: 0.0)
    assert env.status.value == "ok" and env.data["waited"] is True and env.data["instance"]["status"] == "RUNNING"
    assert sleeps == [7]


def test_wait_timeout_is_partial_not_ok(tmp_path):
    fake = FakeVe(tmp_path)
    ve = base_fixtures(fake)
    fake.fixture("ecs.DescribeInstances", only(RUNNING, "RUNNING"), n=1)
    fake.fixture("ecs.DescribeInstances", only(RUNNING, "STOPPING"))
    ticks = iter([0.0, 5.0, 11.0, 12.0])
    env = ecs.power_envelope(ve, "stop", RUNNING, yes=True, dry_run=False, wait_seconds=10, poll_interval=0,
                             sleep=lambda s: None, clock=lambda: next(ticks))
    assert env.status.value == "partial"
    assert env.coverage["last_status"] == "STOPPING" and env.warning_items[0].code == "wait_timeout"
