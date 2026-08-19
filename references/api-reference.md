# 网易外贸通 Agent API 合同

OpenAPI 是 endpoint、method、query、request/response schema 和 operation availability 的唯一权威来源。客户端只接受路径中明确包含 NeteaseWaimao v2 的普通 Agent API。

## 能力类型

- 企业全局搜索。
- customs、scene、intelligent、recommendation、exhibition、maps、social 等已发布获客模块。
- public job 状态查询。
- public result 分页读取。
- 基于 public result 的公司详情、联系人或海关 enrichment。
- 用户明确要求的 owner-bound task cancellation。

某能力未出现在当前 OpenAPI 时标记不可用，不自行推断 endpoint。

运行时 OpenAPI 提供以下 v2 路由族：

- `GET acquisition/modules`
- `POST search/jobs`、`POST acquisition/jobs` 及 customs/scene/intelligent/recommendation/exhibition/maps/social 模块任务
- `GET|DELETE search/jobs/{publicJobRef}` 与 `GET .../results?pageNumber=&pageSize=`
- `GET|DELETE acquisition/jobs/{publicJobRef}` 与 `GET .../results?pageNumber=&pageSize=`
- `POST company-details/jobs`、`GET|DELETE company-details/jobs/{publicJobRef}`、`GET .../result`
- `POST customs-details/jobs`、`GET|DELETE customs-details/jobs/{publicJobRef}`、`GET .../result`

company/customs enrichment 的 body 只传 `public_result_ref` 和业务查询选项；不得传 `search_result_id`。

## 鉴权

所有普通操作使用本地 `OMNIX_API_KEY`，以 `X-API-KEY` 发送。owner 由服务端 principal 推导；body、query 与 path 均不得携带 user_account_id、tenant 或共享 RPA 内部身份。

## 标识

对外仅接受/返回不可猜测的 `public_job_ref` / `public_result_ref`。状态和结果必须使用创建它们的同一 OmniX principal 查询；另一用户访问时按不存在处理。任何名为 job_id、result_id、search_result_id 或缺少 public 语义的底层引用均不进入 Skill 合同。

客户端会移除响应中意外出现的内部 job/result/RPA 字段并记录 warning。不存在或不属于当前 principal 的 public ref 按 404 处理，不探测其他身份或内部 ID。
