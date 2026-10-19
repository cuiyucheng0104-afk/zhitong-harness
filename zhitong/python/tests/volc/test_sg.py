"""安全组：规则查询、增删闸、白名单同步（先加后撤、只撤自己标记的规则）。"""
from __future__ import annotations

import io

import pytest

from tests.volc.helpers import FakeVe
from zt.common.errors import ZtError
from zt.volc import sg
from zt.volc.ve import Ve

SG = "sg-aaaaaaaa01"
NEW_IP = "120.55.10.20"


def setup(tmp_path):
    fake = FakeVe(tmp_path)
    fake.copy("vpc.DescribeSecurityGroupAttributes", "vpc.DescribeSecurityGroupAttributes.json")
    fake.copy("vpc.AuthorizeSecurityGroupIngress", "vpc.AuthorizeSecurityGroupIngress.json")
    fake.copy("vpc.RevokeSecurityGroupIngress", "vpc.RevokeSecurityGroupIngress.json")
    return fake, Ve(fake.settings())


def arg(argv, name):
    return argv[argv.index(name) + 1]


def test_show_filters_direction(tmp_path):
    fake, ve = setup(tmp_path)
    env = sg.show_envelope(ve, SG, direction="ingress")
    assert env.data["name"] == "zt-prod-sg" and env.data["rule_count"] == 3
    assert {r["direction"] for r in env.data["rules"]} == {"ingress"}
    assert sg.show_envelope(ve, SG, direction=None).data["rule_count"] == 4


def test_show_unknown_group_is_an_error(tmp_path):
    fake, ve = setup(tmp_path)
    fake.fixture("vpc.DescribeSecurityGroupAttributes", {"ResponseMetadata": {}, "Result": {}})
    with pytest.raises(ZtError) as e:
        sg.show_envelope(ve, SG, direction=None)
    assert e.value.code == "sg_not_found"


def authorize(ve, **over):
    kw = dict(protocol="tcp", port_start=8080, port_end=8080, cidr_ip="120.55.10.50/32", description="tmp debug",
              policy=None, priority=None, yes=True, dry_run=False)
    return sg.authorize_envelope(ve, SG, **{**kw, **over})


def test_authorize_requires_yes_and_describes_impact(tmp_path):
    fake, ve = setup(tmp_path)
    with pytest.raises(ZtError) as e:
        authorize(ve, yes=False)
    assert e.value.code == "confirmation_required" and "120.55.10.50/32" in e.value.message
    assert "vpc.AuthorizeSecurityGroupIngress" not in fake.keys()


def test_authorize_dry_run_and_apply(tmp_path):
    fake, ve = setup(tmp_path)
    plan = authorize(ve, yes=False, dry_run=True)
    assert plan.data["dry_run"] is True and "vpc.AuthorizeSecurityGroupIngress" not in fake.keys()
    env = authorize(ve, policy="accept", priority=5)
    assert env.data["changed"] is True
    (call,) = fake.calls("vpc.AuthorizeSecurityGroupIngress")
    assert arg(call, "--CidrIp") == "120.55.10.50/32" and arg(call, "--PortStart") == "8080"
    assert arg(call, "--Description") == "tmp debug" and arg(call, "--Policy") == "accept" and arg(call, "--Priority") == "5"
    assert call[-1] == "--yes"


def test_authorize_existing_rule_is_a_noop_even_without_yes(tmp_path):
    fake, ve = setup(tmp_path)
    env = authorize(ve, port_start=443, port_end=443, cidr_ip="0.0.0.0/0", yes=False)
    assert env.data == {"changed": False, "reason": "rule_already_present", "rule": env.data["rule"]}
    assert "vpc.AuthorizeSecurityGroupIngress" not in fake.keys()


def revoke(ve, **over):
    kw = dict(protocol="tcp", port_start=22, port_end=22, cidr_ip="120.55.10.9/32", yes=True, dry_run=False)
    return sg.revoke_envelope(ve, SG, **{**kw, **over})


def test_revoke_requires_existing_exact_rule(tmp_path):
    fake, ve = setup(tmp_path)
    with pytest.raises(ZtError) as e:
        revoke(ve, cidr_ip="120.55.10.250/32")
    assert e.value.code == "rule_not_found"
    with pytest.raises(ZtError) as e:
        revoke(ve, port_end=23)
    assert e.value.code == "rule_not_found"
    assert "vpc.RevokeSecurityGroupIngress" not in fake.keys()


def test_revoke_needs_yes_then_sends_found_rule_fields(tmp_path):
    fake, ve = setup(tmp_path)
    with pytest.raises(ZtError) as e:
        revoke(ve, yes=False)
    assert e.value.code == "confirmation_required" and "zt-ssh-sync" in e.value.message
    assert "vpc.RevokeSecurityGroupIngress" not in fake.keys()
    env = revoke(ve)
    assert env.data["changed"] is True
    (call,) = fake.calls("vpc.RevokeSecurityGroupIngress")
    assert arg(call, "--Policy") == "accept" and arg(call, "--Priority") == "1" and call[-1] == "--yes"


