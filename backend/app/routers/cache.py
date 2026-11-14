"""结果缓存加速接口：维护缓存配置，覆盖启用缓存、暂停缓存、关闭缓存、刷新缓存与命中查询。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.cache import CacheService

router = APIRouter(prefix="/api/cache", tags=["结果缓存加速"])

service = CacheService()

LIST_FIELDS = ["配置编号", "缓存键名", "过期秒数", "缓存版本", "刷新策略", "预热开关", "容量上限", "淘汰算法", "配置状态"]
STATUSES = ["草稿", "生效中", "已暂停", "已关闭"]


@router.get("/query")
def query_result(key: str = Query(default="", description="缓存键名")) -> dict[str, Any]:
    """查询结果返回链：路由服务按缓存键名取快照。

    命中时返回与缓存配置清单同版本的完整快照；没有命中或缓存已失效时返回空态原因。
    """
    return service.query(key)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出结果缓存加速清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "cache", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按配置编号检索"),
    status: str | None = Query(default=None, description="草稿、生效中、已暂停、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按配置编号与状态过滤结果缓存加速列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条缓存配置明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"缓存配置 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条缓存配置，缺字段或键名冲突时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条缓存配置执行启用缓存、暂停缓存、关闭缓存、刷新缓存。

    状态只能按 草稿 → 生效中 → 已暂停 → 已关闭 推进；不允许的动作会被拦下并说明原因，
    刷新失败会保留上一份完整快照并说明原因。
    """
    action = str(payload.values.get("action") or "").strip()
    entry, ok, message = service.run_action(entry_id, action, payload.values)
    return ActionResult(ok=ok, message=message, entry=entry)
