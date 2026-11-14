import { useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'

import Overview from './views/Overview'
import RegistryView from './views/registry'
import RouterView from './views/router'
import CacheView from './views/cache'
import CacheQueryView from './views/cache-query'
import LimiterView from './views/limiter'
import OrchestraView from './views/orchestra'
import TraceView from './views/trace'
import DiagnoseView from './views/diagnose'
import SchemaView from './views/schema'
import SubscribeView from './views/subscribe'
import TransformView from './views/transform'
import MockView from './views/mock'
import GatewayView from './views/gateway'
import MetricView from './views/metric'
import WhitelistView from './views/whitelist'
import BalanceView from './views/balance'
import RollbackView from './views/rollback'

const navItems = [{ label: "运营概览", path: "/" }, { label: "服务注册发现", path: "/registry" }, { label: "查询路由分发", path: "/router" }, { label: "结果缓存加速", path: "/cache" }, { label: "查询结果详情", path: "/cache-query" }, { label: "调用限流降级", path: "/limiter" }, { label: "服务编排组合", path: "/orchestra" }, { label: "调用链追踪", path: "/trace" }, { label: "服务健康诊断", path: "/diagnose" }, { label: "数据接口契约", path: "/schema" }, { label: "数据订阅推送", path: "/subscribe" }, { label: "数据加工转换", path: "/transform" }, { label: "数据模拟服务", path: "/mock" }, { label: "接入网关管理", path: "/gateway" }, { label: "服务指标采集", path: "/metric" }, { label: "调用来源管理", path: "/whitelist" }, { label: "负载均衡策略", path: "/balance" }, { label: "服务版本回退", path: "/rollback" }]

export default function App() {
  const [operator] = useState('值班管理员')

  return (
    <div className="app-shell">
      <aside className="app-side">
        <h1 className="app-title">实时数据服务总线平台</h1>
        <nav className="nav-list">
          {navItems.map((item) => (
            <Link key={item.path} to={item.path} className="nav-item">
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="app-main">
        <header className="app-head">
          <span className="head-desc">面向业务系统的一站式实时数据服务总线平台。覆盖数据服务注册与发现、查询路由分发、结果缓存加速、调用限流降级、服务编排组合、调用链追踪与服务健康诊断的完整数据服务链路。</span>
          <span className="head-user">当前值班：{operator}</span>
        </header>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/registry" element={<RegistryView />} />
          <Route path="/router" element={<RouterView />} />
          <Route path="/cache" element={<CacheView />} />
          <Route path="/cache-query" element={<CacheQueryView />} />
          <Route path="/limiter" element={<LimiterView />} />
          <Route path="/orchestra" element={<OrchestraView />} />
          <Route path="/trace" element={<TraceView />} />
          <Route path="/diagnose" element={<DiagnoseView />} />
          <Route path="/schema" element={<SchemaView />} />
          <Route path="/subscribe" element={<SubscribeView />} />
          <Route path="/transform" element={<TransformView />} />
          <Route path="/mock" element={<MockView />} />
          <Route path="/gateway" element={<GatewayView />} />
          <Route path="/metric" element={<MetricView />} />
          <Route path="/whitelist" element={<WhitelistView />} />
          <Route path="/balance" element={<BalanceView />} />
          <Route path="/rollback" element={<RollbackView />} />
        </Routes>
      </main>
    </div>
  )
}
