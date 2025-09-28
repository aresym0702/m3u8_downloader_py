### **M3U8下载工具参数说明**

**注意身体**

| 参数 | 类型 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `-u` | str | 是 | \- | M3U8下载地址（http(s)://url/xx/xx/index.m3u8） |
| `-n` | int | 否 | 24 | 下载线程数 |
| `-ht` | str | 否 | v1 | 设置getHost的方式（v1: http(s)://host/path; v2: http(s)://host） |
| `-o` | str | 否 | movie | 自定义文件名（不带后缀） |
| `-c` | str | 否 | "" | 自定义请求cookie |
| `-r` | str | 否 | y | 是否自动清除ts文件（y/n） |
| `-s` | int | 否 | 0 | 是否允许不安全的请求（0/1） |
| `-sp` | str | 否 | "" | 文件保存的绝对路径（默认为当前路径） |
| `-retry` | int | 否 | 3 | 下载失败重试次数 |
| `-retry-delay` | int | 否 | 2 | 重试延迟时间（秒） |

**使用示例**：

`python m3u8_downloader.py -u "https://example.com/video/index.m3u8" -n 16 -o my_video -c "session=123" -sp "/path/to/save" `
