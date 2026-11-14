"""结果缓存加速业务规则：状态流转、快照版本与命中口径都收在这里。

缓存动作到查询结果返回链：

    缓存动作（启用缓存 / 暂停缓存 / 关闭缓存 / 刷新缓存）
        → 缓存版本与查询结果快照（同一把锁内原子推进，不允许一半新一半旧）
        → 路由服务按缓存键名取快照（query）
        → 命中返回当前版本完整快照；未命中 / 已失效返回空态原因。

约定：
- 状态只能按 草稿 → 生效中 → 已暂停 → 已关闭 推进，动作只认规定的前置状态；
- 暂停后不再新增命中，但上一份完整快照保留，供排查与刷新；
- 关闭必须让相关缓存键名完成最终失效，重复关闭不会第二次失效；
- 刷新要么整体换成新快照，要么保留上一份完整快照并说明失败原因，异常快照不残留。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.store import Store, store

MODULE = "cache"
REQUIRED_FIELDS = ["配置编号", "缓存键名", "过期秒数"]
STATUS_ORDER = ["草稿", "生效中", "已暂停", "已关闭"]
TERMINAL_STATUS = STATUS_ORDER[-1]
# 动作 → 动作发生前必须处于的状态；目标状态一律是 STATUS_ORDER 里的下一个。
ACTION_RULES = {"启用缓存": "草稿", "暂停缓存": "生效中", "关闭缓存": "已暂停"}
REFRESH_ACTION = "刷新缓存"
REFRESHABLE_STATUSES = {"生效中", "已暂停"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _valid_ttl(value: Any) -> bool:
    try:
        return int(str(value).strip()) > 0
    except (TypeError, ValueError):
        return False


class CacheService:
    """缓存配置与查询结果快照的唯一写入口；所有变更都在同一把锁里完成。"""

    def __init__(self, data_store: Store = store) -> None:
        self._store = data_store
        self._lock = threading.RLock()
        # 缓存键名 → 当前完整快照。只保留完整快照：刷新失败不落地，关闭即移除。
        self._snapshots: dict[str, dict[str, Any]] = {}
        # 缓存键名 → 最终失效记录。关闭时写一次，重复关闭 / 并发刷新不会覆盖。
        self._invalidations: dict[str, dict[str, Any]] = {}
        self._bootstrap()

    # ---------- 历史缓存配置兼容 ----------

    def _bootstrap(self) -> None:
        """把历史缓存配置规范到当前口径：缺缓存版本按 0 计；生效中 / 已暂停的补一份
        完整快照；已关闭的补一条最终失效记录。"""
        with self._lock:
            for entry in self._store.rows(MODULE):
                entry["缓存版本"] = int(entry.get("缓存版本") or 0)
                entry.setdefault("最近刷新失败原因", "")
                entry["配置状态"] = str(entry.get("status") or STATUS_ORDER[0])
                key = str(entry.get("缓存键名") or "").strip()
                if not key:
                    continue
                status = entry.get("status")
                if status in REFRESHABLE_STATUSES and entry["缓存版本"] > 0:
                    self._snapshots[key] = self._build_snapshot(entry, entry["缓存版本"])
                elif status == TERMINAL_STATUS and key not in self._invalidations:
                    self._invalidations[key] = self._tombstone(entry)

    # ---------- 配置清单 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            rows = list(self._store.rows(MODULE))
            if keyword:
                rows = [row for row in rows if keyword in str(row.get("配置编号", ""))]
            if status:
                rows = [row for row in rows if row.get("status") == status]
            total = len(rows)
            start = max(page - 1, 0) * size
            return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            return self._store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        with self._lock:
            key = str(values.get("缓存键名") or "").strip()
            holder = self._find_by_key(key, include_closed=False)
            if holder is not None:
                return None, (
                    f"缓存键名「{key}」已被配置 {holder.get('配置编号')} 占用，"
                    "请先关闭该配置再复用键名"
                )
            rows = self._store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
            entry["status"] = STATUS_ORDER[0]
            entry["配置状态"] = STATUS_ORDER[0]
            entry["缓存版本"] = 0
            entry["最近刷新失败原因"] = ""
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
            return entry, "缓存配置已登记"

    # ---------- 缓存动作 ----------

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, bool, str]:
        values = values or {}
        with self._lock:
            entry = self._store.find(MODULE, entry_id)
            if entry is None:
                return None, False, f"缓存配置 {entry_id} 不存在或已归档"
            if action == REFRESH_ACTION:
                return self._refresh(entry, values)
            if action not in ACTION_RULES:
                return None, False, f"动作「{action}」不属于结果缓存加速可执行范围"
            required = ACTION_RULES[action]
            current = str(entry.get("status") or "")
            if current != required:
                return entry, False, self._reject_message(entry, action, required)
            target = STATUS_ORDER[STATUS_ORDER.index(required) + 1]
            if action == "启用缓存":
                ttl = entry.get("过期秒数")
                if not _valid_ttl(ttl):
                    return entry, False, (
                        f"启用缓存失败：过期秒数「{ttl}」不是正整数，无法生成完整快照"
                    )
                self._publish(entry, int(entry.get("缓存版本") or 0) + 1)
            if action == "关闭缓存":
                self._invalidate(entry)
            entry["status"] = target
            entry["配置状态"] = target
            entry["pending"] = target != TERMINAL_STATUS
            return entry, True, f"缓存配置已{action}，当前状态「{target}」"

    def _reject_message(self, entry: dict[str, Any], action: str, required: str) -> str:
        code = entry.get("配置编号")
        current = str(entry.get("status") or "")
        if current == TERMINAL_STATUS:
            key = str(entry.get("缓存键名") or "").strip()
            return (
                f"缓存配置 {code} 已关闭，键名「{key}」已完成最终失效，不能重复{action}"
            )
        return (
            f"缓存配置 {code} 当前状态「{current}」，不能执行{action}："
            f"{action}仅能从「{required}」发起，"
            f"状态只能按 {' → '.join(STATUS_ORDER)} 推进"
        )

    def _refresh(
        self, entry: dict[str, Any], values: dict[str, Any]
    ) -> tuple[dict[str, Any], bool, str]:
        code = entry.get("配置编号")
        key = str(entry.get("缓存键名") or "").strip()
        status = str(entry.get("status") or "")
        if status == TERMINAL_STATUS:
            return entry, False, (
                f"缓存配置 {code} 已关闭，键名「{key}」已完成最终失效，不能再刷新"
            )
        if status not in REFRESHABLE_STATUSES:
            return entry, False, (
                f"缓存配置 {code} 仍是「{status}」，还没有快照可刷新，请先启用缓存"
            )
        old_version = int(entry.get("缓存版本") or 0)
        keep = (
            f"已保留上一份完整快照 v{old_version}"
            if old_version > 0
            else "当前还没有可用快照"
        )
        ttl = entry.get("过期秒数")
        if not _valid_ttl(ttl):
            return self._refresh_failed(
                entry, f"过期秒数「{ttl}」不是正整数，无法生成完整快照", keep
            )
        if values.get("模拟失败"):
            return self._refresh_failed(entry, "上游查询模拟失败，未拿到完整结果集", keep)
        # 先在局部变量里把新快照构建完整，再一次整体换入，杜绝一半新一半旧。
        self._publish(entry, old_version + 1)
        entry["最近刷新失败原因"] = ""
        entry["abnormal"] = False
        return entry, True, (
            f"缓存配置 {code} 已刷新到 v{old_version + 1}，查询结果快照已整体替换"
        )

    def _refresh_failed(
        self, entry: dict[str, Any], reason: str, keep: str
    ) -> tuple[dict[str, Any], bool, str]:
        # 失败只记录原因，不动快照：旧版本完整保留，可重试，异常快照不残留。
        entry["最近刷新失败原因"] = reason
        entry["abnormal"] = True
        return entry, False, f"刷新失败：{reason}，{keep}，可重试"

    # ---------- 查询结果返回链 ----------

    def query(self, key: str) -> dict[str, Any]:
        """路由服务的查询结果返回链：按缓存键名取当前版本快照。

        命中返回与配置清单同版本的完整快照；未命中 / 已失效返回空态原因。
        """
        key = str(key or "").strip()
        with self._lock:
            entry = self._find_by_key(key)
            if entry is None:
                return {
                    "hit": False,
                    "key": key,
                    "entry": None,
                    "snapshot": None,
                    "reason": f"没有命中：缓存键名「{key}」没有对应的缓存配置",
                }
            code = entry.get("配置编号")
            status = str(entry.get("status") or "")
            version = int(entry.get("缓存版本") or 0)
            if status == "草稿":
                reason = (
                    f"没有命中：缓存配置 {code} 仍是草稿，尚未启用，还没有生成快照"
                )
            elif status == "已暂停":
                reason = (
                    f"没有命中：缓存配置 {code} 已暂停，暂停期间不再新增命中"
                    f"（上一份完整快照 v{version} 已保留）"
                )
            elif status == TERMINAL_STATUS:
                tombstone = self._invalidations.get(key)
                final_version = tombstone["失效版本"] if tombstone else version
                reason = (
                    f"缓存已失效：配置 {code} 已关闭，键名「{key}」已完成最终失效"
                    f"（失效版本 v{final_version}），不再返回任何快照"
                )
            else:
                snapshot = self._snapshots.get(key)
                if snapshot is None:
                    reason = (
                        f"没有命中：配置 {code} 生效中但快照缺失，"
                        "请执行一次刷新缓存补齐"
                    )
                else:
                    return {
                        "hit": True,
                        "key": key,
                        "entry": entry,
                        "snapshot": snapshot,
                        "reason": "",
                    }
            return {"hit": False, "key": key, "entry": entry, "snapshot": None, "reason": reason}

    # ---------- 快照与失效的原子操作（都必须已经持有锁） ----------

    def _publish(self, entry: dict[str, Any], version: int) -> None:
        key = str(entry.get("缓存键名") or "").strip()
        entry["缓存版本"] = version
        # 新快照落地后，同键名旧的失效记录不再适用。
        self._invalidations.pop(key, None)
        self._snapshots[key] = self._build_snapshot(entry, version)

    def _invalidate(self, entry: dict[str, Any]) -> None:
        key = str(entry.get("缓存键名") or "").strip()
        # 关闭即失效：路由服务从这一刻起拿不到任何旧版本。
        self._snapshots.pop(key, None)
        if key and key not in self._invalidations:
            # 只允许一次最终失效：重复关闭 / 并发刷新都不会改写这条记录。
            self._invalidations[key] = self._tombstone(entry)

    def _tombstone(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "配置编号": entry.get("配置编号"),
            "失效版本": int(entry.get("缓存版本") or 0),
            "失效时间": _now(),
        }

    def _build_snapshot(self, entry: dict[str, Any], version: int) -> dict[str, Any]:
        key = str(entry.get("缓存键名") or "").strip()
        return {
            "版本": version,
            "键名": key,
            "配置编号": entry.get("配置编号"),
            "过期秒数": entry.get("过期秒数"),
            "结果行": [f"{key} 第{version}版查询结果行{i}" for i in range(1, 4)],
            "生成时间": _now(),
        }

    def _find_by_key(self, key: str, *, include_closed: bool = True) -> dict[str, Any] | None:
        if not key:
            return None
        candidates = [
            row
            for row in self._store.rows(MODULE)
            if str(row.get("缓存键名") or "").strip() == key
        ]
        if not include_closed:
            candidates = [row for row in candidates if row.get("status") != TERMINAL_STATUS]
        if not candidates:
            return None
        open_rows = [row for row in candidates if row.get("status") != TERMINAL_STATUS]
        pool = open_rows or candidates
        return max(pool, key=lambda row: int(row.get("id", 0)))
