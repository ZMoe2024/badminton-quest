# Railway 部署

此版本支持从 GitHub 仓库部署到 Railway。真实登录与内存占用仍需要在 Railway 环境验收；免费额度并不保证足够整月运行。不要为试运行开通付费套餐。

1. New Project → GitHub Repository，选择 `ZMoe2024/badminton-quest`。仓库根目录保留为空，不要填 `badminton_reservation`。`railway.json` 自动指定 Dockerfile 和健康检查。
2. 给该服务添加 Volume，挂载路径 **`/data`**。没有持久卷时，程序会拒绝在 Railway 启动，防止重启丢失账户、密钥、任务和订单。
3. 添加变量：

   | 变量 | 值 |
   | --- | --- |
   | `RAILWAY_RUN_UID` | `0` |
   | `QUEST_MAX_USERS` | `0`（开放注册，不限制注册人数；实际并发受资源限制） |

   Railway 卷初始归 root 所有；入口仅调整 `/data` 的目录权限，随后降权为 `quest` 用户运行。主程序不以 root 运行；网页版不安装或启动浏览器。

4. Settings → Networking → Generate Domain。程序读取 Railway 提供的域名和 `PORT`。生成域名后如未自动重新部署，执行 Redeploy。使用自定义域名时另设 `QUEST_ORIGIN=https://你的域名`。
5. 保持单实例、单地区，不启用 Serverless/自动休眠，否则关闭网页后定时任务可能停下。部署日志与 `/healthz` 正常后打开网址，直接注册，再用本地登录提取脚本复制并导入自己的学校会话。

网页版使用本地登录脚本提取并由用户主动粘贴会话，也保留手动导入，详见 [连接步骤](WEB_DEPLOYMENT.md#获取学校会话)。Railway 运行环境曾拒绝 Chromium sandbox 初始化，因此已移除服务器浏览器依赖，减少镜像和内存占用。仅有网站能打开，不代表真实学校查询、预约或支付已验证。

免费内存不足时会出现 OOM/重启；需要降低账号数量或改用更合适的运行环境。重启不能解决资源不足，也不能把失败当成预约成功。

CLI 部署需要先 `railway login`。注册不需要邀请码；不需要把本机旧版的任何 Cookie、Token 或个人配置上传。GitHub 提交仅含程序和演示截图。

参考：[Railway 持久卷](https://docs.railway.com/volumes)、[健康检查与端口](https://docs.railway.com/deployments/healthchecks)、[环境变量](https://docs.railway.com/variables/reference)。

## 本次部署验证（2026-09-20）

已验证 Linux 容器启动、持久卷权限、HTTPS 健康检查、无需邀请码注册、个人后台启动、缺失凭据拒绝、退出后会话撤销。临时测试账号已清理。测试没有导入真实学校会话，没有创建预约或支付；27 块场地来自随包目录，实时可用状态仍需使用用户自己的有效会话查询。
