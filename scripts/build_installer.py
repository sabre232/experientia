"""生成 Windows 安装包（Inno Setup）。

用法（仓库根）：
    python scripts/build_package.py     # 第一步：先出 onedir 产物 dist\\Experientia\\
    python scripts/build_installer.py   # 第二步：压成单个 setup.exe

产物：dist/Experientia-Setup-<版本>.exe

本脚本负责四件容易被忘掉的事：
  1. **前置校验**——`dist/Experientia/Experientia.exe` 不存在就直接报错并提示
     先跑 build_package.py，而不是让 Inno 打出一个空壳安装包。
  2. **强制带上瘦身步骤**——自动调用 `scripts/prune_dist.py`（幂等）。这一步
     必须在压缩之前做，否则那约 7 MB 用不到的 Qt 资产会被一起压进安装包。
      实测：漏跑它，打出来的 setup.exe 白胖 7 MB，而且没有任何报错。
  3. **版本号不手抄**——从 `app/version.py` 读 VERSION，作为 `/DMyAppVersion`
     传给 ISCC。installer.iss 里的版本号由此注入，不会和代码漂移。
  4. **定位 ISCC.exe**——依次试 PATH 和几个常见安装路径；找不到时给出安装命令，
     而不是甩一句 "ISCC 不是内部或外部命令"。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "scripts" / "installer.iss"
PRUNE = ROOT / "scripts" / "prune_dist.py"
ZH_LANG = ROOT / "scripts" / "languages" / "ChineseSimplified.isl"
PAYLOAD_EXE = ROOT / "dist" / "Experientia" / "Experientia.exe"


def _find_iscc() -> str | None:
    """ISCC.exe 全路径；找不到返回 None。"""
    found = shutil.which("ISCC")
    if found:
        return found
    # winget / 官方安装包的常见落点（用户级装的话在 LOCALAPPDATA 下）
    candidates = [
        Path.home() / "AppData/Local/Programs/Inno Setup 6/ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _maybe_sign(exe: Path) -> bool:
    """：代码签名管线——**默认休眠，不配证书就只提示**。

    配齐下面任一组合即自动启用（CI 用 secrets 注入）：
      - `SIGN_CERT_PFX`（base64 的 PFX 内容）+ 可选 `SIGN_CERT_PASS`
      - 或 `SIGN_CERT_THUMBPRINT`（用本机证书库里的证书）
    强烈建议同时配 `SIGN_TIMESTAMP_URL`（RFC3161 时间戳服务器）——否则证书
    过期后已发布的安装包会集体失效。

    未配置 / 找不到 signtool：打印一句提示后返回 False，**不影响出包**
    （保持 v1.0"未签名发布"的口径不变，SmartScreen 提示由 README 说明应对）。
    """
    import base64
    import os
    import tempfile

    pfx_b64 = os.environ.get("SIGN_CERT_PFX") or ""
    thumb = (os.environ.get("SIGN_CERT_THUMBPRINT") or "").strip()
    if not pfx_b64 and not thumb:
        print("[信息] 未配置签名证书（SIGN_CERT_PFX / SIGN_CERT_THUMBPRINT）"
              " → 本包不签名")
        return False
    tool = shutil.which("signtool")
    if not tool:
        for c in (Path(r"C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe"),
                  Path(r"C:\Program Files (x86)\Windows Kits\10\App Certification Kit\signtool.exe")):
            if c.exists():
                tool = str(c)
                break
    if not tool:
        print("[警告] 配了签名证书但找不到 signtool.exe → 跳过签名（包仍产出）",
              file=sys.stderr)
        return False

    cmd = [tool, "sign", "/fd", "sha256", "/d", "Experientia",
           "/du", "https://github.com/"]
    tmp_pfx: Path | None = None
    if pfx_b64:
        fd, name = tempfile.mkstemp(suffix=".pfx")
        with os.fdopen(fd, "wb") as fh:
            fh.write(base64.b64decode(pfx_b64))
        tmp_pfx = Path(name)
        cmd += ["/f", str(tmp_pfx)]
        pwd = os.environ.get("SIGN_CERT_PASS") or ""
        if pwd:
            cmd += ["/p", pwd]
    else:
        cmd += ["/sha1", thumb]
    ts = (os.environ.get("SIGN_TIMESTAMP_URL") or "").strip()
    if ts:
        cmd += ["/tr", ts, "/td", "sha256"]
    cmd.append(str(exe))

    print("[信息] 正在签名", exe.name)
    proc = subprocess.run(cmd, cwd=ROOT)
    if tmp_pfx is not None:
        try:
            tmp_pfx.unlink()
        except OSError:
            pass  # 临时 PFX 删不掉也不影响产物（含私钥，尽力删）
    if proc.returncode != 0:
        print(f"[警告] 签名失败（退出码 {proc.returncode}）——包仍产出但未签名",
              file=sys.stderr)
        return False
    print("[完成] 已签名", exe.name)
    return True


def main() -> int:
    if not PAYLOAD_EXE.exists():
        print(f"[错误] 找不到 {PAYLOAD_EXE}", file=sys.stderr)
        print("       请先跑：python scripts/build_package.py", file=sys.stderr)
        return 1

    iscc = _find_iscc()
    if not iscc:
        print("[错误] 找不到 ISCC.exe（Inno Setup 编译器）", file=sys.stderr)
        print("       安装：winget install --id JRSoftware.InnoSetup"
              " --accept-source-agreements --accept-package-agreements",
              file=sys.stderr)
        return 1

    # 瘦身必须在压缩之前——它是"给包体减重"，不是"给已压好的包减重"。
    # prune_dist.py 自带幂等：目标目录不在时静默跳过，所以重复跑没有副作用。
    if PRUNE.exists():
        print(f"[信息] 先跑 {PRUNE.name} 清理 Qt 冗余资产（幂等）")
        subprocess.run([sys.executable, str(PRUNE)], cwd=ROOT)
    else:
        print(f"[警告] 找不到 {PRUNE.name}，跳过瘦身 → 包体会偏大约 7 MB",
              file=sys.stderr)

    # installer.iss 里那份中文语言文件是从官方仓库收进仓库的（不是 Inno 自带的），
    # 它一旦丢失，向导会静默退回纯英文——这里显式提醒一句。
    if not ZH_LANG.exists():
        print(f"[警告] 缺 {ZH_LANG.relative_to(ROOT)}"
              " → 安装向导将只有英文，不会报错", file=sys.stderr)

    sys.path.insert(0, str(ROOT))
    from app.version import VERSION

    print(f"[信息] ISCC       = {iscc}")
    print(f"[信息] 版本号     = {VERSION}")
    print(f"[信息] 待打包产物 = {PAYLOAD_EXE.parent}")

    cmd = [iscc, f"/DMyAppVersion={VERSION}", str(ISS)]
    print(">", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        print(f"[错误] Inno Setup 编译失败，退出码 {proc.returncode}", file=sys.stderr)
        return proc.returncode

    out = ROOT / "dist" / f"Experientia-Setup-{VERSION}.exe"
    if out.exists():
        # 签名是**可选收尾**——配了证书才签；失败/未配都不阻断出包
        _maybe_sign(out)
        print(f"[完成] {out}  ({out.stat().st_size / 1024 / 1024:.1f} MB)")
        return 0
    print(f"[警告] 编译报成功但没找到预期产物：{out}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
