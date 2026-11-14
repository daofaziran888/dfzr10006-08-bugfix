"""结果缓存加速修复的回归验证：直接驱动 CacheService 覆盖任务要求的场景。

运行方式（不需要 pytest）：
    cd backend && .venv/bin/python -m tests.test_cache_service
"""
from __future__ import annotations

import sys
import threading

from app.services.cache import REFRESH_ACTION, CacheService
from app.store import Store

CACH_0001 = 1  # 草稿
CACH_0002 = 2  # 生效中
CACH_0003 = 3  # 已暂停

KEYS = {CACH_0001: "query:daily-report", CACH_0002: "query:route-hit", CACH_0003: "query:user-profile"}


def make_service() -> CacheService:
    return CacheService(Store())


def act(service: CacheService, entry_id: int, action: str, **values):
    return service.run_action(entry_id, action, {"action": action, **values})


def test_close_from_draft_rejected() -> None:
    """CACH-0001：草稿直接关闭必须被拦下，状态保持草稿，键名不产生任何快照。"""
    service = make_service()
    entry, ok, message = act(service, CACH_0001, "关闭缓存")
    assert not ok, message
    assert entry is not None and entry["status"] == "草稿", entry
    assert "已暂停" in message, message
    result = service.query(KEYS[CACH_0001])
    assert not result["hit"] and "草稿" in result["reason"], result


def test_full_lifecycle_and_single_final_invalidation() -> None:
    """CACH-0001：草稿→生效中→已暂停→已关闭；关闭后键名失效；重复关闭只有一次最终失效。"""
    service = make_service()
    entry, ok, _ = act(service, CACH_0001, "启用缓存")
    assert ok and entry["status"] == "生效中" and entry["缓存版本"] == 1, entry
    hit = service.query(KEYS[CACH_0001])
    assert hit["hit"] and hit["snapshot"]["版本"] == 1, hit

    entry, ok, _ = act(service, CACH_0001, "暂停缓存")
    assert ok and entry["status"] == "已暂停", entry
    paused = service.query(KEYS[CACH_0001])
    assert not paused["hit"] and "已暂停" in paused["reason"], paused

    entry, ok, _ = act(service, CACH_0001, "关闭缓存")
    assert ok and entry["status"] == "已关闭", entry
    closed = service.query(KEYS[CACH_0001])
    assert not closed["hit"] and "已失效" in closed["reason"] and "v1" in closed["reason"], closed

    # 重复关闭：被拒，失效记录保持一次
    entry, ok, message = act(service, CACH_0001, "关闭缓存")
    assert not ok and "已关闭" in message, message
    assert len(service._invalidations) == 1, service._invalidations
    assert service._invalidations[KEYS[CACH_0001]]["失效版本"] == 1


def test_out_of_order_actions_rejected() -> None:
    """状态只能按序推进：草稿不能暂停，生效中不能重复启用。"""
    service = make_service()
    _, ok, message = act(service, CACH_0001, "暂停缓存")
    assert not ok and "生效中" in message, message
    _, ok, message = act(service, CACH_0002, "启用缓存")
    assert not ok and "草稿" in message, message


def test_paused_cache_serves_no_hits() -> None:
    """CACH-0003：已暂停后同一缓存键名不再返回旧快照；暂停中刷新成功但仍不命中。"""
    service = make_service()
    result = service.query(KEYS[CACH_0003])
    assert not result["hit"] and "已暂停" in result["reason"], result
    assert "v1" in result["reason"], result  # 上一份完整快照保留，只是不再命中

    entry, ok, _ = act(service, CACH_0003, REFRESH_ACTION)
    assert ok and entry["缓存版本"] == 2, entry
    result = service.query(KEYS[CACH_0003])
    assert not result["hit"] and "v2" in result["reason"], result


