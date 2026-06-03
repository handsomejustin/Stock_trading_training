# 盘感训练器 - 升级服务部署说明

## 目录结构

```
server/
├── api/
│   ├── __init__.py
│   └── update.py           # Blueprint: /api/update/*
├── static/
│   └── releases/
│       ├── versions.json   # 版本注册表（手动维护）
│       └── *.zip           # 各版本发布包
└── README.md               # 本文件
```

## 接入现有 Flask 应用

在 stock.maolige.com 的 Flask app 中添加：

```python
import os
from flask import Flask

app = Flask(__name__)

# 注册升级 API Blueprint
from api.update import update_bp
app.register_blueprint(update_bp, url_prefix='/api/update')

if __name__ == '__main__':
    app.run()
```

## 发布新版本流程

1. 本地 `pyinstaller` 打包，生成 `dist/盘感训练器/` 目录
2. 压缩为 `盘感训练器-{版本号}-win-x64.zip`
3. 计算 SHA256：`certutil -hashfile xxx.zip SHA256`
4. 上传 zip 到 `static/releases/` 目录
5. 更新 `versions.json`：修改 `latest`，添加新版本条目
6. 重启 Flask（如使用 gunicorn/nginx）

## versions.json 字段说明

```json
{
  "latest": "最新版本号",
  "versions": {
    "版本号": {
      "release_date": "发布日期",
      "changelog": "更新说明（\\n 换行）",
      "platforms": {
        "平台标签": {
          "url": "下载路径（相对于站点根目录）",
          "sha256": "ZIP 文件 SHA256 哈希",
          "size": "文件字节数"
        }
      }
    }
  }
}
```

支持的平台标签：`win-x64`, `win-arm64`, `mac-arm64`, `mac-x64`, `linux-x64`, `linux-arm64`

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/update/check?platform=win&arch=x64&version=1.1.2` | GET | 检查更新 |
| `/api/update/changelog?from=1.1.0&to=1.1.2` | GET | 版本间 changelog |
