"""Interpreter tests — JSON parsing into NeutralEvents. No API key (parser only)."""
import json
import pytest

from modapts.interpreter import parse_response, SYSTEM_PROMPT
from modapts.core.neutral import EventType, SourceState, PlacementAccuracy


def test_parse_minimal():
    raw = json.dumps({
        "interpreted_action": "get resistor; place on board",
        "events": [
            {"event_type": "acquire", "object": "resistor", "object_size": "tiny",
             "source_state": "jumbled", "object_weight_kg": 0.01, "distance_cm": 15,
             "inferred_fields": ["object_weight_kg"]},
            {"event_type": "place", "object": "resistor",
             "placement_accuracy": "tight", "distance_cm": 5},
        ],
    })
    act = parse_response(raw)
    assert act.interpreted_action.startswith("get resistor")
    assert len(act.events) == 2
    assert act.events[0].event_type == EventType.ACQUIRE
    assert act.events[0].source_state == SourceState.JUMBLED
    assert "object_weight_kg" in act.events[0].inferred_fields
    assert act.events[1].placement_accuracy == PlacementAccuracy.TIGHT


def test_parse_strips_markdown_fences():
    inner = json.dumps({"interpreted_action": "x",
                        "events": [{"event_type": "inspect", "object": "part"}]})
    act = parse_response(f"```json\n{inner}\n```")
    assert act.events[0].event_type == EventType.INSPECT


def test_parse_defaults_for_omitted_fields():
    raw = json.dumps({"interpreted_action": "press",
                      "events": [{"event_type": "operate_device", "object": "button"}]})
    act = parse_response(raw)
    ev = act.events[0]
    assert ev.placement_accuracy == PlacementAccuracy.NA   # omitted -> NA default
    assert ev.object_weight_kg is None
    assert ev.repetition == 1


def test_parse_rejects_bad_json():
    with pytest.raises(ValueError, match="malformed JSON"):
        parse_response("not json at all")


def test_parse_rejects_missing_events():
    with pytest.raises(ValueError, match="missing 'events'"):
        parse_response(json.dumps({"interpreted_action": "x"}))


def test_system_prompt_is_facts_not_codes():
    # guardrail: the prompt must forbid codes/times and require neutral fields
    assert "never" in SYSTEM_PROMPT.lower()
    assert "sensing_dependency" in SYSTEM_PROMPT
    assert "inferred_fields" in SYSTEM_PROMPT
