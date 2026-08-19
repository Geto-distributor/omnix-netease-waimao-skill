# ExternalObservation 采纳合同

## 主体候选

精确公司名和国家查询仍可能返回宽匹配候选。逐条保存：

```json
{
  "identityDecision": "accepted|rejected|unresolved",
  "decisionReasons": [],
  "queryCountry": "MX",
  "observedCountry": null,
  "matchedAnchors": [],
  "conflictingAnchors": []
}
```

- 法定名、RFC/注册号、稳定官网域名和返回记录国家是主体锚点。
- `S.R.L.`、`S.A. de C.V.`、LLC、Ltd 及阿拉伯语通用法律词不构成名称锚点。
- 候选法定名、RFC 或官网域名与目标冲突时使用 rejected；无强锚点时使用 unresolved。
- 请求 country 只属于 queryBoundary；返回记录未体现国家时 `observedCountry=null`。

## 失败与零结果

- `diagnosticCodes` 含 `server_configuration_missing` 时，任务状态为 failed；它表示服务端搜索结果路径等运行配置缺失。
- `provider_session_expired`、`upstream_unavailable`、`failed` 均不等于 not_found。
- completed 且当前 queryBoundary 的结果数组为空，才记录该边界的 no_result。

## 联系人邮箱桥接

邮箱存在或可投递只支持邮箱字段：

```json
{
  "verificationStatus": "email_only",
  "evidence": [{
    "sourceType": "provider",
    "relation": "context",
    "verificationScope": ["workEmail.deliverability"],
    "note": "Mailbox deliverability only; does not verify employment, title, authority, or buying role."
  }]
}
```

当前任职、职位、授权和采购角色分别需要公司官网、人员公开职业页或多源一致证据。
