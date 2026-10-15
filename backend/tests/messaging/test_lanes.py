"""Lane → queue cố định trên một broker (không file topology); `--lanes` gõ sai phải lỗi."""

import pytest

from app.core.messaging.lanes import LANES, check_lane, parse_lanes, task_queue


def test_lanes_are_fixed():
    assert LANES == {"default": "bw.tq.default", "agent-run": "bw.tq.agent-run"}
    assert task_queue("agent-run") == "bw.tq.agent-run"


def test_parse_lanes():
    assert parse_lanes("") is None and parse_lanes(None) is None
    assert parse_lanes(" default , agent-run ") == ["default", "agent-run"]
    with pytest.raises(ValueError, match="khong-co"):
        parse_lanes("default,khong-co")
    with pytest.raises(ValueError):
        check_lane("x")
