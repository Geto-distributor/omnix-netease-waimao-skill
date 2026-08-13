# OmniX 网易外贸通 Agent Skill

面向 OmniX 受保护的网易外贸通 v2 REST API 的 Agent Skill 与 Python 安全客户端。它通过运行时 OpenAPI 发现可用能力，提交企业搜索或获客异步任务，并使用 owner-bound `public_job_ref` / `public_result_ref` 查询结果。

> 本项目由 GETO / OmniX 维护，不是网易官方 SDK。实际数据能力、可用性和使用条款以服务提供方及 OmniX 部署方的说明为准。

## 能力

- 企业搜索和已发布的获客模块。
- 异步任务状态、分页结果和显式取消。
- 基于公开结果引用的公司、联系人和海关补充。
- OpenAPI 路径白名单、幂等键和跨用户数据隔离保护。

本仓库不包含登录、短信、管理员、用量、v1、原始 RPA 接口，也不包含共享 RPA 凭据或内部任务 ID。

集成只使用 Agent REST，不包含 MCP。当前测试环境和候选服务端 PR 状态见 [合同成熟度](references/contract-status.md)；环境就绪前不声称真实 Provider 调用或跨 Key 隔离测试已通过。

## 安装

~~~bash
git clone https://github.com/Geto-distributor/omnix-netease-waimao-skill.git ~/.codex/skills/netease-waimao
~~~

也可以将仓库克隆到其他支持 `SKILL.md` 的 Agent 运行时的 Skill 搜索目录。

## 配置

~~~bash
export OMNIX_API_BASE_URL="https://<your-omnix-host>"
export OMNIX_API_KEY="omx_live_xxx"
# 可选；默认使用 $OMNIX_API_BASE_URL/swagger/v1/swagger.json
export OMNIX_OPENAPI_URL="https://<your-omnix-host>/swagger/v1/swagger.json"
~~~

API Key 必须由 OmniX 部署方签发。不要把真实 Key 写入仓库、Prompt、日志或研究交付物。

## 使用

~~~bash
python3 scripts/waimao.py --help
python3 scripts/waimao.py capabilities
python3 scripts/waimao.py request POST '/api/NeteaseWaimao/v2/search/jobs' \
  --body search.json \
  --idempotency-key stable-key
python3 -m unittest discover -s tests -v
~~~

先阅读 [SKILL.md](SKILL.md)。实际 endpoint、method 和 DTO 始终以当前 OmniX OpenAPI 为准。

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。
