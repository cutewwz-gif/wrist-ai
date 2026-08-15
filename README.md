# 腕上 AI

OPPO Watch 小方屏聊天 App + `antony.fan` 上的 AutoDL 代理服务端。

## 目录

- `watch-app/` — Android 手表客户端
- `server/` — FastAPI 控制台与聊天代理（`/wristai`）
- `scripts/` — 部署/SSH 辅助脚本（密码用环境变量，不要写进仓库）

## 服务端

1. 把 `server/` 部署到机器，参考 `server/wristai.service`
2. 设置环境变量 `WRISTAI_PASSWORD`
3. 打开 `http://你的域名/wristai/`，登录后填写 AutoDL 令牌
4. 手表使用控制台里的「设备密钥」请求 `/wristai/api/chat`

## 手表 App

用 Android Studio 打开 `watch-app/`，或：

```bash
cd watch-app
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

安装后在设置里填写服务器地址与设备密钥。

## 安全

- 不要提交 AutoDL API Key、设备密钥、管理密码
- `server/data/`、`local.properties`、`*.apk` 已在 `.gitignore` 中忽略
