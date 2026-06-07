# 闻涨知行指数波动提醒

这个小脚本会监控：

- 上证指数
- 沪深300
- 创业板指
- 纳斯达克综合指数
- 标普500

任一指数相对上一交易日收盘价涨跌幅达到 `±1%` 时，会发送钉钉机器人通知。

## 1. 配置环境变量

把下面两项替换成你的钉钉机器人信息：

```bash
export DINGTALK_WEBHOOK='https://oapi.dingtalk.com/robot/send?access_token=你的token'
export DINGTALK_SECRET='SEC你的加签密钥'
export INDEX_ALERT_THRESHOLD='1.0'
```

## 2. 发送测试消息

```bash
cd /Users/pengjunqu/Documents/Codex/2026-06-07/new-chat/outputs/index-alert
INDEX_ALERT_TEST=1 python3 index_alert.py
```

## 3. 手动检查一次

```bash
cd /Users/pengjunqu/Documents/Codex/2026-06-07/new-chat/outputs/index-alert
python3 index_alert.py
```

## 4. 定时运行

### macOS 或 Linux 的 crontab

每小时运行一次：

```cron
0 * * * * cd /Users/pengjunqu/Documents/Codex/2026-06-07/new-chat/outputs/index-alert && /usr/bin/env DINGTALK_WEBHOOK='你的Webhook' DINGTALK_SECRET='你的Secret' INDEX_ALERT_THRESHOLD='1.0' python3 index_alert.py >> index_alert.log 2>&1
```

### 云服务器

把整个 `index-alert` 文件夹上传到云服务器，然后配置同样的 crontab。这样你的电脑关机后，服务器仍然可以推送。

### GitHub Actions

如果你没有云服务器，可以把这个文件夹上传到一个 GitHub 私有仓库。仓库里需要包含：

```text
index_alert.py
.github/workflows/index-alert.yml
```

然后在 GitHub 仓库页面进入：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

添加两个 Secret：

```text
DINGTALK_WEBHOOK
DINGTALK_SECRET
```

工作流会每小时自动运行一次。也可以在 GitHub 的 `Actions -> Index Alert -> Run workflow` 手动测试。

## 说明

- 脚本只使用 Python 标准库，不需要安装第三方依赖。
- 脚本会在同一交易日内避免对同一指数、同一方向重复提醒。
- 行情源使用 Yahoo Finance 图表接口。若行情源临时不可用，脚本会在日志里输出错误。
