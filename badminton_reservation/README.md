# 羽球训练家 0.7.2 · Windows / macOS 通用包

完整本地浏览器界面 + Python 预约、定时、候补和校园卡支付模块。解压后启动本机服务，浏览器打开 `http://127.0.0.1:18765`。首次运行会安装依赖和 Chromium 登录浏览器（数百 MB），需要联网；之后启动复用已安装组件。无需 Node.js、Chrome 调试插件或 EXE。

## 第一次启动

新版本登录组件按 [Playwright 官方系统要求](https://playwright.dev/python/docs/intro#system-requirements) 以 Windows 11+、macOS 14+ 为支持目标；旧系统不保证兼容。

1. 安装 **Python 3.10 或更新版本**，推荐 Python 3.12。Windows 安装时勾选 Add Python to PATH。Mac 使用 python.org 的 **macOS 64-bit universal2** 安装包，可用于 Apple Silicon / Intel。下载：<https://www.python.org/downloads/>。
2. 将 ZIP **完整解压**到自己可写的文件夹，例如“文稿/BadmintonQuest”。不要直接在压缩包里运行，也不要放到系统只读目录。
3. Windows 双击 **`Start-Windows.bat`**；Mac 双击 **`Start-macOS.command`**。第一次安装依赖可能需要几分钟，完成后自动打开界面。
4. 保持启动终端运行。停止时在终端按 **Ctrl+C**；仅关闭浏览器不会停止后台任务。

如果 Mac 不允许双击脚本，打开终端输入 `cd `，将解压文件夹拖入终端，再按回车；随后运行：

```sh
zsh Start-macOS.command
```

如果需要恢复可执行权限，可在该文件夹执行 `chmod +x Start-macOS.command`。不需要关闭系统安全设置。

也可直接执行 `python3 launcher.py`（Windows 使用 `py -3 launcher.py`）。依赖和虚拟环境只安装在本文件夹的 `.venv` 中，不修改系统 Python 包。不要在不同电脑间复制 `.venv`。

## 登录和预约资料

发布包不带任何人的登录凭据、联系电话、订单或自动预约任务。

1. 首次运行自动打开「登录设置」，点击 **登录学校账号**。
2. 程序使用普通 Chrome/Chromium 启动独立临时窗口，先打开预约网站并完成页面初始化，再由网站跳转学校统一认证（修复旧启动方式导致的 HTTP 400 白屏）。在新开的独立浏览器窗口里，使用**自己的学校账号**完成扫码或其他认证，并进入预约网站首页。程序不填写密码、不代做验证码，不读取日常浏览器的资料。
3. 程序自动采集预约会话和当前用户信息，以及可取得的学校认证 Cookie；使用 Python 验证通过后加密保存，并自动关闭临时登录窗口。最长等待10分钟。失败、取消或关闭窗口时保留原会话；成功保存后再关闭窗口不撤销已保存结果。
4. 在同一页面填写并保存自己的 **预约联系电话**，无需编辑配置文件。预约身份从已登录的账号读取。
5. 回到「场地探索」刷新目录、日期和时段后使用。随包目录仅用于初始展示，占用和能否预约必须实时查询。自动任务仍需另行确认启用；登录不会启动预约或付款。

一般不需要手动复制 Cookie。已有凭据 JSON 时可展开「高级选项：手动导入会话」，结构见 `config/credentials.example.json`。当原账号有未完成的自动任务时禁止切换到其他账号，应先停止等待任务或核实结果未知的原订单。

登录窗口优先使用已安装的 Chrome，否则使用随启动器安装的 Chromium；始终创建独立临时会话，不使用个人浏览器配置。底层组件用法参见 [Playwright 官方浏览器文档](https://playwright.dev/python/docs/browsers)。

Windows 会话使用当前用户 DPAPI 加密，保存在 `config/session.dpapi`；Mac 会话加密保存在 `config/session.keychain`，密钥保存在当前用户的 macOS 钥匙串。Mac 首次访问可能请求钥匙串授权；请在准备无人值守前完成授权并检查登录。实现使用系统 Keychain 后端，参见 [keyring 官方文档](https://keyring.readthedocs.io/en/stable/)。

这些加密会话不能靠复制文件跨机器解密；换电脑后点击登录按钮重新登录即可。高级导入用的原始 JSON 是明文，请妥善保管，验证完成后可删除。扫码、密码或验证码由使用者在学校页面完成。

## 定时、候补与支付

- 支持预约尚未开放时预先设置日期、时间和候选场地；候选按顺序尝试，只成功一块。
- 「保存草稿」不会运行；确认启用才开始后台处理。新发布包任务列表为空。
- 所有预约和执行时间按北京时间 UTC+8，与 Mac 当前系统时区无关。
- 自动支付默认关闭；开启需要设置金额上限，按订单实际金额付款。
- 有任务时检查会话并尝试学校认证续期。**学校统一认证自身也过期时，仍需人工登录，不能保证无限保活。**
- 关闭程序、关机、断网或休眠会影响执行。Mac 双击启动器使用系统 `caffeinate -i` 防止运行期间的空闲休眠；**合盖、手动休眠、退出登录仍可能中断**。保持开盖、接电和网络。Windows 请自行设置运行时不休眠。
- 提交或支付结果未知时先核查原记录，不自动重发；不要删除记录来绕过重复保护。取消和退款在学校网站操作。

历史记录在 `state/attempts`、`state/orders`、`state/payments`；自动预约任务在 `state/automation`。不要同时在两台电脑启用相同预约任务，本地重复保护不跨电脑共享。

## 更新、迁移和排错

- 本包的数据保存在解压文件夹内。更新前停止旧程序、保留整个旧文件夹备份；不要直接覆盖或删除原 `config` 和 `state`。
- 同机更新可将旧包的 `config` 和 `state` 复制到新包，再从新包启动；不要复制 `.venv`。恢复的已启用任务可能继续执行，更新前先在界面停止不希望继续的任务。
- 换机需重新完成学校登录；如转移历史记录，请同时保留 `state/attempts`、`state/orders` 和 `state/payments`，不要只复制订单列表。
- 端口被其他程序使用时：`python3 launcher.py --port 18766`。检测到已有羽球训练家服务时会打开该服务；运行新版本前先停止旧版本。
- 启动失败先看终端错误。可重命名 `.venv` 后重启以重新安装依赖，不要删除 `config` 或 `state`。
- 运行离线安装检查（不登录、不预约）：首次安装后，Mac 执行 `.venv/bin/python launcher.py --check`；Windows 执行 `.venv\Scripts\python.exe launcher.py --check`。
- 离线测试：Mac 执行 `.venv/bin/python -m unittest discover -s tests -v`，Windows 把 Python 路径换成 `.venv\Scripts\python.exe`。

## 验证范围

本次发布在 Windows 验证了 104 项离线测试、干净解压后的启动和界面资源。登录采集在真实独立 Chrome 中用拦截的模拟学校响应验证，覆盖 HttpOnly Cookie、Token、用户信息、加密保存、取消和验证失败保留旧会话，并检查临时浏览器目录已清理。2026-09-18 已由使用者完成真实学校登录：预约首页及 cas.html 返回 HTTP 200，程序采集会话并通过 Python 验证后加密保存；关闭登录窗口后，再次从保存文件检查会话也成功。若学校页面持续返回错误且空白，会提示失败并保留旧会话。macOS 会话加密逻辑使用模拟钥匙串测试，Mac 启动脚本和 POSIX 路径已检查；**没有在真实 Mac 上完成启动、钥匙串授权或预约支付实测**。Apple Silicon / Intel 使用各自 Python 安装依赖，本包不包含平台专属二进制。

本次打包不发起真实预约或支付。已有业务流程验证到余额不足分支，余额充足时的成功扣款仍不能以离线测试代替实测。
