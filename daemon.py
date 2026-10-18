"""headless 入口：只跑引擎，无 GUI（产品文档 /）。

引擎 = 统一代理（localhost:8100）+ 文件捕获 + 自动蒸馏 + 存储 + 更新，
常驻一个纯 Python 进程，三平台同一份代码。开机自启与托盘常驻走此入口。

当前已落地：代理+ 文件捕获+ 自动蒸馏（M4，会话复盘 + 阈值兜底）。
后续：M6 更新子系统。
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone

from app.capture import scan as capture_scan
from app.config_schema import feature_enabled
from app.distill import engine_curation
from app.store.store import Store, affinity_display
from app.thread_util import spawn

SCAN_INTERVAL_SECONDS = 60
DISTILL_INTERVAL_SECONDS = 300
# 扫描循环首轮退避——让 GUI 先画完首帧，再跑扫描/迁移/模型下载。
# 只作用于首次；后续按 SCAN_INTERVAL_SECONDS 走，扫描语义与实时性承诺不变。
SCAN_STARTUP_BACKOFF_SECONDS = 2.0

log = logging.getLogger("experientia.daemon")

# 文件通道复盘工作线程（M5：LLM 复盘最长 30 分钟，不能阻塞扫描循环）：
# 单 worker + FIFO 队列，新 session 永不丢失。
# 内存预算：maxsize=16 + 背压——60s 扫描间隔 × 单 worker，16 个在途已远超
# 处理速率；积压只会在 worker 卡死（模型调用挂起）时发生。满则不丢不阻塞：
# 挂起到 pending_reviews（store 管理、封顶 200 行），下轮扫描开头从落库记录
# 重建 review dict 再入队（唯一的无损恢复路径——ref 签名首轮解析后已更新，
# 关闭的文件下轮会被跳过，不能靠重新解析兜底）。
REVIEW_QUEUE_MAX = 16
_review_queue: "queue.Queue[tuple[Store, dict]]" = queue.Queue(maxsize=REVIEW_QUEUE_MAX)
_review_worker: threading.Thread | None = None


def _review_worker_loop() -> None:
    while True:
        store, session_dict = _review_queue.get()
        try:
            capture_scan.review_sessions(store, [session_dict])
            # 只有复盘跑完且没抛异常才标记——失败留着在飞标记，下轮重试
            capture_scan.settle_reviewed(store, [session_dict])
        except Exception as exc:
            log.warning("复盘工作线程异常 %s: %s",
                        session_dict.get("session_id", "?"), exc)


def _spawn_review(store: Store, session_dicts: list) -> None:
    """入队 review dict（M3 入队瘦身：dict 无原始 messages，单条 <32KB）。"""
    if not session_dicts:
        return
    global _review_worker
    for d in session_dicts:
        try:
            _review_queue.put_nowait((store, d))
        except queue.Full:
            log.warning("复盘队列满（容量 %d），挂起 %s/%s 待下轮恢复",
                        REVIEW_QUEUE_MAX, d.get("agent"), d.get("session_id"))
            store.append_pending_review(d.get("agent"), d.get("session_id"))
    if _review_worker is None or not _review_worker.is_alive():
        _review_worker = threading.Thread(
            target=_review_worker_loop, name="experientia-review", daemon=True)
        _review_worker.start()


def _drain_pending_reviews(store: Store) -> None:
    """M3 + 修复方案：挂起项重放——从落库记录重建 review dict 再入队。

    模型感知（本次改动核心）：无模型/熔断时**不排水**——条目留在
    pending_reviews 作为「未提炼片段」展示（旧行为会每轮重入队→复盘
    再挂起→空转 churn）。接上模型后的下一轮扫描自然排干。
    复盘只消费落库记录里已有的字段（req_count/correction_hits/
    user_messages/assistant_messages/trunk/category），不依赖内存 Session。
    队列仍满时保留挂起项，下轮再试（宁慢勿丢）。"""
    from app.distill import llm

    if not llm.model_available(store) or llm.circuit_open(store):
        return
    for agent, session_id in store.load_pending_reviews():
        rec = next((s for s in store.list_sessions()
                    if s.get("agent") == agent
                    and s.get("session_id") == session_id), None)
        if rec is None:
            store.drop_pending_review(agent, session_id)  # 落库记录已不存在
            continue
        # -P1-4：重放素材回读归档原文（落库转录是 20×200 展示口径，
        # 直接喂复盘会系统性偏弱）
        rec = capture_scan.review_dict_for_replay(store, rec)
        try:
            _review_queue.put_nowait((store, rec))
            store.drop_pending_review(agent, session_id)
        except queue.Full:
            break
        except Exception as exc:
            # 入队成功但出队失败（非 Full）时不能既在内存
            # 队列又留 pending——下轮会重复复盘同一会话（不必要 LLM 成本）。
            # 停下本轮，保留 pending，下次启动/下轮自然重试。
            logger.warning("待复盘出队失败（保留 pending，下轮重试）: %s", exc)
            break


# auto_check 工作线程（M-2：阈值兜底蒸馏要调模型，单次最长 30 分钟——
# 内联在扫描循环会冻结文件捕获。单 worker + 至多 1 个在排队：
# 扫描循环每轮触发，上一轮还在跑/排队时不再重复入队，跑完由下一轮再触发。）
_auto_check_queue: "queue.Queue[Store]" = queue.Queue()
_auto_check_worker: threading.Thread | None = None


def _auto_check_worker_loop() -> None:
    while True:
        st = _auto_check_queue.get()
        try:
            engine_curation.auto_check(st, verbose=True)
        except Exception as exc:
            log.warning("auto_check 工作线程异常（不杀常驻）: %s", exc)


def _spawn_auto_check(store: Store) -> None:
    global _auto_check_worker
    if _auto_check_queue.qsize() == 0:
        _auto_check_queue.put(store)
    if _auto_check_worker is None or not _auto_check_worker.is_alive():
        _auto_check_worker = threading.Thread(
            target=_auto_check_worker_loop, name="experientia-auto-check", daemon=True)
        _auto_check_worker.start()


def _proxy_thread(store: Store, port: int) -> threading.Thread:
    def run() -> None:
        from app.proxy.server import create_app

        import uvicorn

        app = create_app(store)
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        uvicorn.Server(config).run()

    # spawn 兜底：uvicorn 的后端/协议是运行期动态 import，缺模块时线程会带着
    # ImportError 静默死亡（打包事故：端口没起、日志零报错）。
    return spawn(run, name="experientia-proxy")


def _proxy_alive(port: int) -> bool:
    """探活 = GET /health。裸 TCP connect 会把"端口上别人的监听"
    误判为代理存活（双实例/端口被占时崩溃恢复永不触发）。"""
    import httpx

    from app.net_util import DIRECT_LOOPBACK

    try:
        # DIRECT_LOOPBACK：回环请求必须绕过系统代理，否则开着代理的机器上请求行
        # 被改写成绝对 URI → 代理返回 404，探活恒假（崩溃自恢复永不触发）。
        # 注意：`mounts` 只有 httpx.Client/AsyncClient 的构造函数认，
        # 顶层 httpx.get/post() 传它会 TypeError（实测）。
        with httpx.Client(mounts=DIRECT_LOOPBACK, timeout=2) as cli:
            r = cli.get(f"http://127.0.0.1:{port}/health")
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


PROXY_MAX_RETRIES = 5          # 连续重拉上限（端口被占时避免无限重拉）
PROXY_START_GRACE_SECONDS = 15  # 启动宽限：uvicorn 绑定 + 首轮探测不触发重拉


def _watch_proxy(store: Store, port: int, state: dict) -> None:
    """代理监控一轮（M-1 崩溃自恢复）：健康 → 计数清零；无响应 → 重拉线程。

    重拉上限 PROXY_MAX_RETRIES：端口被其他进程占用时新线程绑定必失败，
    重拉只会刷屏——达到上限后记一次 error 并停手。
    state 由 scan_loop 持有：{"thread", "retries", "warned"}。
    """
    if _proxy_alive(port):
        state["retries"] = 0
        return
    if state["retries"] >= PROXY_MAX_RETRIES:
        if not state.get("warned"):
            state["warned"] = True
            log.error("代理 %s 持续无响应（端口可能被占用），放弃自动重拉", port)
        return
    state["retries"] += 1
    log.warning("代理 %s 无响应，重拉（%d/%d）", port, state["retries"], PROXY_MAX_RETRIES)
    state["thread"] = _proxy_thread(store, port)


LOCAL_API_PORT = 8101


def probe_local_api(port: int = LOCAL_API_PORT,
                    api_token: str | None = None,
                    timeout: float = 10.0) -> str | None:
    """探活本地 API 端口（M-4）：有活实例返回其数据目录，端口空闲返回 None。

    8101 是固定端口：两个不同数据目录的实例各过各的数据目录锁，
    但共享不了 8101——本探测是对数据目录锁的全局补充。
    探 /api/status?lite=1（lite 跳过全盘 detect，冷缓存实测 2.4s+ 会吃掉旧 2s
    超时 → 探活假阴性）。端口空闲时连接立即被拒，超时只作用于"引擎在但慢"的场景，
    缺省放宽到 10s；阶段 2 的引擎看护显式传更短的超时（判"僵死不响应"）。

    /api/status 的 data_dir 现只对带有效 Bearer token 的调用方
    回显，故本探测带上自己的 token（同安装/同 keyring → 同值）。若端口被"另一套
    token 的实例"占用（跨数据目录 + 无 keyring 的少见组合）→ 401：仍判为端口冲突
    （返回空串，目录未知），不误当空闲。
    """
    import httpx

    from app.net_util import DIRECT_LOOPBACK

    headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}
    try:
        # 同上：本机端点必须绕过系统代理（探测的是同一台机器上的另一个实例）。
        with httpx.Client(mounts=DIRECT_LOOPBACK, timeout=timeout) as cli:
            r = cli.get(f"http://127.0.0.1:{port}/api/status?lite=1",
                        headers=headers)
        if r.status_code == 200:
            return str(r.json().get("data_dir") or "")
        if r.status_code == 401:
            return ""
    except Exception:
        pass
    return None


def _local_api_thread(store: Store, port: int = LOCAL_API_PORT) -> threading.Thread:
    def run() -> None:
        from app.local_api import create_local_app

        import uvicorn

        app = create_local_app(store)
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        uvicorn.Server(config).run()

    t = spawn(run, name="experientia-local-api")
    return t


def start_servers(store: Store) -> int:
    """拉起代理 8100 + 本地 API 8101（后台线程），返回代理端口。GUI 与 headless 共用。

    W4-07 的规则迁移（`migrate_user_rules`）已挪进 `scan_loop` 首轮
    退避之后——本函数此前同步跑它，把一次性磁盘迁移压在了首帧之前的主线程上。
    """
    config = store.load_config()
    port = int(config.get("port", 8100))
    _proxy_thread(store, port)
    _local_api_thread(store)
    return port


def _startup_tasks(store: Store) -> None:
    """一次性启动任务：首轮退避之后、首轮 run_scan 之前跑，只跑一次。

    三件归一批：启动迁移（版本门控，-P1-8）/ embedding 模型下载/
    用户规则迁移（W4-07）。选「首轮退避后、run_scan 之前」而不是「第二轮」的理由：
    三件都是只跑一次的启动工作，聚合在一处时序可读；退避已保证 GUI 先画完首帧，
    再往后挪只会让"第一轮 run_scan 耗时较长"时迁移被推得更晚，无额外收益。
    每件各自兜底异常，绝不拦死引擎。
    """
    # 启动迁移（版本门控，-P1-8）：轻相同步跑（清库快照/证据入队），
    # 重相回采置旗标由循环内后台线程消化——迁移异常绝不拦死引擎
    try:
        from app.store.migrations import run_startup_migrations
        summary = run_startup_migrations(store)
        if not summary.get("skipped"):
            log.info("启动迁移完成: %s", summary)
    except Exception as exc:
        log.warning("启动迁移异常（引擎继续）: %s", exc)
    try:
        # embedding 模型自动下载：开关开 + 文件缺才起线程，
        # sha256 钉死校验，失败静默（BM25 降级一直在）
        from app.semantic.model_dl import spawn_model_download
        if spawn_model_download(store):
            log.info("embedding 模型后台下载已启动（首启一次性）")
    except Exception as exc:
        log.info("模型下载探测跳过: %s", exc)
    try:
        # W4-07：模板矩阵重设计的一次性规则迁移（幂等，无操作时零开销）
        from app.rules import migrate as _rules_migrate
        _rules_migrate.migrate_user_rules(store)
    except Exception as exc:
        log.warning("规则迁移失败（不影响启动）: %s", exc)


def _daily_growth_notices(store: Store) -> None:
    """成长档位扫描：磨合度升档（中/高）推 growth_report（每至多一天一次）。

    v2 口径：主句 = 磨合差值（基线前 3 次修正中位数 − 近 5 次
    中位数），不再用"第 3 次 vs 第 1 次"百分比（防小分母假数字）。"""
    from app import notify

    summary = store.growth_summary(days=30)
    aff = summary.get("affinity") or {}
    for key, old, new in notify.growth_edges(store, aff):
        a = aff.get(key) or {}
        # 展示走统一口径（旧写法对 3 段键会切出"其他/未分类"这种内部路径味串）
        cat = affinity_display(key)
        diff = int(a.get("diff") or 0)
        if a.get("excluded"):
            body = "基线本来就顺，经验未必帮上忙（中性提示）"
        elif diff >= 1:
            body = f"比最初几次平均少 {diff} 轮修正（近 5 次）"
        else:
            body = f"磨合度 {a.get('level', '')}（样本 {a.get('n', 0)} 次）"
        if a.get("sample_note"):
            body += f"（样本 {a.get('n', 0)} 次，结论仅供参考）"
        notify.push(store, "growth_report",
                    f"「{cat}」磨合度新高：{old} → {new}", body, target="growth")


def _daily_summary(store: Store) -> None:
    """21:00 今日总结（本地时区）：当日无积累不发（宁缺毋滥）。

    经验 ts 是 UTC（store.utcnow），必须换算到本地时区再比
    「今天」——此前直接截串比对，UTC+8 下 0-8 点产生的经验被记到前一天，
    21:00 总结漏计/错计。"""
    from app import notify

    today = datetime.now().date().isoformat()

    def _ts_local_date(ts) -> str:
        try:
            dt = datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return str(ts)[:10]
        return dt.replace(tzinfo=timezone.utc).astimezone().date().isoformat()

    exps = list(store.iter_experiences(include_distilled=True))
    new_exps = sum(1 for e in exps if _ts_local_date(e.get("ts")) == today)
    # 口径与首页账本一致：坑卡 = rule 源结构事实；
    # 新坑（被纠正经验）单列，两码事不再混一个词
    new_cards = sum(1 for e in exps if _ts_local_date(e.get("ts")) == today
                    and e.get("g_source") == "rule")
    new_fail = sum(1 for e in exps if _ts_local_date(e.get("ts")) == today
                   and (e.get("corrected") or float(e.get("G") or 0) < 0.5)
                   and e.get("g_source") != "rule")
    pending = len(list(store.iter_experiences()))
    if not (new_exps or new_fail or pending or new_cards):
        return
    notify.push(store, "daily_summary",
                f"今日总结：新增 {new_exps} 条经验 · {new_cards} 张坑卡 · "
                f"{new_fail} 条被纠正 · 待蒸馏 {pending} 条",
                "", target="home")


def daily_checks(store: Store) -> None:
    """每日通知（幂等，状态存 config notify_state，重启/跨天不重发）：
    成长档位扫描每日一次；今日总结 21:00（本地时区）后每日一次；
    sessions 保留期清理每日一次（低5，notifications 在 save 处顺手清）。"""
    from app import notify

    today = datetime.now().date().isoformat()
    st = notify.state_get(store, "daily") or {}
    # FLAG-1：常驻通知任务各自可关（config.features，缺省全开；不改变现有体验）
    run_growth = feature_enabled(store.load_config(), "growth_report")
    run_summary = feature_enabled(store.load_config(), "daily_summary")
    if st.get("pruned_date") != today:
        try:
            dropped = store.prune_sessions()
            if dropped:
                log.info("保留期清理：删除超期 session %d 条", dropped)
        except Exception as exc:
            log.warning("session 保留期清理失败: %s", exc)
        notify.state_patch(store, "daily", pruned_date=today)
    if run_growth and st.get("growth_date") != today:
        try:
            _daily_growth_notices(store)
        except Exception as exc:
            log.warning("成长通知检查失败: %s", exc)
        notify.state_patch(store, "daily", growth_date=today)
    if run_summary and st.get("summary_date") != today and datetime.now().hour >= 21:
        try:
            _daily_summary(store)
        except Exception as exc:
            log.warning("今日总结失败: %s", exc)
        notify.state_patch(store, "daily", summary_date=today)
    # 档 C：空闲后台整理——每日门 + 空闲 ≥2h + 当日已有会话结束（逾期时免）
    if feature_enabled(store.load_config(), "background_maintenance") \
            and st.get("maintenance_date") != today:
        ran = False
        try:
            from app.distill import maintenance
            ran = maintenance.should_run(store)
            if ran:
                maintenance.run(store)
        except Exception as exc:
            log.warning("档 C 整理检查失败: %s", exc)
            # 出错也盖章：否则每轮重试刷日志，而"执行失败"与"还没到点"是两回事
            ran = True
        # 日期门只在**真跑过**时盖章。跳过不盖章——否则跨天后的第一次检查若恰好
        # 不满足条件（0 点刚过、当日还没会话结束…），这一天就被废掉、再也不补跑。
        # 症状：maintenance.log 停在几天前，config 里 maintenance_date 却是今天。
        if ran:
            notify.state_patch(store, "daily", maintenance_date=today)
    # 周日结算：每周至多 1 条，并入 growth_report；成就顺延补发
    if feature_enabled(store.load_config(), "weekly_report"):
        try:
            from app.distill import weekly_report
            weekly_report.maybe_run(store)
        except Exception as exc:
            log.warning("周日结算失败: %s", exc)


def scan_loop(store: Store, proxy_port: int | None = None) -> None:
    """捕获 + 自动蒸馏 + 每日通知循环（阻塞）。

    proxy_port 非 None 时顺带监控代理（M-1）：每轮探测 /health，
    无响应则重拉（有上限）。启动前 PROXY_START_GRACE_SECONDS 内不探测——
    uvicorn 绑定 + 首包需要时间，立即探测会把正常启动误判为崩溃。
    """
    proxy_state = {"thread": None, "retries": 0, "warned": False}
    loop_start = time.time()
    # 首轮退避（只此一次），让 GUI 先画完首帧再跑扫描/迁移/模型下载
    time.sleep(SCAN_STARTUP_BACKOFF_SECONDS)
    _startup_tasks(store)
    while True:
        try:
            # 归档回采旗标（重相，分钟级）：起后台线程一次，跑完清旗标
            from app.store.migrations import spawn_backfill_if_pending
            spawn_backfill_if_pending(store)
            # 上轮队列满挂起的复盘，从落库记录恢复后再入队
            _drain_pending_reviews(store)
            # review=False：复盘进工作线程，扫描循环只做捕获 + 归档
            result = capture_scan.run_scan(store, verbose=False, review=False)
            if result.new_sessions:
                log.info("捕获: %s", result.new_sessions)
            _spawn_review(store, result.new_session_dicts)
            # M-2：auto_check 调模型最长 30 分钟，进工作线程不冻结循环
            # FLAG-1：档 B 自动蒸馏可关（config.features.auto_distill，缺省开）
            if feature_enabled(store.load_config(), "auto_distill"):
                _spawn_auto_check(store)
            daily_checks(store)
            # 经验 JSONL 快照导出（SQLite 为唯一事实源，JSONL 仅作备份/回退格式；
            # 脏计数达阈值才导出，未达零开销）。导出失败不影响循环。
            try:
                n = store.maybe_export_experience_snapshot()
                if n:
                    log.info("经验快照已导出：%d 条", n)
            except Exception as exc:
                log.info("经验快照导出跳过: %s", exc)
        except Exception as exc:
            log.warning("引擎循环异常（不杀常驻）: %s", exc)
        if proxy_port is not None and time.time() - loop_start > PROXY_START_GRACE_SECONDS:
            # 看护异常绝不杀常驻：探活/重拉在循环体外，一抛整个 scan_loop 就没了
            try:
                _watch_proxy(store, proxy_port, proxy_state)
            except Exception as exc:
                log.warning("代理看护异常（不杀常驻）: %s", exc)
        time.sleep(SCAN_INTERVAL_SECONDS)


def run_forever() -> None:
    from app.log_conf import setup_logging
    from app.store.store import cleanup_pending_data_dir, default_engine_log_file

    # 引擎落 engine.log（与 GUI 的 gui.log 分文件，避免两进程写同一文件
    # 时 RotatingFileHandler 轮转互踩）。
    setup_logging(log_file=default_engine_log_file())
    # GUI 拉起的引擎子进程带 EXPERIENTIA_PARENT_PID → 父进程关窗/崩溃后
    # 本进程随之退出（开机自启/手工 headless 无此 env，不受影响）。
    from app.platform.proc_util import PARENT_PID_ENV, start_parent_watch

    _parent = os.environ.get(PARENT_PID_ENV, "")
    if _parent.isdigit():
        start_parent_watch(int(_parent))
        log.info("父进程看护已启用：父 pid=%s（父退出则引擎退出，T2.1）", _parent)
    # 清理上次更换数据目录遗留的旧目录（引擎未启动，无文件锁）
    cleanup_pending_data_dir()
    store = Store()
    store.ensure_layout()
    # M-4 单实例：数据目录进程锁（OS 字节锁，进程死亡内核自动释放，无陈旧锁）
    from app.platform.engine_lock import EngineLock

    lock = EngineLock(store.data_dir)
    if not lock.acquire():
        log.error("已有 experientia 实例在运行（数据目录 %s），不启动重复引擎",
                  store.data_dir)
        sys.exit(1)
    from app.token_util import ensure_api_token
    _api_token = ensure_api_token(store.data_dir)
    running = probe_local_api(api_token=_api_token)
    if running is not None:
        log.error("本地 API 8101 已有活实例（数据目录 %s），端口冲突，放弃启动", running)
        sys.exit(1)
    # 引擎启动失败：记日志退出（更新回滚已移除，不再计失败次数）
    try:
        port = start_servers(store)
    except Exception as exc:
        log.critical("引擎启动失败: %s", exc)
        sys.exit(1)
    print(f"[experientia] 数据目录: {store.data_dir}", flush=True)
    print(f"[experientia] 代理端口: {port}  本地 API: {LOCAL_API_PORT}", flush=True)

    # 启动等待：/health 就绪前不进入扫描循环；~60s 仍不就绪（端口可能被占）
    # 记告警并继续——运行期崩溃由 scan_loop 的 _watch_proxy 负责重拉（M-1）。
    retry = 0
    while not _proxy_alive(port):
        time.sleep(2)
        retry += 1
        if retry > 30:
            log.warning("代理 %s 未能就绪（端口可能被占用）", port)
            break

    scan_loop(store, port)


def main() -> None:
    run_forever()


if __name__ == "__main__":
    main()
