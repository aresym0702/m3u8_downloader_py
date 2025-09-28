import os
import re
import sys
import time
import argparse
import requests
from urllib.parse import urlparse, urljoin
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

# 常量定义
HEAD_TIMEOUT = 5  # 请求超时时间(秒)
TS_NAME_TEMPLATE = "%05d.ts"  # TS文件命名模板
DEFAULT_RETRY_TIMES = 3  # 默认重试次数
RETRY_DELAY = 2  # 重试延迟时间(秒)

# 全局变量
logger = None
ro = {
    "headers": {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36",
        "Connection": "keep-alive",
        "Accept": "*/*",
        "Accept-Encoding": "*",
        "Accept-Language": "zh-CN,zh;q=0.9, en;q=0.8, de;q=0.7, *;q=0.5"
    },
    "timeout": HEAD_TIMEOUT,
    "verify": True
}

class TsInfo:
    """TS文件信息类"""
    def __init__(self, name, url):
        self.name = name
        self.url = url

def init_logger():
    """初始化日志"""
    global logger
    logger = open("download.log", "a", encoding="utf-8")
    logger.write(f"\n===== 新会话开始: {time.strftime('%Y-%m-%d %H:%M:%S')} =====")

def get_host(url, host_type):
    """获取M3U8地址的host"""
    parsed_url = urlparse(url)
    if host_type == "v1":
        return f"{parsed_url.scheme}://{parsed_url.netloc}{os.path.dirname(parsed_url.path)}"
    elif host_type == "v2":
        return f"{parsed_url.scheme}://{parsed_url.netloc}"
    return ""

def get_m3u8_body(url):
    """获取M3U8文件内容"""
    try:
        logger.write(f"\n获取M3U8内容: {url}")
        response = requests.get(url, **ro)
        response.raise_for_status()
        logger.write(f" - 成功 (状态码: {response.status_code})")
        return response.text
    except Exception as e:
        error_msg = f"获取M3U8内容失败: {str(e)}"
        tqdm.write(error_msg)  # 使用tqdm.write避免打断进度条
        logger.write(f"\n{error_msg}")
        return ""

def resolve_nested_m3u8(base_url, m3u8_body):
    """解析嵌套的M3U8文件"""
    lines = m3u8_body.splitlines()
    for line in lines:
        line = line.strip()
        if not line.startswith("#") and ".m3u8" in line.lower():
            nested_url = urljoin(base_url, line)
            logger.write(f"\n发现嵌套M3U8: {nested_url}")
            nested_body = get_m3u8_body(nested_url)
            if nested_body:
                return resolve_nested_m3u8(nested_url, nested_body)
    return m3u8_body

def get_m3u8_key(base_url, m3u8_body):
    """从M3U8内容中获取解密密钥"""
    lines = m3u8_body.splitlines()
    for line in lines:
        if "#EXT-X-KEY" in line:
            logger.write(f"\n找到密钥行: {line}")
            if "URI" not in line:
                continue
                
            uri_match = re.search(r'URI="([^"]+)"', line)
            if uri_match:
                key_url = uri_match.group(1)
                key_url = urljoin(base_url, key_url)
                
                try:
                    logger.write(f"\n获取密钥: {key_url}")
                    response = requests.get(key_url,** ro)
                    response.raise_for_status()
                    logger.write(f" - 成功")
                    return response.content
                except Exception as e:
                    error_msg = f"获取密钥失败: {str(e)}"
                    tqdm.write(error_msg)  # 使用tqdm.write避免打断进度条
                    logger.write(f"\n{error_msg}")
    logger.write("\n未找到加密密钥")
    return None

def get_ts_list(base_url, m3u8_body):
    """从M3U8内容中提取TS文件列表"""
    lines = m3u8_body.splitlines()
    ts_list = []
    index = 0
    logger.write("\n开始解析TS文件列表...")
    
    for i, line in enumerate(lines):
        line = line.strip()
        logger.write(f"\n第{i+1}行: {line[:50]}{'...' if len(line) > 50 else ''}")
        
        if not line.startswith("#") and line:
            ts_url = urljoin(base_url, line)
            if ts_url.endswith(".ts"):
                ts_name = TS_NAME_TEMPLATE % index
                ts_list.append(TsInfo(ts_name, ts_url))
                logger.write(f" - 发现TS文件: {ts_url}")
                index += 1
    
    logger.write(f"\nTS文件解析完成，共找到 {len(ts_list)} 个文件")
    return ts_list

