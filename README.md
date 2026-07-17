# Music Metadata Perfecter

面向 Windows 的本地 MP3 / FLAC 元数据编辑器。它使用 PyQt6 提供中文桌面界面，可在同一工作流中整理本地标签、比较 MusicBrainz 与 Apple Music / iTunes 元数据、选择封面，并在保存后撤销或重做文件修改。

> 本项目会直接修改音频文件。正式整理曲库前，请先用少量副本熟悉保存、专辑同步和撤销行为，并保留独立备份。

## 功能

- 扫描所选目录顶层的 `.mp3` 和 `.flac` 文件，不递归进入子目录。
- 编辑标题、艺术家、专辑、专辑艺术家、作曲家、音轨号、碟号、日期、流派、注释和封面。
- 同时检索 MusicBrainz 与 Apple Music / iTunes，并比较、切换整套候选来源。
- 从 Apple 与 Cover Art Archive 获取封面，也支持剪贴板粘贴和画廊选择。
- 支持多文件编辑、临时专辑、字段锁和受约束的专辑字段同步。
- 内置本地音频预览。
- 使用 `Ctrl+Z` / `Ctrl+Y` 撤销或重做编辑状态和已保存文件的受管元数据。
- 提供 NCM 转换、转换结果移动、NCM 永久删除和 `.lrc` 清理工作流。
- 生成带版本号的运行日志、元数据搜索日志和封面搜索日志，便于定位问题。

## 下载与运行

Windows x64 预构建版本发布在 [GitHub Releases](https://github.com/xjr353171020/music-metadata-perfecter/releases/latest)。

1. 下载 `Music-Metadata-Perfecter-v<version>-windows-x64.zip` 并解压到可写目录。
2. 运行其中的 `Music-Metadata-Perfecter-v<version>.exe`。
3. 首次启动后打开设置，选择主曲库目录和 VIP / NCM 下载目录。
4. 建议先用测试文件确认读取、保存和撤销结果，再处理正式曲库。

程序会在 EXE 同目录保存 `settings.json`，并在 `runtime_logs/` 下写入运行日志。升级时请保留自己的 `settings.json`，但不要把它提交到 Git 或公开分享。

未签名的个人构建可能触发 Windows SmartScreen 提示。请只从本仓库 Release 页面下载，并自行核对发布页提供的 SHA-256。

## 配置

| 设置 | 用途 |
| --- | --- |
| `MAIN_MUSIC_DIR` | 主曲库目录；只加载该目录顶层的 MP3 / FLAC |
| `VIP_DOWNLOAD_DIR` | NCM 转换、移动和歌词清理工作流使用的下载目录 |
| `DEEPSEEK_API_KEY` | 可选；只用于在已有 Apple 艺术家名称候选之间裁决，不会生成新的元数据 |

`DEEPSEEK_API_KEY` 可通过同名环境变量提供。若在设置窗口中填写，它会以明文写入本机 `settings.json`。

## 数据安全

- 保存会直接写回音频文件；当前没有保存预览、事务级自动回滚或持久化撤销日志。
- 单文件保存可能根据专辑身份、勾选字段和锁状态同步同一专辑的其他曲目。
- 撤销 / 重做历史只存在于内存中，重启应用或重新加载目录后会清空。
- 恢复已保存修改前会检查文件是否被外部程序改动；冲突文件不会被静默覆盖。
- NCM 转换默认保留原始 NCM；永久删除 NCM、移动音频和清理 `.lrc` 无法由编辑器撤销。
- 音频文件本身不会上传，但搜索词和相关元数据会发送给所选外部 Provider。
- 调试日志可能含本地路径和音乐元数据，分享前请先检查；API Key 不应出现在日志、截图或 issue 中。

## 从源码运行

当前开发与发布验证环境为 Windows x64 + Python 3.12。仓库没有承诺其他 Python 或操作系统版本的兼容性。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

首次运行仍需在应用设置中选择自己的目录。仓库中的机器本地设置、日志、音频和构建产物均由 `.gitignore` 排除。

## 构建 Windows 发布包

先安装运行与构建依赖，然后调用仓库提供的 PowerShell 脚本。脚本从 `config.APP_VERSION` 读取版本，生成单文件 GUI EXE、仅包含该 EXE 的 ZIP，以及 SHA-256 校验文件。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 `
  -PythonPath .\.venv\Scripts\python.exe
```

产物位于 `dist/`：

```text
Music-Metadata-Perfecter-v<version>.exe
Music-Metadata-Perfecter-v<version>-windows-x64.zip
Music-Metadata-Perfecter-v<version>-SHA256SUMS.txt
```

构建会将仓库内的 `Ncm拖一拖.exe` 嵌入应用。不要把 `dist/settings.json`、日志或整个 `dist/` 目录直接打入 Release。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

`test_metadata_restore.py` 会在临时目录中生成真实 MP3 / FLAC 并验证保存与恢复；它需要 `ffmpeg` 位于 `PATH`，否则相关类会跳过。外部网络请求在自动测试中使用 mock，因此测试通过不代表 MusicBrainz、Apple、Cover Art Archive 或 DeepSeek 的实时服务始终可用。

## 已知限制

- 应用面向 Windows，当前界面以简体中文为主。
- 只处理配置目录顶层的 MP3 / FLAC。
- NCM 转换、文件移动、永久删除和歌词清理目前同步执行，较大任务可能短暂阻塞界面。
- Provider 结果受网络、限流、地区商店和上游接口变化影响。
- 保存计划没有用户可见的 dry-run；部分文件失败时不会自动回滚已经成功的文件。
- 撤销 / 重做不跨应用重启持久化。

## 开发文档

- [架构与数据流](docs/ARCHITECTURE.md)
- [调试指南](docs/DEBUGGING_GUIDE.md)
- [模型交接说明](docs/MODEL_HANDOFF.md)

## 许可证

仓库目前尚未声明软件许可证。第三方库和随仓库提供的工具仍受各自许可证约束；在复用或再分发前，请先核对相应条款。
