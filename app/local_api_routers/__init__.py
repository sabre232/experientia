"""本地 API 的资源域 router（M5 拆分 `create_local_app`）。

约定见各域模块的 docstring：域模块不反向 import `app.local_api`，
只暴露 `build_xxx_router(store)` 工厂供 `create_local_app` 用
`app.include_router(...)` 挂载。
"""
