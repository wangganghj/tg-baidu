# tg-baidu 🎬 百度网盘智能转存与 TMDB 媒体重命名 Telegram 机器人

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED.svg" alt="Docker">
  <img src="https://img.shields.io/badge/TMDB-v3%2Fv4-01d277.svg" alt="TMDB">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
</p>

`tg-baidu` 是一个现代化的 Telegram 机器人，通过百度网盘开放平台（OpenAPI / OAuth2）协议与 TMDB（The Movie Database）媒体数据库集成。

当你在 Telegram 中发送百度网盘分享链接时，机器人会自动解析链接、清洗文件名中的广告信息并在 TMDB 中匹配影视条目，根据 **Plex / Emby / Jellyfin** 媒体库命名规范自动重命名并归档保存到指定的百度网盘目录中。

---

- 🌐 **现代化 Web 管理控制台 (Web UI Dashboard)**：
  - **百度 OAuth 登录**：网页一键跳转百度网盘授权登录与自动回调，支持查看账户头像、SVIP 会员等级与容量使用进度条。
  - **网盘目录可视化选择器**：在网页端直接浏览百度网盘云端目录树，支持一键将指定目录设为电影/剧集保存位置并新建文件夹。
  - **系统与 Bot 配置中心**：在网页端可视化修改 Bot Token、TMDB Key、刮削语言、重命名模板，并提供 TMDB 接口实时测试搜索。
  - **转存与重命名历史**：清晰直观的任务列表，展示原文件名 ➡️ TMDB 识别影视 ➡️ 百度网盘目标重命名路径的完整日志。
  - **网页快捷转存**：支持在 Web 界面直接粘贴分享链接进行测试与转存。
- 🤖 **Telegram 交互式体验**：
  - 自动识别消息中的百度网盘分享链接与提取码（支持各种复杂/带有说明文字的格式）。
  - 支持 Inline Keyboard 按钮交互确认（快速确认识别、切换电影/剧集分类、查看多候选结果、取消操作）。
  - 实时推送转存、重命名与归档进度及结果概览。
- 🎬 **TMDB 智能影视刮削与匹配**：
  - 内置基于 `guessit` 与定制正则的中文广告清洗算法（去除“关注公众号”、“压制组标签”、“无水印”等干扰字符）。
  - 智能识别电影与电视剧（季、集、年份、分辨率 4K/1080P 等）。
  - 支持多语言刮削（默认中文 `zh-CN`），自动抓取剧集单集标题。
- 📂 **Plex / Emby / Jellyfin 规范化整理**：
  - **电影格式**：`/Media/Movies/奥本海默 (2023)/奥本海默 (2023) [2160P].mkv`
  - **剧集格式**：`/Media/TV/繁花 (2023)/Season 01/繁花 - S01E01 - 第一集.mp4`
  - 支持在配置文件中自定义重命名模板。
- ☁️ **百度网盘开放平台 (OpenAPI) 深度集成**：
  - 标准 OAuth 2.0 授权流程与 Token 自动续期。
  - 支持账号状态与容量配额查询（`/status`）。
  - 支持批量创建文件夹、重命名与移动操作。
- 🐳 **开箱即用与容器化**：
  - 默认开放 `8080` 端口访问 Web 控制台，提供完整 `Dockerfile` 与 `docker-compose.yml`。
  - 使用 SQLite 本地持久化保存授权令牌、用户偏好与任务历史。

---

## 🏗️ 架构设计

```mermaid
flowchart LR
    User([Telegram 用户]) <-->|发送分享链接 / 命令| Bot[Telegram 机器人]
    Bot <--> Parser[文件名清洗 & 媒体解析器]
    Parser <--> TMDB[TMDB API 刮削服务]
    Bot --> TaskQueue[异步任务管理器]
    TaskQueue --> Baidu[百度网盘 OpenAPI 客户端]
    Baidu <--> Netdisk[(百度网盘存储)]
```

---

## 🚀 快速开始

### 准备工作

在使用前，你需要准备以下三样凭证：

