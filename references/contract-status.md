# 网易外贸通 Agent REST 合同成熟度

截至 2026-08-13，测试环境尚未上线，相关服务端 PR 仍未合并。运行时 OpenAPI 是唯一可调用合同；当前仓库中的路由族说明和 Mock fixtures 不是“已上线/已实测”的证据。

## 当前可做

- 静态检查 Skill、脚本、OpenAPI allowlist 和安全边界。
- 使用本地 Mock OpenAPI/响应验证 schema、public ref、幂等、分页、状态归一和内部 ID 隔离。
- 输出真实 REST 合同测试 `blocked/pending_test_environment`。

## 环境就绪后才可做

- 创建 queued/running/completed/failed/cancelled/session-expired 任务并验证状态转换。
- 验证 owner-bound public refs：创建 Key 可读，另一 Key 按不存在处理。
- 验证分页、重复 Idempotency-Key、取消和 enrichment 的服务端行为。
- 以上真实测试必须使用明确授权的测试 Key，不写生产数据，不调用管理、登录、短信、usage 或 raw RPA。

本 Skill 只使用 OmniX Agent REST。MCP 完全不纳入设计、实现或测试。
