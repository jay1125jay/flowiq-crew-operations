import copy
import json
import re
from pathlib import Path

import bull_official_enricher as bull

LIVE = Path("race-sports/live.html")


def sample_event(status="SCHEDULED"):
    return {
        "id": "BULL-20261003-37-1-1",
        "sport": "BULL",
        "status": status,
        "start_time": "12:20",
        "left": "RED_TEST",
        "right": "BLUE_TEST",
        "outcomes": [
            {"key": "RED", "name": "홍", "odds": None},
            {"key": "DRAW", "name": "무", "odds": None},
            {"key": "BLUE", "name": "청", "odds": None},
        ],
    }


def check_official_odds_contract():
    scheduled = sample_event("SCHEDULED")
    odds = {"RED": 1.8, "DRAW": 8.5, "BLUE": 2.3}
    assert bull.apply_odds(scheduled, odds, "2026-10-03T12:18:00+09:00", "https://official.example/pre", capture_mode="PRE_RACE_OFFICIAL")
    assert scheduled["odds_history"][-1]["source"] == "CPC_FINAL_SINGLE_AUTO"
    assert scheduled["odds_history"][-1]["capture_mode"] == "PRE_RACE_OFFICIAL"
    assert all(o["odds_source"] == "CPC_FINAL_SINGLE_AUTO" for o in scheduled["outcomes"])
    assert all(o["odds_capture_mode"] == "PRE_RACE_OFFICIAL" for o in scheduled["outcomes"])

    late = sample_event("LIVE")
    assert bull.apply_odds(late, odds, "2026-10-03T12:21:00+09:00", "https://official.example/late", capture_mode="LATE_OFFICIAL_RECOVERY")
    assert all(o["odds_capture_mode"] == "LATE_OFFICIAL_RECOVERY" for o in late["outcomes"])



def check_capture_mode_repair_contract():
    event = sample_event("SCHEDULED")
    odds = {"RED": 1.8, "DRAW": 8.5, "BLUE": 2.3}
    ts = "2026-10-03T12:30:00+09:00"
    assert bull.apply_odds(event, odds, ts, "https://official.example/recovery", capture_mode="PRE_RACE_OFFICIAL")
    result = {
        "official": True,
        "status": "CONFIRMED",
        "winner": {"key": "RED", "label": "홍", "name": "RED_TEST"},
        "sides": {
            "RED": {"name": "RED_TEST", "decision": "승"},
            "BLUE": {"name": "BLUE_TEST", "decision": "패"},
        },
        "markets": [],
        "source": "CPC_RESULT_OFFICIAL",
    }
    assert bull.apply_result(event, result, ts, "https://official.example/result")
    assert bull.repair_capture_modes(event) > 0
    assert all(o["odds_capture_mode"] == "LATE_OFFICIAL_RECOVERY" for o in event["outcomes"])
    assert event["odds_history"][-1]["capture_mode"] == "LATE_OFFICIAL_RECOVERY"
    assert bull.has_official_odds(event)
    assert bull.capture_mode_for(event) == "LATE_OFFICIAL_RECOVERY"


def check_final_retention_contract():
    event = sample_event("SCHEDULED")
    odds = {"RED": 1.8, "DRAW": 8.5, "BLUE": 2.3}
    bull.apply_odds(event, odds, "2026-10-03T12:18:00+09:00", "https://official.example/pre", capture_mode="PRE_RACE_OFFICIAL")
    before = copy.deepcopy(event["outcomes"])
    result = {
        "official": True,
        "status": "CONFIRMED",
        "winner": {"key": "RED", "label": "홍", "name": "RED_TEST"},
        "sides": {
            "RED": {"name": "RED_TEST", "decision": "승"},
            "BLUE": {"name": "BLUE_TEST", "decision": "패"},
        },
        "markets": [{"market": "단승", "winner": "홍", "odds": 1.8}],
        "source": "CPC_RESULT_OFFICIAL",
    }
    assert bull.apply_result(event, result, "2026-10-03T12:30:00+09:00", "https://official.example/result")
    assert event["status"] == "FINAL"
    assert event["result"]["official"] is True
    assert event["result"]["winner"]["key"] == "RED"
    assert event["outcomes"][0]["odds"] == before[0]["odds"]
    assert event["outcomes"][1]["odds"] == before[1]["odds"]
    assert event["outcomes"][2]["odds"] == before[2]["odds"]
    assert event["odds_history"]
    assert event["outcomes"][0]["won"] is True
    assert event["outcomes"][1]["won"] is False
    assert event["outcomes"][2]["won"] is False


def check_ui_contract():
    s = LIVE.read_text(encoding="utf-8")

    scoped = re.search(r"function scoped\(\)\{([^}]*)\}", s)
    assert scoped, "SCOPED_FUNCTION_MISSING"
    body = scoped.group(1)
    assert "e.sport===sp" in body, "SPORT_FILTER_MISSING"
    assert "status" not in body, "FINAL_EVENT_FILTERED_FROM_TODAY"

    pre = re.search(r"function preOdds\(o\)\{([^}]*)\}", s)
    assert pre, "PRE_ODDS_FUNCTION_MISSING"
    pre_body = pre.group(1)
    assert "CPC_FINAL_SINGLE_AUTO" in pre_body, "CPC_OFFICIAL_ODDS_SOURCE_MISSING"
    assert "PRE_RACE_OFFICIAL" in pre_body, "PRE_RACE_OFFICIAL_MODE_MISSING"
    assert "LATE_OFFICIAL_RECOVERY" not in pre_body, "LATE_ODDS_MUST_NOT_ENTER_VALUE"

    required = [
        "e.sport==='BULL'&&e.result.winner",
        "e.status==='FINAL'?'공식 결과':'공식 출전표'",
        "e.status==='FINAL'?'종료 · AI 예측/실제 결과 비교 · 추천 비활성'",
        "a.length?a.map(card).join('')",
    ]
    for token in required:
        assert token in s, "UI_CONTRACT_MISSING:" + token


def main():
    check_official_odds_contract()
    check_capture_mode_repair_contract()
    check_final_retention_contract()
    check_ui_contract()
    print(json.dumps({
        "BULL_CONTRACT_GUARD": "PASS",
        "manual_odds": "DISALLOWED",
        "value_odds": "PRE_RACE_OFFICIAL_ONLY",
        "late_odds_for_value": "BLOCKED",
        "capture_mode_repair": "PASS",
        "final_result_retained": True,
        "final_event_visible_today": True,
        "odds_history_retained": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
