# tg-baidu 🎬 Telegram Bot for Baidu Netdisk Share Transfer & TMDB Renaming

`tg-baidu` is a Telegram bot that connects to your Baidu Netdisk account via Baidu Open Platform (OAuth2 / OpenAPI). When you send a Baidu Netdisk share link in Telegram, the bot parses the link, queries TMDB for accurate media metadata, renames the media files according to **Plex / Emby / Jellyfin** standards, and organizes them into your designated Baidu Netdisk media directories.

---

## ✨ Key Features

- **🌐 Web Management Dashboard (Port 8082)**:
  - **Baidu OAuth2 Integration**: One-click OAuth login, auto callback redirect, real-time storage quota bar & VIP status.
  - **Netdisk Directory Browser & Picker**: Browse remote cloud folders visually, create new folders, and set destination folders for Movies/TV shows with 1 click.
  - **Bot & TMDB Settings Panel**: Live configuration for Bot Token, TMDB API Key, language, rename templates, and interactive TMDB search testing.
  - **Task & Renaming History**: View transfer progress, file rename logs (original name ➡️ TMDB Plex path).
  - **Web Quick Transfer**: Submit Baidu share links directly from the web interface.
- **🤖 Telegram Interface**:
  - Automatically captures Baidu Netdisk share links and extraction passwords.
  - Interactive Inline Keyboards (Confirm, Switch Movie/TV, Manual Search, Cancel).
  - Real-time progress updates and completion notifications.
- **TMDB & Media Parsing**:
  - Cleans ad watermarks, group tags, and release noise from filenames.
  - Automatic Movie vs. TV series detection with season and episode recognition.
  - Generates standard Plex / Emby compatible directory structures.
- **Baidu Netdisk Open Platform**:
  - Full OAuth2 authorization with automatic token refresh.
  - Remote directory creation, batch moving, and renaming directly in Baidu Netdisk.
  - Storage quota & user status inquiry.
- **Docker Support**:
  - Production-ready `Dockerfile` and `docker-compose.yml`.

---

## 🚀 Quick Start with Docker

1. **Clone repository**:
   ```bash
   git clone https://github.com/your-username/tg-baidu.git
   cd tg-baidu
   ```

2. **Configure `config.yaml`**:
   ```bash
   cp config.example.yaml config.yaml
   ```
   Fill in your Telegram Bot Token, TMDB API Key, and Baidu AppKey/AppSecret.

3. **Start container**:
   ```bash
   docker-compose up -d
   ```

---

## 📄 License

MIT License.
