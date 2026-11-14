"""ONT-48 T8 (G11): truncated implies a non-null cursor; eligible canaries suggest promote."""

from __future__ import annotations

import server


def test_page_output_lists_truncates_with_cursor() -> None:
    parsed = {"items": list(range(10)), "name": "x"}
    truncated, cur = server._page_output_lists(parsed, 4, 0)
    assert truncated is True and cur == "4"
    assert parsed["items"] == [0, 1, 2, 3] and parsed["total_items"] == 10


def test_page_output_lists_follows_cursor_to_end() -> None:
    parsed = {"items": list(range(10))}
    truncated, cur = server._page_output_lists(parsed, 4, 8)
    assert truncated is False and cur is None
    assert parsed["items"] == [8, 9]


def test_truncated_invariant_over_all_offsets() -> None:
    for offset in range(0, 12):
        parsed = {"items": list(range(10))}
        truncated, cur = server._page_output_lists(parsed, 3, offset)
        assert (not truncated) or cur is not None


def test_canary_next_action_promote() -> None:
    nxt = server._canary_next_action({"task_id": 76, "eligible_for_promotion": True})
    assert nxt == 'kanban_board(action="promote", task_id=76)'
    assert server._canary_next_action({"task_id": 76, "eligible_for_promotion": False}) is None
    assert server._canary_next_action(None) is None
