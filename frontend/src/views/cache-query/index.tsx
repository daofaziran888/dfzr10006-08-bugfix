import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { request } from '@/api/client'

const ENDPOINT = '/api/cache'

type Row = Record<string, string | number | boolean | null>

type Snapshot = {
  版本: number
  键名: string
  配置编号: string
  过期秒数: string
  结果行: string[]
  生成时间: string
}

type QueryResult = {
  hit: boolean
  key: string
  reason: string
  entry: Row | null
  snapshot: Snapshot | null
}

export default function CacheQueryView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [key, setKey] = useState(searchParams.get('key') ?? '')
  const [result, setResult] = useState<QueryResult | null>(null)
  const [configs, setConfigs] = useState<Row[]>([])
  const [errorMessage, setErrorMessage] = useState('')
  const [noticeMessage, setNoticeMessage] = useState('')

  const loadConfigs = useCallback(async () => {
    try {
      const response = await request(`${ENDPOINT}?size=200`)
      if (!response.ok) {
        throw new Error('缓存配置清单读取失败')
      }
      const payload = await response.json()
      setConfigs(payload.items ?? [])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '缓存配置清单读取失败')
    }
  }, [])

  const runQuery = useCallback(async (target: string) => {
    setErrorMessage('')
    const trimmed = target.trim()
    if (!trimmed) {
      setResult(null)
      return
    }
    try {
      const response = await request(`${ENDPOINT}/query?key=${encodeURIComponent(trimmed)}`)
      if (!response.ok) {
        throw new Error('查询结果读取失败')
      }
      setResult((await response.json()) as QueryResult)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '查询结果读取失败')
    }
  }, [])

  useEffect(() => {
    void loadConfigs()
  }, [loadConfigs])

  useEffect(() => {
    const initial = searchParams.get('key')
    if (initial) {
      setKey(initial)
      void runQuery(initial)
    }
  }, [searchParams, runQuery])

  async function refresh(entry: Row, simulateFailure: boolean) {
    setErrorMessage('')
    setNoticeMessage('')
    try {
      const response = await request(`${ENDPOINT}/${entry.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action: '刷新缓存', 模拟失败: simulateFailure } }),
      })
      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload?.message ?? '刷新缓存未生效，请稍后重试')
      }
      if (payload.ok) {
        setNoticeMessage(payload.message ?? '缓存已刷新')
      } else {
        setErrorMessage(payload.message ?? '刷新缓存未生效，请稍后重试')
      }
      await Promise.all([loadConfigs(), runQuery(String(entry['缓存键名'] ?? ''))])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '刷新缓存操作失败')
    }
  }

  const entry = result?.entry ?? null
  const refreshable = entry !== null && (entry.status === '生效中' || entry.status === '已暂停')
  const lastFailure = String(entry?.['最近刷新失败原因'] ?? '')

  return (
    <section className="page" data-module="cache-query">
      <header className="page-head">
        <div>
          <h2>查询结果详情</h2>
          <p className="page-desc">按缓存键名查看路由服务实际拿到的查询结果快照；这里的缓存版本与缓存配置清单引用同一份数据。</p>
        </div>
      </header>

      <form
        className="filter-bar"
        onSubmit={(event) => {
          event.preventDefault()
          setSearchParams(key.trim() ? { key: key.trim() } : {})
        }}
      >
        <label className="filter-item">
          <span>缓存键名</span>
          <input
            value={key}
            placeholder="输入缓存键名，如 query:route-hit"
            onChange={(event) => setKey(event.target.value)}
          />
        </label>
        <button className="btn primary" type="submit">查询结果</button>
      </form>

      {result && result.hit && result.snapshot && (
        <table className="data-table">
          <tbody>
            <tr><th>配置编号</th><td>{result.snapshot.配置编号}</td></tr>
            <tr><th>缓存键名</th><td>{result.snapshot.键名}</td></tr>
            <tr><th>缓存版本</th><td>v{result.snapshot.版本}</td></tr>
            <tr><th>过期秒数</th><td>{result.snapshot.过期秒数}</td></tr>
            <tr><th>生成时间</th><td>{result.snapshot.生成时间}</td></tr>
            <tr>
              <th>查询结果快照</th>
              <td>
                <ul>
                  {result.snapshot.结果行.map((line) => <li key={line}>{line}</li>)}
                </ul>
              </td>
            </tr>
          </tbody>
        </table>
      )}

      {result && !result.hit && (
        <table className="data-table">
          <tbody>
            <tr><th>缓存键名</th><td>{result.key}</td></tr>
            {entry && <tr><th>配置编号</th><td>{String(entry['配置编号'] ?? '—')}</td></tr>}
            {entry && <tr><th>配置状态</th><td>{String(entry['配置状态'] ?? '—')}</td></tr>}
            {entry && <tr><th>缓存版本</th><td>v{String(entry['缓存版本'] ?? 0)}</td></tr>}
            <tr><th>空态原因</th><td className="empty-reason">{result.reason}</td></tr>
          </tbody>
        </table>
      )}

      {!result && (
        <p className="empty-state">输入缓存键名后查询；没有命中或缓存失效时会在这里显示空态原因。</p>
      )}

      {refreshable && entry && (
        <div className="page-actions">
          <button className="btn" type="button" onClick={() => void refresh(entry, false)}>刷新缓存</button>
          <button className="btn ghost" type="button" onClick={() => void refresh(entry, true)}>刷新缓存（模拟失败）</button>
        </div>
      )}
      {lastFailure && <p className="error-text">最近刷新失败原因：{lastFailure}（上一份完整快照已保留，可重试）</p>}
      {noticeMessage && <p>{noticeMessage}</p>}
      {errorMessage && <p className="error-text">{errorMessage}</p>}

      <h3>缓存配置清单</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>配置编号</th>
            <th>缓存键名</th>
            <th>过期秒数</th>
            <th>缓存版本</th>
            <th>配置状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {configs.map((row) => (
            <tr key={String(row.id)}>
              <td>{String(row['配置编号'] ?? '—')}</td>
              <td>{String(row['缓存键名'] ?? '—')}</td>
              <td>{String(row['过期秒数'] ?? '—')}</td>
              <td>v{String(row['缓存版本'] ?? 0)}</td>
              <td>{String(row['配置状态'] ?? '—')}</td>
              <td className="row-actions">
                <button
                  className="link"
                  type="button"
                  onClick={() => setSearchParams({ key: String(row['缓存键名'] ?? '') })}
                >
                  查询结果
                </button>
              </td>
            </tr>
          ))}
          {configs.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={6}>暂无缓存配置</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
