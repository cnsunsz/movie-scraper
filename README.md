# 电影元数据刮削

桌面程序：扫描自己的视频目录，从文件名解析 IMDb id 或番号，按顺序查询勾选的网站，下载海报、背景和演员头像，写成 Emby / Jellyfin / Kodi 能读的电影 NFO。入口只有 `app.py`，它打开窗口。

## 和 Movie Data Capture 的关系

工作流受到 [Movie_Data_Capture](https://github.com/mvdctop/Movie_Data_Capture) 启发：本地扫描、从文件名得到番号、拉元数据、下图片、写 NFO、按演员/番号整理、代理与简介翻译等。

本仓库是另行编写的 MIT 项目，不是那些项目的分支，也没有复制它们的源码。桌面界面按商业 MDC 8.0.6 的布局自行用 PySide6 实现（无登录、无到期）。

## 界面

顶部导航：

| 页 | 作用 |
| --- | --- |
| **运行** | 深色日志区与进度 |
| **完成项目信息** | 最近一次刮削的成功 / 失败 / 跳过摘要 |
| **本地配置** | **一般影片 / 其他影片** 切换、共用目录与代理、本类型网站顺序、命名规则、排除、翻译、TMDB Key |
| **自定义刮削** | 单文件刮削、名称提取测试 |
| **演员** | Emby / Jellyfin 连接测试；Gfriends 或本地库补全缺失头像 |
| **语言** | 目前仅简体中文说明 |

底部常驻：**帮助**、**刷新**、**名称提取测试**、**停止**、绿色 **开始**。

## 一般影片 / 其他影片

「本地配置」顶部可切换 **一般影片** 与 **其他影片**（`film_type`: `general` | `other`）。两类各自保存网站顺序、命名规则、翻译与排除等；刮削源目录、输出目录、代理、TMDB Key 共用。旧版扁平 `config.json` 会迁移进「其他影片」，并自动生成「一般影片」默认项。

- **一般影片** 默认网站：TMDB、IMDb 开，Jav* 关；文件夹规则 `genres+'/'+title`，文件命名 `title.year`。
- **其他影片** 默认网站：JavDB、JavBus、TMDB、IMDb 开；DMM、AVSOX、MGStage、FC2 关；文件夹 `actor+'/'+number`，文件 `number+'-'+title`。

命名规则支持 token：`title` / `original_title` / `actor` / `studio` / `director` / `release` / `year` / `number` / `tag` / `genres` / `runtime` / `series` / `prefix` / `letter` / `season` / `episode` / `suffix`（`outline` 不进路径）。支持 `genres/title`、`actor/[number]-title`、`title.year` 与 `+` 引号拼接。安全解析，不使用 `eval()`。

## 网站

「本地配置」里是可勾选的顺序列表（按当前影片类型），用上移 / 下移调整。勾选的网站从上到下查询，番号或标题对不上就换下一个，不会拿另一部充数。第一个严格匹配的结果胜出。

- 番号站（JavDB、JavBus、DMM、AVSOX、MGStage、FC2）：页面上的番号必须和文件名一致。
- 标题站（TMDB、IMDb）：标题去掉标点和年份后必须相同；有年份就必须对上。
- TMDB 需要自己的 API Key。
- 代理可关；开启后按 `http://地址:端口` 使用。仅支持 http/https。

「主运行模式」对齐 MDC：`1` 整理+改名移动、`1_keep` 保留原名移动、`2` 仅位置规则移动、`4` 原地刮削、`5` 原地刮削并重命名。整理方式支持移动与软链接（硬链接/strm 暂不支持）。

## 怎么运行

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Windows：

```bat
py -m pip install -r requirements.txt
py app.py
```

命令行：`python3 app.py --cli --media 目录`。`--web` 不是主界面。

```bash
python3 -m unittest discover -s tests
```

推送到 `master` 后 GitHub Actions 会按仓库根目录的 `VERSION` 编译单文件 `MovieScraper.exe`，并发布：

- **版本化 Release**（如 `v0.4.0`）：正式归档，同一版本号不可重复发布；若 tag 已存在，工作流会失败，请先提高 `VERSION`。
- **`latest` Release**：始终覆盖为当前最新 exe，旧下载链接仍可用。

窗口标题与「语言」页会显示当前版本。下载：

- 最新：https://github.com/cnsunsz/movie-scraper/releases/latest
- 指定版本：https://github.com/cnsunsz/movie-scraper/releases

## 会写出哪些文件

不读取视频内容，只看文件名。支持 mkv、mp4、avi、wmv、ts、m2ts、iso、rmvb、flv、mov。扫描时跳过 `failed`、`.actors` 和点开头的目录。不删除原视频（移动模式会改名并移动）。

两种模式都在 nfo 旁边写：

- `{视频名}.nfo`
- `poster.jpg`、`fanart.jpg`、`thumb.jpg`
- 有剧照才写 `extrafanart/extrafanart-N.jpg`
- 每位演员一个 `<actor><name>`；有头像时下载到 `.actors/演员名.jpg`

配置不会在 exe 旁自动生成。界面提供「加载配置 / 保存 / 另存为」；CLI 用 `--config 路径`（可选 `--save-config`）。关闭窗口且未保存则丢弃本次修改。不要把含密钥的配置提交进仓库。
