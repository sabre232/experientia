# AGENTS.md — 给执行 agent 的规则

- **唯一事实来源**：产品文档。文档没写的不要自己发明，列出来问。
- **数据层铁律**：所有对 `~/.experientia/` 的读写走 `app/store/store.py`，禁止其他模块直接碰文件。
- **命名规范**：用户可见字符串用平实中文；内部术语只出现在架构部分与代码里。
- **捕获层约定**：加 agent = `app/capture/adapters/` 加一个文件 + `registry.py` 加一行；解析失败单条跳过不中断；归一化 schema 在 `app/capture/models.py`。
- **防错误传播**：G < 0.5 永不注入；失败模式 ≥3 次才固化。
- **写入面红线**：产品不下载、不安装、也不联网检查更新（`app/updater/` 已整块移除）；任何新能力都不许写程序目录或系统盘，只有 `Store` 能写 `~/.experientia/`。
- **原子替换一律走 `app/fs_util.replace_atomic`**（Windows 瞬时锁重试，`os.replace` 会偶发 `PermissionError [WinError 5]`）；`app/` 与 `scripts/` 禁止裸 `os.replace`，`tests/test_fs_util.py` 有守卫测试。
- **回环 HTTP 一律绕过系统代理**：`httpx.Client(mounts=DIRECT_LOOPBACK)`（`app/net_util.py`）。开着系统代理的机器上，回环请求会被改写成绝对 URI 后送到代理 → 404。**顶层 `httpx.get/post()` 不接受 `mounts`**（传了 TypeError），只有 `Client`/`AsyncClient` 的构造函数认；`tests/test_net_util.py` 有守卫。
- **测试不得依赖宿主机真实状态**（端口/守护进程/系统代理/真实 home/剪贴板）：`tests/conftest.py` 提供 `_no_env_proxy`、`_pin_local_api_listening` 两道 autouse 闸与 `OfflineApi` 桩基类；页面桩一律继承 `OfflineApi`，不得直挂 `LocalApi`。新建含只读产物（如 `git init`）的测试收尾用 `rmtree_readonly`。
- 验收：产品文档的验收清单逐条过；闭环实证判据为第 3 次较第 1 次修正轮数降 ≥30%。
- Python 3.11+，依赖用 uv 管理（`pyproject.toml`）。
