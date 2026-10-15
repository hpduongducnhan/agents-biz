"""`bw agent-eval` + `eval.report`: chỉ chạy router với LLM giả; báo cáo tỉ lệ; exit 1 khi < 95 %."""

import uuid

import pytest
import yaml
from typer.testing import CliRunner

from app import cli as cli_module
from app.agent import eval as ev
from app.agent.testing import fake_llm as fl
from tests.agent.helpers import setup, setup_router

runner = CliRunner()


def outcome(text, expected, got, clarify=None):
    return ev.Outcome(text, expected, got, clarify)


def test_outcome_ok_and_exact_rules():
    assert outcome("a", ["personal"], ["personal"]).ok
    assert outcome("a", ["personal", "report"], ["personal"]).ok  # chỉ cần bước đầu đúng
    assert not outcome("a", ["personal", "report"], ["personal"]).exact
    assert outcome("a", ["personal", "report"], ["personal", "report"]).exact
    assert not outcome("a", ["personal"], ["report"]).ok and not outcome("a", ["personal"], []).ok
    assert outcome("a", None, [], "Ví nào?").ok and outcome("a", None, [], "Ví nào?").exact is True
    assert not outcome("a", None, ["general"], None).ok and not outcome("a", None, ["personal"], "x").ok


def test_report_rate_and_miss_lines():
    outs = [
        outcome("ăn trưa", ["personal"], ["personal"]),
        outcome("báo cáo", ["report"], ["personal"]),
        outcome("mơ hồ", None, ["general"]),
        outcome("mơ hồ 2", ["report"], [], "Ví nào?"),
    ]
    rate, lines = ev.report(outs)
    assert rate == 0.25 and len(lines) == 3
    assert lines[0] == "✗ 'báo cáo': mong report, được personal"
    assert lines[1] == "✗ 'mơ hồ': mong hỏi lại, được general"
    assert lines[2] == "✗ 'mơ hồ 2': mong report, được hỏi lại: Ví nào?"
    assert ev.report([]) == (0.0, [])
    assert ev.report([outcome("a", ["x"], ["x"])]) == (1.0, [])


def test_past_builds_messages_with_agent_ids():
    sp = uuid.uuid4()
    case = {
        "text": "t",
        "history": [{"role": "user", "text": "u"}, {"role": "assistant", "agent": "personal", "text": "a?"}],
    }
    past = ev._past(case, {"personal": sp})
    assert [(m.role, m.agent_id, m.content["text"]) for m in past] == [("user", None, "u"), ("assistant", sp, "a?")]
    assert ev._past({"text": "t"}, {}) == []


@pytest.fixture
def cases_file(tmp_path, monkeypatch):
    path = tmp_path / "cases.yaml"
    path.write_text(
        yaml.safe_dump(
            [
                {"text": "route:report tổng chi", "expect": {"steps": ["report"]}},
                {"text": "route:personal,report a | b", "expect": {"steps": ["personal", "report"]}},
                {"text": "clarify:Ví nào?", "expect": {"clarify": True}},
                {"text": "route:general chào", "expect": {"steps": ["personal"]}},  # cố tình sai
                {
                    "text": "route:general ừ",
                    "history": [
                        {"role": "user", "text": "tổng chi tháng nào"},
                        {"role": "assistant", "agent": "report", "text": "Tháng nào?"},
                    ],
                    "expect": {"steps": ["report"]},
                },
            ],
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ev, "CASES", path)
    monkeypatch.setattr(ev, "load_cases", lambda p=path: yaml.safe_load(p.read_text(encoding="utf-8")))
    return path


async def test_run_eval_runs_only_the_router_and_reports_misses(team, api, aenv, fake_llm, cases_file):
    await setup_router(api, fake_llm.base_url)
    fl.REQUESTS.clear()
    outs = await ev.run_eval(aenv)
    assert [o.got for o in outs] == [["report"], ["personal", "report"], [], ["general"], ["report"]]
    assert [o.ok for o in outs] == [True, True, True, False, True]  # câu cuối: bám chuyên gia lượt trước
    assert outs[2].clarify == "Ví nào?"
    assert len(fl.REQUESTS) == 5  # mỗi câu đúng một lần gọi LLM (router), không chuyên gia
    assert (await ev.run_eval(aenv, limit=2))[-1].text.startswith("route:personal,report")
    rate, lines = ev.report(outs)
    assert rate == 0.8 and len(lines) == 1


async def test_run_eval_requires_configured_orchestrator(api, aenv, fake_llm):
    with pytest.raises(RuntimeError, match="chưa là orchestrator"):
        await ev.run_eval(aenv)  # seed chưa có model
    await setup(api, fake_llm.base_url)  # "Assistant" thành specialist
    with pytest.raises(RuntimeError):
        await ev.run_eval(aenv)


def test_cli_agent_eval_exit_codes_and_json(monkeypatch):
    async def passing(_s, limit):
        return [outcome("a", ["personal"], ["personal"]), outcome("b", None, [], "?")]

    monkeypatch.setattr(cli_module, "_agent_eval", passing)
    monkeypatch.setattr(cli_module, "load_domains", lambda: None)
    ok = runner.invoke(cli_module.cli, ["agent-eval", "--json"])
    assert ok.exit_code == 0 and "đúng bước đầu 100.0% (2/2)" in ok.output and '"ok": true' in ok.output

    async def failing(_s, limit):
        assert limit == 1
        return [outcome("a", ["personal"], ["report"])] * 2

    monkeypatch.setattr(cli_module, "_agent_eval", failing)
    bad = runner.invoke(cli_module.cli, ["agent-eval", "--limit", "1"])
    assert bad.exit_code == 1 and "✗ 'a': mong personal, được report" in bad.output and "0.0%" in bad.output
