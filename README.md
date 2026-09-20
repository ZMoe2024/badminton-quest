# 羽球训练家 · Badminton Quest

Python 羽毛球预约工具与像素风本地仪表盘。支持实时场地查询、学校账号登录、定时预约、候补和订单查询，提供可选的校园卡支付流程。

当前版本为 **0.7.2 本地单用户版**。多人服务器版和微信小程序尚未实现。

## 启动

安装 Python 3.10+（推荐 3.12），下载并解压代码后进入 `badminton_reservation` 文件夹：

- Windows：双击 `Start-Windows.bat`。
- macOS：双击 `Start-macOS.command`，或在终端执行 `zsh Start-macOS.command`。

首次启动联网安装依赖和登录浏览器，完成后打开本地界面。每位使用者需登录自己的学校账号并填写预约联系电话。

完整部署、登录和运行说明见 [使用说明](badminton_reservation/docs/DISTRIBUTION.md)。Mac 尚未实机验证。

## 开发与测试

在仓库根目录执行：

```sh
python -m pip install -r badminton_reservation/requirements.txt
python -m unittest discover -s badminton_reservation/tests
python badminton_reservation/build_release.py
```

测试使用模拟数据，不提交真实预约或付款。打包结果位于 `badminton_reservation/dist`。

## 个人数据

仓库仅包含空白配置、场地目录和测试数据，不包含实际 Cookie、Token、个人联系方式、订单或启用的任务。运行产生的个人配置和状态保存在本机；不要将这些文件提交到 GitHub。

学校认证会话仍可能过期；关机、休眠、断网会中断自动任务。支付需使用者明确授权，余额充足的真实扣款不能以模拟测试代替验证。
