import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { request } from '@/api/client'

const ENDPOINT = '/api/cache'
const columns = [
  "配置编号",
  "缓存键名",
  "过期秒数",
  "缓存版本",
  "刷新策略",
  "预热开关",
  "容量上限",
  "淘汰算法",
  "配置状态"
]
const actions = [
  "启用缓存",
  "暂停缓存",
  "关闭缓存",
  "刷新缓存"
]

type Row = Record<string, string | number | boolean | null>

export default function CacheView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [noticeMessage, setNoticeMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('缓存配置列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '结果缓存加速列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    setNoticeMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        throw new Error(payload?.message ?? '结果缓存加速动作未生效，请稍后重试')
      }
      setNoticeMessage(payload.message ?? `缓存配置已${action}`)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '结果缓存加速操作失败')
    }
  }

  const statCards = [
    { label: '缓存配置总数', value: total },
    { label: '生效中缓存', value: rows.filter((row) => row.status === '生效中').length },
    { label: '已暂停缓存', value: rows.filter((row) => row.status === '已暂停').length },
  ]

  return (
    <section className="page" data-module="cache">
      <header className="page-head">
        <div>
          <h2>结果缓存加速管理</h2>
          <p className="page-desc">维护查询结果的缓存参数、过期策略与预热机制，为结果缓存加速提供可验证的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('缓存配置登记入口尚未接入审批流')}>
            登记缓存配置
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出结果缓存加速清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {statCards.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => (
                <td key={column}>
                  {column === '缓存版本' ? `v${String(row[column] ?? 0)}` : (row[column] ?? '—')}
                </td>
              ))}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
                <Link className="link" to={`/cache-query?key=${encodeURIComponent(String(row['缓存键名'] ?? ''))}`}>
                  查询结果
                </Link>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无结果缓存加速数据，可先登记缓存配置</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条结果缓存加速记录</span>
        {noticeMessage && <span>{noticeMessage}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