def test_refresh_failure_keeps_previous_snapshot_and_is_retryable() -> None:
    """CACH-0002：刷新失败保留上一份完整快照并说明原因；可重试；异常快照不残留。"""
    service = make_service()
    before = service.query(KEYS[CACH_0002])
    assert before["hit"] and before["snapshot"]["版本"] == 1, before

    entry, ok, message = act(service, CACH_0002, REFRESH_ACTION, 模拟失败=True)
    assert not ok and "保留上一份完整快照 v1" in message, message
    assert entry["缓存版本"] == 1 and entry["最近刷新失败原因"], entry
    after = service.query(KEYS[CACH_0002])
    assert after["hit"] and after["snapshot"]["版本"] == 1, after  # 旧快照完整保留
    assert len(service._snapshots) == 2, service._snapshots  # 没有异常快照残留

    entry, ok, message = act(service, CACH_0002, REFRESH_ACTION)
    assert ok and entry["缓存版本"] == 2 and entry["最近刷新失败原因"] == "", entry
    after = service.query(KEYS[CACH_0002])
    assert after["hit"] and after["snapshot"]["版本"] == 2, after


def test_closed_cache_cannot_refresh() -> None:
    """关闭后不能再刷新，避免已失效键名被刷新复活。"""
    service = make_service()
    act(service, CACH_0003, "关闭缓存")
    _, ok, message = act(service, CACH_0003, REFRESH_ACTION)
    assert not ok and "已关闭" in message, message
    result = service.query(KEYS[CACH_0003])
    assert not result["hit"] and "已失效" in result["reason"], result


def test_concurrent_close_and_refresh_single_final_invalidation() -> None:
    """CACH-0002：暂停后并发执行关闭与刷新，最终只允许一次失效，且配置与快照同版本。"""
    for round_no in range(50):
        service = make_service()
        entry, ok, _ = act(service, CACH_0002, "暂停缓存")
        assert ok, entry

        results: list[tuple[dict | None, bool, str]] = []
        lock = threading.Lock()

        def run(entry_id: int, action: str) -> None:
            outcome = act(service, entry_id, action)
            with lock:
                results.append(outcome)

        closer = threading.Thread(target=run, args=(CACH_0002, "关闭缓存"))
        refresher = threading.Thread(target=run, args=(CACH_0002, REFRESH_ACTION))
        closer.start()
        refresher.start()
        closer.join()
        refresher.join()

        entry = service.get_entry(CACH_0002)
        assert entry["status"] == "已关闭", (round_no, entry, results)
        assert len(service._invalidations) == 1, (round_no, service._invalidations)
        tombstone = service._invalidations[KEYS[CACH_0002]]
        # 失效记录里的版本必须等于配置清单上的最终版本：不允许一半新一半旧
        assert tombstone["失效版本"] == entry["缓存版本"], (round_no, tombstone, entry)
        result = service.query(KEYS[CACH_0002])
        assert not result["hit"] and "已失效" in result["reason"], (round_no, result)
        assert f"v{entry['缓存版本']}" in result["reason"], (round_no, result)
        # 关闭之后键名下不允许再有任何可用快照
        assert KEYS[CACH_0002] not in service._snapshots, (round_no, service._snapshots)


def test_list_and_hit_share_same_version() -> None:
    """缓存配置清单与缓存命中结果引用同一份缓存版本。"""
    service = make_service()
    act(service, CACH_0002, REFRESH_ACTION)
    rows, _ = service.list_entries()
    listed = next(row for row in rows if row["id"] == CACH_0002)
    hit = service.query(KEYS[CACH_0002])
    assert hit["hit"], hit
    assert listed["缓存版本"] == hit["snapshot"]["版本"] == 2, (listed, hit)
    assert listed["缓存键名"] == hit["snapshot"]["键名"]
    assert listed["过期秒数"] == hit["snapshot"]["过期秒数"]


def test_unknown_key_shows_empty_reason() -> None:
    service = make_service()
    result = service.query("query:no-such-key")
    assert not result["hit"] and "没有命中" in result["reason"], result


def main() -> int:
    tests = [
        test_close_from_draft_rejected,
        test_full_lifecycle_and_single_final_invalidation,
        test_out_of_order_actions_rejected,
        test_paused_cache_serves_no_hits,
        test_refresh_failure_keeps_previous_snapshot_and_is_retryable,
        test_closed_cache_cannot_refresh,
        test_concurrent_close_and_refresh_single_final_invalidation,
        test_list_and_hit_share_same_version,
        test_unknown_key_shows_empty_reason,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except AssertionError as error:
            failures += 1
            print(f"FAIL {test.__name__}: {error}")
        else:
            print(f"PASS {test.__name__}")
    print(f"{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
