# 错误与安全边界

| HTTP/业务状态 | 处理 |
|---|---|
| 401 | `unauthenticated`；检查本地 OMNIX_API_KEY 生命周期 |
| 403 | `forbidden`；不尝试 Web session 或其他身份 |
| 404 | public ref 不属于当前 principal、已不存在或 endpoint 未发布；不探测内部 ID |
| 409/422 | 修正任务状态或请求合同，不原样重试 |
| 429 | `rate_limited`；遵守 Retry-After |
| 502/503/504 | `upstream_unavailable`；使用原幂等键恢复 |
| provider_session_expired | 报告外部恢复需求，不调用 login/admin |

Skill 不提供登录、短信、管理员、用量或共享 RPA 调试能力。错误输出不得包含 OMNIX_API_KEY、内部 job/result ID、RPA cookie 或共享账号信息。