1. **Telegram Bot Token**：通过 Telegram 联系 [@BotFather](https://t.me/BotFather) 创建机器人并获取 Token。
2. **TMDB API Key**：在 [TMDB 官网](https://www.themoviedb.org/settings/api) 申请免费 API Key（或 Read Access Token）。
3. **百度网盘开放平台应用**：
   - 访问 [百度网盘开放平台 (Union)](https://pan.baidu.com/union/) 创建应用。
   - 获取 `AppKey` (Client ID) 与 `AppSecret` (Client Secret)。
   - 在应用回调地址中填入 `oob` 或 `https://openapi.baidu.com/oauth/2.0/login_success`。

---

### 方式一：Docker Compose 部署（推荐）

1. **克隆项目并进入目录**：
   ```bash
   git clone https://github.com/your-username/tg-baidu.git
   cd tg-baidu
   ```

2. **创建配置文件**：
   ```bash
   cp config.example.yaml config.yaml
   ```
   编辑 `config.yaml` 填入你的配置信息：
   ```yaml
   telegram:
     bot_token: "YOUR_TELEGRAM_BOT_TOKEN"
     allowed_user_ids: [123456789]  # 填入你的 Telegram User ID
     admin_user_id: 123456789

   tmdb:
     api_key: "YOUR_TMDB_API_KEY"
     language: "zh-CN"

   baidu:
     app_key: "YOUR_BAIDU_APP_KEY"
     app_secret: "YOUR_BAIDU_APP_SECRET"
     redirect_uri: "oob"

   media:
     movie_dir: "/Media/Movies"
     tv_dir: "/Media/TV"
   ```

3. **启动容器**：
   ```bash
   docker-compose up -d
   ```

4. **查看日志**：
   ```bash
   docker-compose logs -f
   ```

---

### 方式二：本地 Python 运行

1. **安装 Python 3.10+ 环境**。
2. **安装依赖**：
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **配置 `config.yaml`**（同上）。
4. **启动机器人**：
   ```bash
   python3 -m tg_baidu.main -c config.yaml
   ```

---

## 🌐 Web 控制台使用指南

服务启动后，在浏览器访问 **`http://localhost:8080`** 即可进入 Web 管理面板。

### 1. 百度网盘授权绑定
- 点击 **【🔑 网页一键授权登录百度】**，页面会自动引导至百度开放平台授权页，授权后自动回调绑定。
- 也可以通过手动输入页面返回的 **Code 授权码** 提交完成绑定。
- 绑定后控制台实时展示网盘总容量、已用空间百分比与 VIP 等级。

### 2. 百度网盘目录可视化选择
- 切换至 **【📁 网盘目录选择器】** 标签页。
- 页面将实时读取云端网盘的文件夹结构，点击任意文件夹可进入下级目录。
- 点击 **【🎬 设为电影目录】** 或 **【📺 设为剧集目录】** 即可完成路径指定，同时支持在网盘中直接新建文件夹。

### 3. Telegram 机器人与 TMDB 设置
- 切换至 **【⚙️ 机器人与系统设置】** 标签页。
- 可视化修改与保存 Telegram Bot Token、管理员 ID、TMDB API Key 与刮削语言。
- 提供 TMDB 搜索实时测试框，可立即验证 API Key 是否有效。
- 可自定义电影与剧集的 Plex/Emby 重命名模板。

### 4. 任务与重命名历史
- 切换至 **【📋 转存与重命名历史】** 标签页。
- 查看所有任务的状态（等待中、处理中、已完成、失败）与文件处理进度。
- 点击 **【详情】** 可展开查看原文件名与整理后生成的目标网盘路径对照日志。

---

## 📱 Telegram 机器人使用指南

### 1. 账号授权绑定 (Bot 方式)

1. 在 Telegram 中向机器人发送 `/start`。
2. 发送 `/login` 命令，机器人会返回百度 OAuth2 授权链接。
3. 在浏览器中打开链接完成登录与授权，复制页面显示的 **授权码 (Code)**。
4. 在 Telegram 中发送：
   ```text
   /code <你的授权码>
   ```
5. 机器人提示绑定成功，并显示当前网盘容量与账号信息。

### 2. 发送链接转存与整理

直接在聊天中发送百度网盘分享链接，例如：
```text
链接: https://pan.baidu.com/s/1abcdEFG12345 提取码: 8888 繁花.2023.4K.WEB-DL.H265
```

机器人将自动：
1. 提取链接和提取码 `8888`。
2. 检索 TMDB 并展示海报与匹配信息。
3. 点击 **【✅ 确认识别并转存】**。
4. 后台自动将文件转存至百度网盘临时目录，随后按照 TMDB 规则移动并重命名至 `/Media/TV/繁花 (2023)/Season 01/...`。

### 3. 可用命令列表

| 命令 | 说明 |
| :--- | :--- |
| `/start` | 欢迎信息与快速指引 |
| `/help` | 查看详细帮助信息 |
| `/login` | 获取百度网盘 OAuth2 授权绑定链接 |
| `/code <授权码>` | 提交授权码完成账号绑定 |
| `/status` | 查询百度网盘空间容量、会员状态与配置信息 |
| `/settings` | 交互式修改个人偏好（自动转存开关、目录等） |
| `/tasks` | 查看最近转存与整理任务的历史状态 |
| `/search <关键词>` | 手动在 TMDB 搜索影视条目与详情 |

---

## ⚙️ 高级配置项说明

在 `config.yaml` 中支持以下高级配置：

```yaml
media:
  # 电影重命名模板
  # 支持变量: {title}, {year}, {resolution}, {video_codec}, {audio_codec}, {ext}
  movie_format: "{title} ({year})/{title} ({year}) [{resolution}].{ext}"

  # 剧集重命名模板
  # 支持变量: {title}, {year}, {season:02d}, {episode:02d}, {episode_title}, {resolution}, {ext}
  tv_format: "{title} ({year})/Season {season:02d}/{title} - S{season:02d}E{episode:02d} - {episode_title}.{ext}"

  # 自动转存开关 (开启后识别到匹配项立即执行，无需按钮确认)
  auto_transfer: false

  # 转存并整理完成后是否自动删除临时转存文件夹
  cleanup_temp_dirs: true

system:
  # 最大并发处理任务数
  max_concurrent_tasks: 3
  # 日志级别: DEBUG, INFO, WARNING, ERROR
  log_level: "INFO"
```

---

## 🧪 单元测试

运行单元测试套件：
```bash
python3 tests/run_tests.py
# 或使用 pytest
pytest -v
```

---

## 📄 开源许可证

本项目采用 [MIT License](LICENSE) 开源许可证。
