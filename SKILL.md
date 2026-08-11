---
name: netease-waimao
description: 使用本地 OMNIX_API_KEY 调用 OmniX 受保护的网易外贸通 v2 REST API，按 OpenAPI 提交企业搜索或获客异步任务，并以 public job/result refs 查询状态、分页结果、公司联系人和海关补充。用于 GETO 线索发现与单公司证据增强；只返回 ExternalObservation，不接触共享 RPA 的内部 ID、登录、短信或管理接口。
---

# 网易外贸通 Provider REST

## 配置和信任边界

- `OMNIX_API_BASE_URL`：OmniX API 根地址。
- `OMNIX_API_KEY`：当前用户的 `omx_test_*` 或 `omx_live_*` Key。
- 可选 `OMNIX_OPENAPI_URL`：默认 `${OMNIX_API_BASE_URL}/swagger/v1/swagger.json`。

使用 `scripts/waimao.py`，先执行 `capabilities`。只调用当前 OpenAPI 中受保护的网易外贸通 v2 普通 Agent API；v2 未发布时状态为 `upstream_unavailable`，不得回退到 v1、共享内部 ID 或无鉴权接口。

OmniX 服务端负责把当前 principal 绑定到 public refs。Skill 不传 owner，不接触共享网易账号的业务 Key/Admin Key，也不解释成每个用户拥有独立网易账号。

## 安全调用

~~~bash
python scripts/waimao.py capabilities
python scripts/waimao.py request POST '/api/NeteaseWaimao/v2/search/jobs' --body search.json --idempotency-key stable-key
python scripts/waimao.py request GET '/api/NeteaseWaimao/v2/search/jobs/public-job-ref'
python scripts/waimao.py request GET '/api/NeteaseWaimao/v2/search/jobs/public-job-ref/results?pageNumber=1&pageSize=20'
~~~

示例路径仅用于说明调用形态；实际大小写、path、参数与 DTO 必须来自本次 capabilities 返回的 OpenAPI。脚本拒绝 v1、admin、login、SMS、usage、raw/RPA 路径，也拒绝非 public 的 job/result path 参数。

POST 必须有可重算的 `Idempotency-Key`。取消任务只在用户明确要求时使用 DELETE + `--confirm-cancel`。没有长阻塞 `wait`：一次调用只提交、查询一次状态或拉一页结果。

## 标准流程

### 1. capability check

区分：

- `skill_unavailable`
- `not_configured`
- `unauthenticated`
- `forbidden`
- `provider_session_expired`
- `upstream_unavailable`
- `partial`

这些状态不等于 `not_found`。

### 2. 提交任务

从 OpenAPI 选择全局搜索或 customs、scene、intelligent、recommendation、exhibition、maps、social 等已发布模块。使用小范围、可解释的 query boundary，保存幂等键和服务端返回的 `public_job_ref`。

不得猜 `public_job_ref` 或 `public_result_ref`。提交返回 202 只表示接受，不表示结果完成。

### 3. 查询与结果

用同一 Key 查询 public ref 的状态；完成后按 OpenAPI 分页取结果。若需要公司详情、联系人或海关补充，只能从当前 principal 可见的 public result ref 发起后续任务。

不要把网页会话失效转化成 login/admin 操作；报告 `provider_session_expired` 交由服务端运维恢复。

### 4. 输出 ExternalObservation

~~~json
{
  "provider": "netease-waimao",
  "operation": "search.results",
  "queryBoundary": {},
  "retrievedOn": "ISO-8601",
  "publicJobRef": "opaque-ref",
  "publicResultRef": null,
  "valueStatus": "observed",
  "data": {},
  "warnings": []
}
~~~

public refs 仅用于后续查询和审计，不是 Company/Project/Source 自然键。

## GETO 交接

- `$geto-find-leads` 使用外贸通扩大候选企业召回。
- `$geto-diligence-company` 使用公司、联系人和海关结果补强特定主体。
- 上层必须做主体去重、官网/公开来源交叉验证、Claim/Source 仲裁后才形成 ResearchDelta。
- 联系人、CustomsEvidence 与 Company 保持独立子资源；查询边界和“汇总有值但明细无值”状态必须保留。

详细异步、分页与错误行为见 [workflows.md](references/workflows.md)，数据解释见 [company-and-customs.md](references/company-and-customs.md)。

## 禁止项

- 不调用 login、SMS、admin、usage、raw RPA 或 v1 接口。
- 不显示、写入或传递共享 RPA 内部 job/result ID。
- 不自行轮询到完成，不无限翻页。
- 不把 Provider 结果直接发布、评分或自动建立关系。
