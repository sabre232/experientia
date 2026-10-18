---
id: c5-p0-eng-safety
name: 工程安全边界
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: engineering; security
keywords: 密钥; CI; 删除; 安全
description: 密钥不入库、CI/依赖锁不乱动、不可逆操作停下来问
donts: |
  - NEVER 提交密钥、token、内网地址到代码或配置
  - NEVER 改动 CI 配置、依赖版本锁文件，除非任务明确要求
  - 删除数据/文件前先确认影响范围，不可逆操作停下来问
source: research
from: eng-general
---

NEVER 安全边界：
- NEVER 提交密钥、token、内网地址到代码或配置。
- NEVER 改动 CI 配置、依赖版本锁文件，除非任务明确要求。
- 删除数据/文件前先确认影响范围，不可逆操作停下来问。
