# 多人网页版部署 · 0.8.0

保留原有像素风仪表盘，电脑一屏布局、手机纵向排列。网页通过 Flask + Waitress 连接原有 Python 预约模块，学校接口的场地、日期、时段仍然实时查询。

## 账号和运行方式

- 每位使用者直接公开注册一个**网站账号**，不需要邀请码，然后在「登录设置」导入自己的学校会话。网站密码与学校密码分开。
- 网页版不在服务器运行学校登录浏览器。用户从自己已登录的学校网站复制 Cookie、X-Access-Token、currentUser 和可选的 User-Agent，或上传完整凭据 JSON。先向学校验证，成功后才加密保存；失败保留旧会话。
- 每个网站账号拥有独立进程、会话密钥、数据目录、任务、订单、联系电话。首次成功绑定后只接受同一学校身份；同一学校账号不能绑定两个网站账号。
- Cookie / Token / 学校认证会话在服务器加密保存，不返回给网页。网站密码仅保存哈希；网站会话有效期为 7 天，可退出或通过修改密码撤销。
- 关闭网页、退出网站或修改网站密码**不会停止已启用任务**。停止任务需在任务列表操作；已有学校预约的取消和退款仍去学校网站处理。
- 学校认证续期沿用原模块。服务器不能保证学校 SSO 永不失效；扫码过期、额外认证、学校限制及防护更新仍可能需要人工重新登录。失败会显示具体任务状态，不伪装成成功。

当前是小规模单服务器版本，默认开放注册（QUEST_MAX_USERS=0），免费资源不代表无限并发。已验证两个真实后台进程的隔离与并发；尚未做大规模压力测试。不要运行多个网页主进程共享同一份数据，也不要用多副本部署。

## 本机预览

安装 Python 3.10+，推荐 3.12。在仓库根目录执行：

```sh
python start_web.py
```

Windows 也可以双击 `Start-Web-Windows.bat`；macOS 执行 `zsh Start-Web-macOS.command`。首次会创建独立虚拟环境并安装 Python 依赖。

打开 `http://127.0.0.1:18880`。直接注册自己的账号，无需邀请码。预览不复用本地旧版的学校会话。

如果手动安装了依赖，可直接运行：

```sh
python -m pip install -r requirements-web.txt
python -m badminton_reservation.web_server --data .quest-data --port 18880
```

本机 Windows 与 Railway Linux 启动已验证；macOS 新网页启动器待对应环境验证。网页版镜像不安装 Chromium 或 Xvfb。

## Linux 服务器：Docker Compose + HTTPS

需要：可运行 Docker Compose 的 Linux 服务器；一个指向服务器的域名；开放 80/443；服务器能够访问学校预约网站和统一认证。是否需要校园网/VPN 取决于学校访问策略，应在部署机器上实测。

先在仓库根目录准备公开网址：

```sh
cp .env.example .env
# 编辑 .env：QUEST_ORIGIN=https://你的域名
docker compose up -d --build
docker compose logs --tail=80 web
docker compose exec web cat /data/invite-code.txt
```

注册无需邀请码，保留登录限流和独立账号隔离。容器持久数据写入 `quest-data` 命名卷；不会读取仓库里的个人凭据。镜像使用非 root 用户，仅运行 Python 后台。

宿主机安装 Caddy 后，将 `deploy/Caddyfile.example` 中的域名替换为真实域名并合并到现有 Caddy 配置。配置示例：

```caddyfile
quest.example.com {
    reverse_proxy 127.0.0.1:18880
}
```

`QUEST_ORIGIN` 必须与浏览器实际访问的 **HTTPS 来源完全一致**，不带末尾斜杠或子路径。反向代理保留原始 `Host`。应用挂在域名根路径，不支持 `/quest/` 子目录。Compose 只把应用端口映射到宿主机回环地址，外部访问走 HTTPS 代理。

如果使用宝塔/Nginx，也可以反向代理到 `127.0.0.1:18880`，保留 `Host`，设置不低于 200 秒的上游读取超时，并启用 HTTPS。不要给学校登录和 API 配置响应缓存，也不要记录请求体、Cookie 或认证输入。

