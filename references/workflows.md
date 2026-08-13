# 异步任务工作流

1. 从 OpenAPI 读取当前 submit operation 和 schema。
2. 用确定性 Idempotency-Key 提交一次；保存 public_job_ref。
3. 在后续 Agent turn 中查询一次状态，不使用本地长阻塞 wait。
4. completed 后用 OpenAPI 声明且有上下界的 query `pageNumber`、`pageSize` 读取 public results；响应保存 `page_number`、`page_size`、`total`。
5. enrichment 必须使用当前 principal 可见的 public_result_ref。

`queued/running` 是正常状态。`failed/cancelled/provider_session_expired` 是终态或需要外部恢复的状态。网络超时后使用同一 Idempotency-Key 恢复提交，不生成第二个任务。

脚本将已知业务状态归一为 `queued|running|completed|failed|cancelled|provider_session_expired`；HTTP providerStatus 与 jobStatus 分开，不能把 202/queued 当 completed。

只在用户明确要求取消某个已解析 public_job_ref 时调用 DELETE；取消后报告任务状态，不清理其他结果。

分页必须保存 pageNumber、pageSize、total 和 query boundary。默认先取一页验证数据；全量研究按上层任务范围继续，不把单页结果称为全量。
