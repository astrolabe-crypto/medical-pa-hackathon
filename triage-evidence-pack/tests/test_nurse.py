"""Care-team queue: pure, offline tests for audit records and backfill."""
from __future__ import annotations

import asyncio
import json

from demo.server import main
from demo.server import scenarios
from demo.server.router_adapter import MockRouter


def test_panel_seed_is_believable_and_margaret_free():
    seed = json.loads((main.demo_config.NURSE_DIR / "panel_seed.json").read_text(encoding="utf-8"))
    c = seed["counts"]
    assert c["quiet"] + c["watching"] + c["needs_review"] == c["total"] == 247
    pts = seed["patients"]
    assert len(pts) == 8
    # Margaret is NOT seeded — she arrives live via SSE
    assert all("margaret" not in p["name"].lower() for p in pts)
    # background panel is amber/grey only; no pre-seeded URGENT
    assert all(p["tier"] in ("ROUTINE", "WATCH") for p in pts)
    for p in pts:
        assert p["reason"] and p["conditions"] and p["last_contact"]


def test_both_actions_defined():
    assert set(main.NURSE_ACTIONS) == {"callback", "gp"}
    for a in main.NURSE_ACTIONS.values():
        assert a["badge"] and a["banner"] and a["spoken"]


def test_action_record_schema():
    rec = main._action_record("callback", "hf_weight_red_flag", "Margaret Bailey")
    assert rec["type"] == "action" and rec["source"] == "nurse"
    assert rec["action"] == "callback" and rec["actor"] == "Sarah"
    assert rec["rule_id"] == "hf_weight_red_flag" and rec["patient"] == "Margaret Bailey"
    assert "Callback booked" in rec["booked"]
    assert isinstance(rec["ts"], float)


def test_confirmation_meta_speaks_and_banners():
    m = main._action_confirmed_meta("callback", "hf_weight_red_flag")
    assert m["type"] == "action_confirmed"
    assert m["banner"].startswith("✓")
    assert "Sarah" in m["spoken_response"]
    assert m["rule_id"] == "hf_weight_red_flag"
    # gp path is the quieter secondary
    g = main._action_confirmed_meta("gp", "hf_weight_red_flag")
    assert "GP" in g["banner"] and g["spoken_response"]


def test_escalation_log_writes_local_audit_and_structured_handoff(tmp_path, monkeypatch):
    """The care-team audit preserves local wording separately from the handoff."""
    log = tmp_path / "escalations.jsonl"
    monkeypatch.setattr(main.demo_config, "ESCALATIONS_LOG", log)
    scenario = scenarios.replays()["1"]
    result = asyncio.run(MockRouter().route(
        scenario["utterance"], scenario["patient_context"], scenario["sensor_data"]
    ))

    rec = main._log_escalation("talk", "Margaret's local demo wording", result)
    written = json.loads(log.read_text(encoding="utf-8"))

    assert rec == written
    assert written["transcript"] == "Margaret's local demo wording"
    assert written["tier"] == "URGENT"
    assert written["scrubbed_payload"] == result.scrubbed_payload
    assert "Margaret's local demo wording" not in written["scrubbed_payload"]


def test_read_feed_splits_escalations_and_actions(tmp_path, monkeypatch):
    log = tmp_path / "escalations.jsonl"
    lines = [
        {"proactive": True, "rule_id": "hf_weight_red_flag", "tier": "URGENT",
         "scrubbed_payload": "Margaret ...", "spoken_response": "I've noticed ...",
         "evidence": {"delta_kg": 2.3}},
        {"proactive": False, "source": "talk", "tier": "URGENT"},
        {"type": "action", "action": "callback", "rule_id": "hf_weight_red_flag",
         "booked": "Callback booked - Sarah, 9:15am"},
    ]
    log.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(main.demo_config, "ESCALATIONS_LOG", log)

    feed = main._read_feed()
    # A reconnecting nurse page sees both device-led and spoken-care alerts.
    assert len(feed["escalations"]) == 2
    assert feed["escalations"][0]["rule_id"] == "hf_weight_red_flag"
    assert feed["escalations"][0]["spoken_response"].startswith("I've noticed")
    assert feed["escalations"][1]["source"] == "talk"
    assert len(feed["actions"]) == 1
    assert feed["actions"][0]["booked"].startswith("Callback booked")


def test_read_feed_missing_log_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(main.demo_config, "ESCALATIONS_LOG", tmp_path / "nope.jsonl")
    assert main._read_feed() == {"escalations": [], "actions": []}
