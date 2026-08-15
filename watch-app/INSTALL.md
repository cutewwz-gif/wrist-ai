# 腕上 AI 手表 App 安装

## APK

构建产物：

- `watch-app/app/build/outputs/apk/debug/app-debug.apk`
- 根目录副本：`腕上AI-debug.apk`

## 使用前

1. 打开 http://antony.fan/wristai/ 登录
2. 复制「设备密钥」
3. 手表打开 App → **设置** → 粘贴密钥 → 保存 → 测试连接

默认服务器：`http://antony.fan/wristai`

## OPPO Watch SE 安装

1. 手表：关于 → 连点版本号 → 打开开发者选项 / USB 调试  
2. 手表放上充电座，连电脑  
3. 电脑执行：

```bat
adb devices
adb install -r 腕上AI-debug.apk
```

若 SE 无法侧载，需换可装第三方 APK 的表，或走官方商店流程。

## 重新构建

```bat
cd watch-app
set GRADLE_USER_HOME=%USERPROFILE%\.gradle-wristai
gradle assembleDebug
```

（路径含中文时需 `android.overridePathCheck=true`，已写入 `gradle.properties`。）
