# 电影元数据刮削

桌面程序：扫描自己的视频目录，从文件名解析 IMDb id 或番号，按顺序查询勾选的网站，下载海报、背景和演员头像，写成 Emby / Jellyfin / Kodi 能读的电影 NFO。入口只有 `app.py`，它打开窗口。

## 和 Movie Data Capture / MDCx 的关系

工作流受到 Movie Data Capture / MDCx 启发：本地扫描、从文件名得到番号、拉元数据、下图片、写 NFO、可选按演员和番号整理。

本仓库是另行编写的，不是那些项目的分支，也没有复制它们的源码。

## 网站

「网站」页是一个可勾选的顺序列表，用上移 / 下移调整。勾选的网站从上到下查询，番号或标题对不上就换下一个，不会拿另一部充数。第一个严格匹配的结果胜出。某个站失败只记一行，然后继续。全都失败时，仍按文件名写一份简单 NFO。

默认顺序：JavDB、JavBus、TMDB、IMDb 开；DMM、AVSOX、MGStage、FC2 关。

- 番号站（JavDB、JavBus、DMM、AVSOX、MGStage、FC2）：页面上的番号必须和文件名一致（忽略大小写、空格、连字符）。对不上就丢掉。文件名没有番号时，这些站一共只记一行并跳过。FC2 只用文件名里的 FC2 编号。
- 标题站（TMDB、IMDb）：标题去掉标点和年份后必须相同。文件名有年份就必须对上。同名有好几年、文件名又没写年份时，不猜测，日志写「有多部同名，文件名里没有年份」。文件名没有标题时跳过标题站；文件名里的 `tt` id 仍按 id 查。
- TMDB 需要自己的 API Key。勾选了但没填 Key 时，日志写「TMDB 已勾选但没有 API Key，已跳过」，不访问网络。
- 站点返回验证页、年龄验证或 403 时记下状态并换下一个，不会绕过。

代理可空，只支持 `http://` 或 `https://`。socks 会提示并改为直接连接。「跳过已有 NFO」「简介翻译为中文」默认开。简介里没有汉字时才翻译，失败保留原文。

旧的 `priority` 和单独的 javdb / tmdb / imdb 开关会在读取配置时并进 `sites`。

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

窗口有两个标签：「刮削」（媒体目录、旁边写文件 / 按演员/标题复制、开始、停止、进度、日志）和「网站」。这台 Debian 如果缺少 Qt 的系统库，程序会在导入前从 `~/.local/qt-libs` 加载。Windows 的 PySide6 自带 Qt，不需要这一步。

命令行仍然可用：`python3 app.py --cli --media 目录`。`--web` 不是主界面。

```bash
python3 -m unittest discover -s tests
```

## 会写出哪些文件

不读取视频内容，只看文件名。支持 mkv、mp4、avi、wmv、ts、m2ts、iso、rmvb、flv、mov。扫描时跳过 `failed`、`.actors` 和点开头的目录。不删除、不移动原视频。

两种模式都在 nfo 旁边写：

- `{视频名}.nfo`（不会改成 `movie.nfo`）
- `poster.jpg`、`fanart.jpg`、`thumb.jpg`
- 有剧照才写 `extrafanart/extrafanart-N.jpg`，最多 20 张
- 每位演员一个 `<actor><name>`。页面给了头像时，再下载到旁边的 `.actors/演员名.jpg`（png / webp 保留原扩展名）。没有头像也照样写名字。

复制模式的目录是 `输出目录/第一位演员/番号或标题/`，里面是复制来的原文件名视频。没有演员时是 `输出目录/番号或标题/`。已有同名 nfo 默认跳过，不覆盖。
