"""参数校验：每个进入 ve/ssh argv 的值都有拒绝用例。"""
from __future__ import annotations

import pytest

from zt.common.errors import ZtError
from zt.volc import validate as v


def code(fn, *a, **k):
    with pytest.raises(ZtError) as e:
        fn(*a, **k)
    return e.value.code


def test_ids_and_names():
    assert v.instance_id("i-yeaaaaaaaa01") == "i-yeaaaaaaaa01"
    assert v.security_group_id("sg-aaaaaaaa01") == "sg-aaaaaaaa01"
    assert v.bucket_name("zt-company") == "zt-company"
    for bad in ["", "i-", "--instance", "I-ABC123", "i-ab cd", "i-yeaaa;rm"]:
        assert code(v.instance_id, bad) == "invalid_instance_id"
    for bad in ["sg-", "-sg-aaaaaaaa", "sg-aaaa aaaa"]:
        assert code(v.security_group_id, bad) == "invalid_sg_id"
    for bad in ["ab", "-bucket", "Bucket", "bucket-", "a_b_c", "tos://x"]:
        assert code(v.bucket_name, bad) == "invalid_bucket"


def test_prefix_rejects_traversal_and_options():
    assert v.object_prefix("/项目/2026-007/") == "项目/2026-007"
    assert v.object_prefix("") == ""
    for bad in ["../x", "a/../b", "-rf", "a\\b", "a\nb"]:
        assert code(v.object_prefix, bad) == "invalid_prefix"


def test_ssh_alias_cannot_look_like_an_option():
    assert v.ssh_alias("zt-prod") == "zt-prod"
    for bad in ["-oProxyCommand=x", "a b", "a;b", "", "$(id)"]:
        assert code(v.ssh_alias, bad) == "invalid_ssh_alias"


def test_protocol_ports_policy_priority():
    assert v.protocol("TCP") == "tcp"
    assert code(v.protocol, "gre") == "invalid_protocol"
    assert v.port_range("tcp", 22, 22) == (22, 22)
    assert v.port_range("all", -1, -1) == (-1, -1)
    assert code(v.port_range, "tcp", -1, -1) == "invalid_port"
    assert code(v.port_range, "tcp", 0, 10) == "invalid_port"
    assert code(v.port_range, "tcp", 22, 21) == "invalid_port"
    assert code(v.port_range, "udp", 1, 65536) == "invalid_port"
    assert v.ports_list("22, 2222,22") == [22, 2222]
    for bad in ["", "22,,23", "abc", "0", "70000", "-1"]:
        assert code(v.ports_list, bad) == "invalid_port"
    assert v.policy("Accept") == "accept"
    assert code(v.policy, "allow") == "invalid_policy"
    assert v.priority(100) == 100
    assert code(v.priority, 0) == "invalid_priority"
    assert code(v.priority, 101) == "invalid_priority"


def test_cidr_and_world_open():
    assert v.cidr("120.55.10.20/32") == "120.55.10.20/32"
    assert v.cidr("10.0.0.0/8") == "10.0.0.0/8"
    assert code(v.cidr, "120.55.10.20/24") == "invalid_cidr", "主机位非 0 不接受"
    assert code(v.cidr, "not-an-ip") == "invalid_cidr"
    assert code(v.cidr, "0.0.0.0/0") == "world_open_refused"
    assert code(v.cidr, "::/0") == "world_open_refused"
    assert v.cidr("0.0.0.0/0", allow_world=True) == "0.0.0.0/0"


def test_public_ip_rejects_private_and_garbage():
    assert v.public_ip(" 120.55.10.20\n") == "120.55.10.20"
    for private in ["10.0.0.8", "192.168.1.5", "127.0.0.1", "169.254.1.1", "203.0.113.5"]:
        assert code(v.public_ip, private) == "ip_not_public"
    assert code(v.public_ip, "<html>blocked</html>") == "invalid_ip"
    assert v.host_cidr("120.55.10.20") == "120.55.10.20/32"
    assert v.host_cidr("2400:3200::1") == "2400:3200::1/128"


def test_text_fields_and_timeout():
    assert v.label("alice") == "alice"
    assert code(v.label, "a b") == "invalid_label"
    assert v.description("zt-ssh-sync:alice") == "zt-ssh-sync:alice"
    assert code(v.description, "--x") == "invalid_description"
    assert code(v.description, "a;b") == "invalid_description"
    assert v.timeout_seconds(30) == 30
    assert code(v.timeout_seconds, 0) == "invalid_timeout"
    assert code(v.timeout_seconds, 99999) == "invalid_timeout"