def download_ts(ts_info, download_dir, key, progress_bar, max_retries, retry_delay):
    """下载单个TS文件并解密，支持重试"""
    ts_path = os.path.join(download_dir, ts_info.name)
    
    for attempt in range(max_retries + 1):
        try:
            logger.write(f"\n下载TS文件 (尝试 {attempt+1}/{max_retries+1}): {ts_info.url}")
            response = requests.get(ts_info.url, **ro, stream=True)
            response.raise_for_status()
            
            with open(ts_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            
            if key:
                logger.write(f" - 解密中...")
                cipher = AES.new(key, AES.MODE_ECB)
                with open(ts_path, "rb") as f:
                    encrypted_data = f.read()
                decrypted_data = unpad(cipher.decrypt(encrypted_data), AES.block_size)
                with open(ts_path, "wb") as f:
                    f.write(decrypted_data)
                
            progress_bar.update(1)
            logger.write(f" - 成功")
            return True
            
        except Exception as e:
            error_msg = f"{ts_info.name}-下载尝试 {attempt+1} 失败: {str(e)}"
            if attempt < max_retries:
                error_msg += f", 将在 {retry_delay} 秒后重试"
                time.sleep(retry_delay)
            
            # 使用tqdm.write代替print，避免打断进度条
            tqdm.write(error_msg)
            logger.write(f"\n{error_msg}")
            
            # 清理不完整文件
            if os.path.exists(ts_path):
                os.remove(ts_path)
    
    return False

def merge_ts(download_dir, output_file):
    """合并TS文件为MP4"""
    ts_files = sorted([f for f in os.listdir(download_dir) if f.endswith(".ts")])
    logger.write(f"\n开始合并TS文件: {len(ts_files)}个文件 -> {output_file}")
    
    with open(output_file, "wb") as outfile:
        for ts_file in ts_files:
            ts_path = os.path.join(download_dir, ts_file)
            with open(ts_path, "rb") as infile:
                outfile.write(infile.read())
    
    logger.write(f" - 合并完成")
    return output_file

def downloader(ts_list, max_workers, download_dir, key, max_retries, retry_delay):
    """多线程下载TS文件"""
    # 优化进度条配置，确保进度条保持在同一行
    progress_bar = tqdm(
        total=len(ts_list), 
        desc="下载进度", 
        unit="个",
        leave=True,  # 进度条完成后保留
        position=0,  # 固定进度条位置
        dynamic_ncols=True  # 动态适应终端宽度
    )
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for ts_info in ts_list:
            future = executor.submit(
                download_ts, 
                ts_info, 
                download_dir, 
                key, 
                progress_bar,
                max_retries,
                retry_delay
            )
            futures.append(future)
        
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                error_msg = f"下载任务出错: {str(e)}"
                tqdm.write(error_msg)  # 使用tqdm.write避免打断进度条
                logger.write(f"\n{error_msg}")
    
    progress_bar.close()

def main():
    init_logger()
    
    # 命令行参数解析
    parser = argparse.ArgumentParser(description="M3U8视频下载器 (进度条修复版)")
    parser.add_argument("-u", required=True, help="m3u8下载地址(http(s)://url/xx/xx/index.m3u8)")
    parser.add_argument("-n", type=int, default=24, help="下载线程数(默认24)")
    parser.add_argument("-ht", default="v1", help="设置getHost的方式(v1: http(s)://host/path; v2: http(s)://host)")
    parser.add_argument("-o", default="movie", help="自定义文件名(默认为movie)不带后缀")
    parser.add_argument("-c", default="", help="自定义请求cookie")
    parser.add_argument("-r", default="y", help="是否自动清除ts文件")
    parser.add_argument("-s", type=int, default=0, help="是否允许不安全的请求(默认0)")
    parser.add_argument("-sp", default="", help="文件保存的绝对路径(默认为当前路径)")
    parser.add_argument("-retry", type=int, default=3, help="下载失败重试次数(默认3次)")
    parser.add_argument("-retry-delay", type=int, default=2, help="重试延迟时间(秒)(默认2秒)")
    
    args = parser.parse_args()
    
    # 验证URL
    if not args.u.startswith("http"):
        error_msg = "无效的URL，请提供以http开头的M3U8地址"
        tqdm.write(error_msg)  # 使用tqdm.write避免打断进度条
        logger.write(f"\n{error_msg}")
        return
    
    # 配置请求参数
    if args.c:
        ro["headers"]["Cookie"] = args.c
        logger.write(f"\n设置Cookie: {args.c[:20]}...")
    if args.s != 0:
        ro["verify"] = False
        logger.write("\n已禁用SSL验证")
    ro["headers"]["Referer"] = get_host(args.u, "v2")
    logger.write(f"\n设置Referer: {ro['headers']['Referer']}")
    
    # 设置保存路径
    save_path = args.sp if args.sp else os.getcwd()
    download_dir = os.path.join(save_path, args.o)
    os.makedirs(download_dir, exist_ok=True)
    logger.write(f"\n下载目录: {download_dir}")
    
    # 解析M3U8
    original_m3u8_body = get_m3u8_body(args.u)
    if not original_m3u8_body:
        tqdm.write("无法获取有效的M3U8内容")
        return
    
    # 解析可能存在的嵌套M3U8
    resolved_m3u8_body = resolve_nested_m3u8(args.u, original_m3u8_body)
    
    # 获取密钥和TS列表
    ts_key = get_m3u8_key(args.u, resolved_m3u8_body)
    ts_list = get_ts_list(args.u, resolved_m3u8_body)
    
    if not ts_list:
        error_msg = "未找到TS文件列表，请检查M3U8地址是否正确或包含有效的TS条目"
        tqdm.write(error_msg)
        logger.write(f"\n{error_msg}")
        return
    
    # 下载TS文件（传递重试参数）
    downloader(ts_list, args.n, download_dir, ts_key, args.retry, args.retry_delay)
    
    # 合并TS文件
    output_file = f"{args.o}.mp4"
    if os.path.exists(output_file):
        timestamp = time.strftime("%Y%m%d%H%M%S")
        output_file = f"{args.o}_{timestamp}.mp4"
        logger.write(f"\n输出文件已存在，重命名为: {output_file}")
    
    merge_ts(download_dir, output_file)
    tqdm.write(f"合并完成: {os.path.abspath(output_file)}")
    
    # 清理临时文件
    if args.r == "y":
        import shutil
        shutil.rmtree(download_dir)
        logger.write(f"\n已清理临时TS目录: {download_dir}")
        tqdm.write("已清理临时TS文件")
    
    logger.write(f"\n===== 会话结束: {time.strftime('%Y-%m-%d %H:%M:%S')} =====")
    logger.close()

if __name__ == "__main__":
    main()
    print("Python代码进度条修复完成: m3u8下载器进度条修复版.py")