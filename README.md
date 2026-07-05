# Podcast Studio

📚 书籍转播客流水线 — 上传书籍文件，自动生成双人辩论式中文播客

## 功能特性

- **书籍解析**: 支持 PDF、EPUB、TXT、DOCX、HTML 等格式
- **双人辩论**: 自动生成主持人（阿哲）与评论员（老K）的对话体剧本
- **TTS 合成**: 7 种 TTS 引擎支持，中文语音合成（edge-tts/espeak-ng）
- **音频后处理**: FFmpeg 专业级音频拼接与响度归一化
- **REST API**: 完整的播客管理 API
- **RSS Feed**: 自动生成播客订阅源
- **抖音式首页**: 知识卡片流，每本书一张精选洞察卡片

## 项目结构

```
podcast-studio/
├── api_server.py        # Flask REST API 服务器
├── config.py            # 配置管理
├── utils.py             # 工具函数
├── middleware.py        # 中间件
├── _shared.css          # 共享样式
├── _shared.js           # 共享前端 JS
├── index.html           # 首页（知识卡片流）
├── studio.html          # 工作室（上传与生成）
├── library.html         # 播客库
├── player.html          # 播放器
├── docs.html            # 使用文档
├── routes/              # API 路由模块
│   ├── api.py           # 核心 API
│   └── static.py        # 静态文件路由
├── tests/               # 测试套件
│   └── test_api_server.py
└── podcast-output/      # 生成的播客（自动排除）
```

## 快速启动

```bash
# 启动服务器
python3 api_server.py

# 访问
http://localhost:8080
```

## 技术栈

- 后端: Python 3 + Flask
- 前端: 原生 HTML/CSS/JS
- TTS: edge-tts / espeak-ng
- 音频处理: FFmpeg
- 测试: pytest (140 tests)

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/sessions` | GET | 播客项目列表 |
| `/api/session/:id` | GET | 项目详情 |
| `/api/engines` | GET | TTS 引擎列表 |
| `/api/download/:id/:file` | GET | 音频下载 |

## License

MIT