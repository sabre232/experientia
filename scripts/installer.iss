; ============================================================================
; Experientia 安装包脚本（Inno Setup 6.3+，ISCC.exe 编译）
; ----------------------------------------------------------------------------
; 构建（推荐，会自动带上版本号）：
;     python scripts\build_installer.py
; 手动：
;     ISCC.exe /DMyAppVersion=1.0.0 scripts\installer.iss
;
; 前置：必须先跑 scripts\build_package.py 生成 dist\Experientia\（onedir 产物），
;       本脚本把那个目录整体压成单个 setup.exe。
;
; 路径说明：本文件位于 scripts\ 下，故源路径一律用 ..\ 回到仓库根。
; ============================================================================

#ifndef MyAppName
#define MyAppName "Experientia"
#endif
#ifndef MyAppVersion
#define MyAppVersion "0.0.0-dev"
#endif
#ifndef MyAppPublisher
#define MyAppPublisher "Experientia"
#endif
#define MyAppExeName "Experientia.exe"

[Setup]
; --- AppId 是安装身份的唯一键 ------------------------------------------------
; 控制面板的卸载项、升级识别（装新版本时认出旧版本）、per-user/全局切换，全凭它。
; 首次发布后**永远不要改**：改了系统会把它当成另一款软件——旧版卸不掉、
; 新版装成第二份，两个副本会共抢 ~/.experientia 数据目录。
;
; 写法警告：**首尾花括号数不对称是正常的，别"修"对称**。
; Inno 把 `{{` 当转义（转成一个字面 `{`），而单个 `}` 本身就是字面量，
; 所以想得到 `{GUID}` 必须写成 `{{GUID}`。
;  实测踩过：原先写成 `{{GUID}}`，编译不报错、装也装得上，
; 但注册表里的卸载键变成了 `{GUID}}_is1`（尾巴多一个括号）。
AppId={{7B3E5C21-9A4D-4F6B-8E2A-1C5D9F0A6B34}

AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
AppPublisher={#MyAppPublisher}

; --- 安装位置 ----------------------------------------------------------------
; 默认 Program Files（需要管理员）；用户可在向导里改路径。
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
UsePreviousAppDir=yes

; PySide6 6.x 官方只支持 Windows 10/11，故把门槛设在这里——在 Win7/8 上直接
; 拒绝安装，比装完跑不起来更诚实。
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; 默认装给所有用户（Program Files，需要管理员）。加上 OverridesAllowed=dialog 后，
; 向导首页会多一个"为谁安装"的选择页：没有管理员权限的用户可以选"仅我"，
; 装到 %LOCALAPPDATA%\Programs 且不弹 UAC。
; 之所以能这样放开，是因为下面的目录常量用的都是 {autopf} / {autodesktop} 这种
; "自动"版本——Inno 会按实际权限模式自动解析成全局或当前用户路径，不用手写两套。
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; --- 输出 -------------------------------------------------------------------
; 产物落在 dist\ 根下，与待打包的 dist\Experientia\ 目录互不干扰。
OutputDir=..\dist
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon_windows.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; --- 许可页 -----------------------------------------------------------------
; 展示仓库根的 LICENSE（BUSL-1.1 双授权说明，5 KB）：它讲清了"个人/非商用走
; AGPL 免费、闭源集成走 BUSL 需授权"这件事，是用户真正需要看到的那一层。
; 不直接展示 LICENSE-AGPL（33 KB 法务全文）——那份由 LICENSE 指向，并随包一起
; 分发（见 [Files]），需要时用户自己翻。
LicenseFile=..\LICENSE

; 安装时若 Experientia 正在运行，先关掉它，否则 {app} 下的文件会因占用而复制失败。
CloseApplications=yes
RestartApplications=no

[Languages]
; 简体中文语言文件不在 winget 那个 Inno 安装的语言集里（它只装了 29 个、缺中文），
; 因此把官方那份（jrsoftware/issrc 的 Files/Languages/ChineseSimplified.isl）收进
; 仓库 scripts\languages\ 随版本管理：构建不再依赖网络，也不会因为某台机器装的
; Inno 版本不同而缺语言。
; 用 FileExists 守卫：万一这份文件丢了，自动退回纯英文向导，而不是编译直接失败。
; SourcePath 是 ISPP 提供的"当前脚本所在目录"，用它拼绝对路径，不依赖编译器的 CWD。
Name: "english"; MessagesFile: "compiler:Default.isl"
#if FileExists(SourcePath + "\languages\ChineseSimplified.isl")
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; onedir 产物整体搬进安装目录。recursesubdirs 负责把 _internal\（PySide6、Python
; 运行时、assets）等子目录一并带上；Excludes 挡掉字节码缓存（打包机上的 .pyc
; 进了用户机器只会让人困惑）。
Source: "..\dist\Experientia\*"; DestDir: "{app}"; \
    Excludes: "*.pyc,*.pyo"; Flags: recursesubdirs createallsubdirs ignoreversion

; 以下三份随包分发（不注册、不显示，纯粹让人拿到）：
;   LICENSE-AGPL —— AGPL 选项的完整条款。GPL 系许可证的分发义务之一是
;                    " recipients 必须能拿到许可证全文"，只给 5 KB 的摘要页不够。
;   LICENSE      —— 双授权说明（安装向导展示的就是这份，这里再放一份纯文本）。
;   README_zh.md —— 中文说明。
Source: "..\LICENSE-AGPL"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README_zh.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
; 开始菜单里的卸载入口。Inno 不会自动加这条，必须显式写。
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
; 桌面快捷方式，受 [Tasks] 里的 desktopicon 复选框控制。
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 装完默认勾选"立即运行"。skipifsilent 保证 /SILENT 静默安装时不弹程序。
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

; 没有 [UninstallDelete] 是刻意的：按项目铁律，产品运行期只写 ~/.experientia/，
; 不往安装目录写任何东西（日志、缓存都在用户目录），所以卸载时安装目录里不会有
; 需要额外清理的残留。若哪天有人打破了这条铁律，这里就要补对应清理项。
