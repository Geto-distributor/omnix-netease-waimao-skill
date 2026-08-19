# 公司、联系人和海关观察

## 公司

Provider 公司名称、网站、域名、地址、描述和 record ref 均为候选观察。先用官网域名、法定名、RFC/注册号、返回记录国家与别名解析 Company；组合实体、分支、品牌和法定实体不得自动合并。请求 country 不等于记录已证明该国家，通用法律后缀不构成名称锚点。

## 联系人

保存姓名、职位、层级、邮箱、电话、公司域名、地点、provider record ref 与 retrievedOn。邮箱/电话存在不证明其当前任职；邮箱验证 Evidence 的 verificationScope 只写 `workEmail.deliverability`。任职、职位、授权和 buyingRole 需要公开来源或多源一致性仲裁。

## 海关

保存主体、交易方、时间范围、HS/商品、数量、金额、币种、记录数、查询国家/分区和 provider query boundary。汇总有值但明细为空时标记 `summary_only` 或等价 valueStatus，并保留原始依据；不得生成不存在的明细。

Provider 结果不能单独证明采购产品的最终用途、项目归属、payer 或当前合作状态。
