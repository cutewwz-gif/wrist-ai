# 腕上 AI

OPPO Watch 小方屏 **AI 聊天 App** + 自托管 **FastAPI 代理服务端**（对接 AutoDL 大模型 API）。

## 功能

- 手表端简洁聊天 UI，适配小屏阅读
- Web 管理控制台：配置 AutoDL 令牌、模型、系统提示词
- 设备密钥鉴权，手表通过 `/wristai/api/chat` 流式对话
- Markdown 自动转纯文本，方便手表显示
- 一键部署脚本（SSH 密码通过环境变量，不写进仓库）

## 目录

```
├── watch-app/          # Android 手表客户端（Kotlin）
├── server/             # FastAPI 控制台 + 聊天代理
│   ├── app.py
│   └── wristai.service   # systemd 示例
├── scripts/            # 部署 / SSH 辅助脚本
└── watch-app/INSTALL.md  # 手表安装详细说明
```

## 服务端部署

1. 将 `server/` 部署到 Linux 机器，参考 `server/wristai.service`
2. 设置环境变量：

   | 变量 | 说明 |
   |------|------|
   | `WRISTAI_PASSWORD` | 管理控制台登录密码（**生产环境必设**） |

3. 安装依赖并启动：

   ```bash
   cd server
   pip install -r requirements.txt
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```

4. 打开 `http://你的域名/wristai/`，登录后在控制台填写 **AutoDL API Key** 与模型名称
5. 复制控制台中的 **设备密钥**，供手表 App 使用

### API 概览

| 路径 | 说明 |
|------|------|
| `GET /wristai/` | Web 管理控制台 |
| `POST /wristai/api/chat` | 手表聊天接口（需 `X-Device-Key` 头） |

## 手表 App

### 构建

用 Android Studio 打开 `watch-app/`，或命令行：

```bash
cd watch-app
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

详细安装步骤见 [watch-app/INSTALL.md](watch-app/INSTALL.md)（含 OPPO Watch SE 侧载说明）。

### 配置

安装后在 App **设置** 中填写：

- **服务器地址**：如 `http://你的域名/wristai`
- **设备密钥**：从 Web 控制台复制

## 部署脚本

`scripts/` 目录提供 SSH 部署辅助（`deploy_wristai.py` 等）。使用时设置环境变量，**不要**在脚本或仓库中硬编码密码：

```powershell
$env:SSH_PASSWORD = "your_password"
python scripts/deploy_wristai.py
```

## 安全

- 不要提交 AutoDL API Key、设备密钥、管理密码
- `server/data/`、`local.properties`、`*.apk` 已在 `.gitignore` 中忽略
- 生产环境务必设置 `WRISTAI_PASSWORD`，不要使用默认占位值

## License

MIT
