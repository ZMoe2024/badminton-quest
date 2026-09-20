# Railway 部署

此版本支持从 GitHub 仓库部署到 Railway。真实登录与内存占用仍需要在 Railway 环境验收；免费额度并不保证足够整月运行。不要为试运行开通付费套餐。

1. New Project → GitHub Repository，选择 `ZMoe2024/badminton-quest`。仓库根目录保留为空，不要填 `badminton_reservation`。`railway.json` 自动指定 Dockerfile 和健康检查。
2. 给该服务添加 Volume，挂载路径 **`/data`**。没有持久卷时，程序会拒绝在 Railway 启动，防止重启丢失账户、密钥、任务和订单。
3. 添加变量：

   | 变量 | 值 |
   | --- | --- |
   | `RAILWAY_RUN_UID` | `0` |
   | `QUEST_MAX_USERS` | `2`（免费内存先做两人试运行，实测后再调整） |
   | `QUEST_INVITE_CODE` | 自己设置一串随机的注册邀请码，不要写进公开代码 |

   Railway 卷初始归 root 所有；入口仅调整 `/data` 的目录权限，随后降权为 `quest` 用户运行。主程序和 Chromium 不以 root 运行，也不会关闭浏览器 sandbox。

4. Settings → Networking → Generate Domain。程序读取 Railway 提供的域名和 `PORT`。生成域名后如未自动重新部署，执行 Redeploy。使用自定义域名时另设 `QUEST_ORIGIN=https://你的域名`。
5. 保持单实例、单地区，不启用 Serverless/自动休眠，否则关闭网页后定时任务可能停下。部署日志与 `/healthz` 正常后打开网址，用邀请码注册，再登录自己的学校账号。

浏览器登录全站同一时刻只开放一个窗口，降低小内存实例的峰值；其他人的普通任务仍分开执行。Chromium 登录窗口在结束/取消后清理，不常驻。首次先检查学校登录与实时场地，不要以网站能打开代替完整预约验收。

免费内存不足时会出现 OOM/重启；需要降低账号数量或改用更合适的运行环境。重启不能解决资源不足，也不能把失败当成预约成功。

CLI 部署需要先 `railway login`。邀请码可以设在 Railway Variables 中，不需要把本机旧版的任何 Cookie、Token 或个人配置上传。GitHub 提交仅含程序和演示截图。

参考：[Railway 持久卷](https://docs.railway.com/volumes)、[健康检查与端口](https://docs.railway.com/deployments/healthchecks)、[环境变量](https://docs.railway.com/variables/reference)。