def sync(ve, **over):
    kw = dict(ip=NEW_IP, ports=[22], protocol="tcp", marker="zt-ssh-sync", label=None, yes=True, dry_run=False)
    return sg.sync_ip_envelope(ve, SG, **{**kw, **over})


def test_sync_dry_run_plans_add_then_revoke_of_own_marker_only(tmp_path):
    fake, ve = setup(tmp_path)
    env = sync(ve, yes=False, dry_run=True)
    d = env.data
    assert d["to_add_ports"] == [22] and d["to_revoke"] == [{"cidr": "120.55.10.9/32", "port": 22}]
    assert [c[2] for c in d["commands"]] == ["AuthorizeSecurityGroupIngress", "RevokeSecurityGroupIngress"]
    assert fake.keys() == ["vpc.DescribeSecurityGroupAttributes"], "dry-run 只读"


def test_sync_requires_yes_when_changes_needed(tmp_path):
    fake, ve = setup(tmp_path)
    with pytest.raises(ZtError) as e:
        sync(ve, yes=False)
    assert e.value.code == "confirmation_required" and NEW_IP in e.value.message
    assert fake.keys() == ["vpc.DescribeSecurityGroupAttributes"]


def test_sync_adds_before_revoking_and_leaves_other_labels_alone(tmp_path):
    fake, ve = setup(tmp_path)
    env = sync(ve)
    assert env.status.value == "ok" and env.data["added_ports"] == [22]
    assert env.data["revoked"] == [{"cidr": "120.55.10.9/32", "port": 22}]
    assert fake.keys() == ["vpc.DescribeSecurityGroupAttributes", "vpc.AuthorizeSecurityGroupIngress", "vpc.RevokeSecurityGroupIngress"]
    add = fake.calls("vpc.AuthorizeSecurityGroupIngress")[0]
    assert arg(add, "--CidrIp") == f"{NEW_IP}/32" and arg(add, "--Description") == "zt-ssh-sync" and add[-1] == "--yes"
    (rev,) = fake.calls("vpc.RevokeSecurityGroupIngress")
    assert arg(rev, "--CidrIp") == "120.55.10.9/32", "alice 的 120.55.10.31 与 web 规则没被动"


def test_sync_label_scopes_stale_revocation(tmp_path):
    fake, ve = setup(tmp_path)
    env = sync(ve, label="alice")
    assert env.data["description"] == "zt-ssh-sync:alice"
    assert env.data["revoked"] == [{"cidr": "120.55.10.31/32", "port": 22}]


def test_sync_already_in_sync_needs_no_yes_and_no_writes(tmp_path):
    fake, ve = setup(tmp_path)
    env = sync(ve, ip="120.55.10.9", yes=False)
    assert env.data["reason"] == "already_in_sync" and env.data["changed"] is False
    assert fake.keys() == ["vpc.DescribeSecurityGroupAttributes"]


def test_sync_multiple_ports_adds_only_missing(tmp_path):
    fake, ve = setup(tmp_path)
    env = sync(ve, ip="120.55.10.9", ports=[22, 2222])
    assert env.data["added_ports"] == [2222] and env.data["revoked"] == []


def test_sync_authorize_failure_revokes_nothing(tmp_path):
    fake, ve = setup(tmp_path)
    fake.fail("vpc.AuthorizeSecurityGroupIngress", stderr="boom")
    with pytest.raises(ZtError) as e:
        sync(ve)
    assert e.value.code == "ve_failed" and "未撤销任何旧规则" in e.value.message
    assert "vpc.RevokeSecurityGroupIngress" not in fake.keys()


def test_sync_revoke_failure_is_partial_with_error_warning(tmp_path):
    fake, ve = setup(tmp_path)
    fake.fail("vpc.RevokeSecurityGroupIngress", stderr="boom")
    env = sync(ve)
    assert env.status.value == "partial" and env.data["added_ports"] == [22]
    assert env.warning_items[0].code == "stale_rule_revoke_failed" and env.warning_items[0].level.value == "error"
    assert env.coverage == {"revoke_planned": 1, "revoke_done": 0}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_detect_public_ip():
    seen = {}

    def opener(url, timeout):
        seen["url"], seen["timeout"] = url, timeout
        return FakeResponse(b" 120.55.10.20\n")

    assert sg.detect_public_ip("https://ip.example.test/", timeout=3, opener=opener) == "120.55.10.20"
    assert seen == {"url": "https://ip.example.test/", "timeout": 3}
    for body, code in [(b"10.0.0.8", "ip_not_public"), (b"<html>", "invalid_ip")]:
        with pytest.raises(ZtError) as e:
            sg.detect_public_ip("https://ip.example.test/", opener=lambda u, timeout, b=body: FakeResponse(b))
        assert e.value.code == code
    with pytest.raises(ZtError) as e:
        sg.detect_public_ip("file:///etc/passwd")
    assert e.value.code == "invalid_ip_url"

    def down(url, timeout):
        raise OSError("down")

    with pytest.raises(ZtError) as e:
        sg.detect_public_ip("https://ip.example.test/", opener=down)
    assert e.value.code == "public_ip_unreachable"
