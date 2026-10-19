"""TOS 只读管理：桶列表、对象列表截断、lifecycle/versioning 的命令存在性检查。"""
from __future__ import annotations

import pytest

from tests.volc.helpers import FakeVe
from zt.common.errors import ZtError
from zt.volc import tos
from zt.volc.ve import Ve


def setup(tmp_path):
    fake = FakeVe(tmp_path)
    for name in ("ls", "stat", "help", "lifecycle"):
        fake.copy(f"tosutil.{name}", f"tosutil.{name}.txt")
    return fake, Ve(fake.settings())


def test_buckets(tmp_path):
    fake, ve = setup(tmp_path)
    env = tos.buckets_envelope(ve)
    assert env.data == {"buckets": ["zt-company", "zt-archive"], "total": 2}
    assert fake.calls("tosutil.ls") == [["tosutil", "ls"]], "透传命令不带 --profile，也不带 --yes"


def test_buckets_empty_and_unrecognized(tmp_path):
    fake, ve = setup(tmp_path)
    fake.fixture("tosutil.ls", "", ext="txt")
    env = tos.buckets_envelope(ve)
    assert env.status.value == "empty" and env.status_reason == "no_buckets"
    fake.fixture("tosutil.ls", "something else entirely\n", ext="txt")
    with pytest.raises(ZtError) as e:
        tos.buckets_envelope(ve)
    assert e.value.code == "tosutil_output_unrecognized"


def test_stat_and_ls_pass_uri(tmp_path):
    fake, ve = setup(tmp_path)
    assert tos.stat_envelope(ve, "zt-company").data["lines"][1] == "Region: cn-beijing"
    assert fake.calls("tosutil.stat") == [["tosutil", "stat", "tos://zt-company"]]
    tos.ls_envelope(ve, "zt-company", "项目/2026-007")
    assert fake.calls("tosutil.ls")[-1] == ["tosutil", "ls", "tos://zt-company/项目/2026-007"]


def test_ls_truncates_to_partial_and_empty(tmp_path):
    fake, ve = setup(tmp_path)
    fake.fixture("tosutil.ls", "\n".join(f"obj{i}" for i in range(250)), ext="txt")
    env = tos.ls_envelope(ve, "zt-company", "")
    assert env.status.value == "partial" and len(env.data["lines"]) == tos.MAX_LINES
    assert env.coverage == {"lines_total": 250, "lines_shown": tos.MAX_LINES}
    fake.fixture("tosutil.ls", "\n\n", ext="txt")
    assert tos.ls_envelope(ve, "zt-company", "x").status_reason == "no_objects"


def test_stat_without_output_is_an_error(tmp_path):
    fake, ve = setup(tmp_path)
    fake.fixture("tosutil.stat", "", ext="txt")
    with pytest.raises(ZtError) as e:
        tos.stat_envelope(ve, "zt-company")
    assert e.value.code == "tosutil_empty_output"


def test_lifecycle_checks_verb_first_and_flags_unverified_syntax(tmp_path):
    fake, ve = setup(tmp_path)
    env = tos.config_envelope(ve, "lifecycle", "zt-company")
    assert fake.keys() == ["tosutil.help", "tosutil.lifecycle"]
    assert fake.calls("tosutil.lifecycle")[0] == ["tosutil", "lifecycle", "-method", "get", "tos://zt-company"]
    assert [w.code for w in env.warning_items] == ["tosutil_syntax_unverified"]
    assert env.data["setting"] == "lifecycle"


def test_missing_verb_is_refused_without_guessing(tmp_path):
    fake, ve = setup(tmp_path)
    fake.fixture("tosutil.help", "Commands: ls stat cp rm mb lifecycle-rules\n", ext="txt")
    with pytest.raises(ZtError) as e:
        tos.config_envelope(ve, "versioning", "zt-company")
    assert e.value.code == "tosutil_verb_missing"
    assert "tosutil.versioning" not in fake.keys()
    with pytest.raises(ZtError) as e:
        tos.config_envelope(ve, "lifecycle", "zt-company")
    assert e.value.code == "tosutil_verb_missing", "lifecycle-rules 不算 lifecycle"
    with pytest.raises(ZtError):
        tos.config_envelope(ve, "cors", "zt-company")
