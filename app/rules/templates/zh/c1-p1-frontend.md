---
id: c1-p1-frontend
name: 前端工程
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: 前端; 组件
description: 组件边界 + 状态管理 + 可访问性
source: built-in
from: eng-frontend
---

前端开发遵守：

组件：
- 组件保持单一职责；超过一个屏幕高或职责混杂就拆。
- 受控组件与不可控组件不混用；props 命名与现有组件库一致。

状态：
- 能局部化就不上全局状态；先问「这个状态需要跨几个组件」，答案 ≤2 用 props/局部 state。
- 派生数据用 useMemo/计算，NEVER 存两份同源状态再手动同步。

可访问性与质量：
- 交互元素保证键盘可达（button 不用 div 假按钮）；表单控件有 label。
- 改 UI 后检查 console 无新增报错/警告再交付。

NEVER：NEVER 在组件里直接写死环境相关 URL；NEVER 为省一行引入全局 CSS 污染。
