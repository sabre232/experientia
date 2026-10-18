---
id: c1-p1-backend
name: 后端 API 工程
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: API; 后端; 接口
description: 契约先行 + 错误语义 + 幂等与边界
source: built-in
from: eng-backend
---

后端/API 开发遵守：

契约：
- 接口先定输入/输出 schema 再写实现；改契约先改文档/测试，再改代码。
- 对外字段命名与现有 API 一致；NEVER 同一含义多种拼写。

错误与状态：
- 用正确的 HTTP 状态码（4xx 客户端错、5xx 服务端错），错误体带机器可读 code + 人类可读 message。
- NEVER 吞异常后返回 200 空体；要么处理要么抛出。

幂等与边界：
- 写操作（尤其涉及钱的）考虑幂等键；NEVER 假设请求只来一次。
- 入参一律校验（类型/范围/长度），NEVER 信任调用方。

日志：
- 记「发生了什么 + 关键上下文」，NEVER 记密钥、token、完整请求体里的敏感字段。