部署后依次检查：

1. 域名 `/healthz` 返回 `status: ok`，登录页可打开。
2. 使用邀请码注册两个账号，分别登录，任务列表、订单和联系电话互不可见。
3. 在「登录设置」打开学校页面，完成真实学校认证，保存本人的联系电话；检查会话和实时场地。
4. 先保存一个未启用的任务草稿，重启服务后确认仍在。预约和支付需要另行明确确认后才提交。

当前离线测试覆盖账号隔离、CSRF、网站登录撤销、学校身份绑定、凭据加密、重复请求阻止和真实子进程隔离。浏览器自动化使用模拟学校数据验证布局；**不代表服务器上的真实学校登录、预约或扣款已通过**。上线前必须使用用户自行导入的有效凭据，在实际服务器网络验证学校接口。

## 数据、更新与恢复

数据结构：

```text
/data/
  master.key                 # 服务器主密钥，必须与数据一起备份
  invite-code.txt            # 注册邀请码
  accounts.sqlite3          # 网站账号、绑定身份、会话、已受理操作编号
  users/<随机账号ID>/
    config/                  # 加密学校会话、独立预约配置和联系电话
    state/                   # 场地目录、预约任务和订单
```

只有学校会话加密；订单、电话、任务等业务数据依靠服务器文件权限保护。服务器管理员持有主密钥，可以管理这些数据。部署者应控制服务器和备份的访问权限。

更新代码前先备份，停止应用后备份**整个数据卷**（包括数据库及 WAL 文件、`master.key`），再更新并启动。不要单独复制一个正在写入的 SQLite 文件。不要执行 `docker compose down -v`，它会删除持久数据。密钥丢失无法恢复学校会话。

```sh
docker compose stop web
# 在此完成数据卷备份
git pull --ff-only
docker compose up -d --build
```

重启时自动恢复已经启用的任务，草稿不会启用。处于提交/付款未知状态的任务会沿用原来的查单恢复逻辑；不要删除订单或换一个操作编号强行重试付款。

默认不限制注册人数；可用 `web_server --max-users` 设置容量上限。每人独立 Python 进程，需按服务器内存规划实际活跃人数。当前不包含邮箱找回密码、管理员 UI、多机调度或高可用；网站密码应妥善保管。

## 常见问题

- **访问地址不匹配 / 请求来源校验失败**：检查域名、`QUEST_ORIGIN` 和代理传入的 `Host` 是否相同，修改环境后重新创建容器。
- **凭据导入失败**：检查 Cookie、Token 与 currentUser 来自同一次登录，检查有效期、DNS、服务器出口与学校防护限制。不要仅凭 HTTP 400 认定 Cookie 过期。
- **待查询 / 查询失败**：先在登录设置检查学校会话，再刷新场地；学校没有返回有效结果时不会显示为可预约。
- **多人同时失败**：检查服务器网络、资源与学校限制。邀请注册与请求有速率限制；代理后的认证限流默认按代理地址聚合，避免频繁反复尝试。
- **GitHub Pages**：只提供静态页面，不能运行这套 Python 后台、账号库和预约调度器。

参考：[Flask 的 Waitress 部署说明](https://flask.palletsprojects.com/en/stable/deploying/waitress/)。

## 手动获取会话

1. 在自己电脑的学校预约网站登录，F12 → Network，选择成功的学校 API 请求。
2. Request Headers 中复制完整 Cookie、X-Access-Token；建议同时复制 User-Agent。
3. Application → Local Storage → `https://resm.lzjtu.edu.cn`，复制 currentUser 的值。不要修改身份内容。
4. 在网页版「登录设置」填写并验证；也支持对应字段的凭据 JSON 文件。成功后输入框清空，服务器仅保留加密文件。
5. 只有额外导入有效 ssoCookies 时才能尝试学校统一认证续期；仅有预约 Cookie 不保证长期有效。过期后重新登录学校并导入。Cookie 也可能受来源 IP 等防护限制，云端验证失败需按实际返回排查。
