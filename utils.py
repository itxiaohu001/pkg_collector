import hashlib
import json
import os
import re
import time
import requests
import lief
import logging
from logging.handlers import RotatingFileHandler
from bs4 import BeautifulSoup

# 创建 Logger
logger = logging.getLogger("crawl")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    filename="craw.log",  # 基础日志文件名
    maxBytes=10 * 1024 * 1024,  # 每个日志文件最大 10MB
    backupCount=10  # 保留最多 10 个备份文件
)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(handler)


class LinkFetchError(Exception):
    """自定义异常，包含重试信息和原始错误"""

    def __init__(self, url: str, retries: int, original_error: Exception):
        self.url = url
        self.retries = retries
        self.original_error = original_error
        super().__init__(
            f"Failed to fetch links from {url} after {retries} retries. Original error: {str(original_error)}")


def get_links(
        url,
        pattern=None,
        type_name="",
        timeout=60,
        max_retries=3,
        retry_delay=5.0
):
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            # 1. 发送HTTP请求
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()  # 自动处理4xx/5xx错误

            # 2. 解析HTML
            soup = BeautifulSoup(r.text, "html.parser")
            tbody = soup.find("tbody")

            if not tbody:
                logger.warning(f"[{type_name}] No <tbody> found in {url}")
                return []

            # 3. 提取匹配的链接
            anchors = tbody.find_all("a")
            links = []
            for a in anchors:
                href = a.get("href")
                if href and (not pattern or re.match(pattern, href)):
                    links.append(href)

            return links

        except requests.exceptions.RequestException as e:
            last_error = e
            logger.warning(
                f"[{type_name}] Attempt {attempt}/{max_retries} failed for {url}: {str(e)}"
            )
            if attempt < max_retries:
                time.sleep(retry_delay * attempt)  # 指数退避
        except Exception as e:
            last_error = e
            logger.error(f"[{type_name}] Unexpected error processing {url}: {str(e)}")
            break  # 非网络错误立即终止

    # 重试全部失败后抛出自定义异常
    raise LinkFetchError(url, max_retries, last_error)


class FileDownloadError(Exception):
    """自定义下载异常，包含重试信息和上下文"""

    def __init__(self, url: str, retries: int, error: Exception, file_path: str = ""):
        self.url = url
        self.retries = retries
        self.original_error = error
        self.file_path = file_path
        super().__init__(
            f"Failed to download {url} after {retries} retries. "
            f"Path: {file_path}, Error: {str(error)}"
        )


def download_file(
        url,
        save_path,
        save=False,
        callback=None,
        type_name="",
        timeout=60,
        additional=None,
        max_retries: int = 3,
        retry_delay: float = 5.0,
):
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            # 发送请求（禁用SSL验证需谨慎）
            r = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            r.raise_for_status()  # 检查HTTP状态码

            # 保存文件
            with open(save_path, "wb") as f:
                f.write(r.content)
            if os.path.exists(save_path):
                logger.info(f"[{type_name}] Downloaded {url}")
            else:
                logger.error(f"[{type_name}] Failed to save {url}")
                return None

            # 回调处理
            if callback:
                callback(save_path, additional)

            # 非保存模式删除文件
            if not save:
                os.remove(save_path)
                logger.info(f"[{type_name}] Deleted {save_path}")

            return save_path

        except requests.exceptions.RequestException as e:
            last_error = e
            logger.warning(
                f"[{type_name}] Attempt {attempt}/{max_retries} failed for {url}: {str(e)}"
            )
            if attempt < max_retries:
                time.sleep(retry_delay * attempt)  # 指数退避
        except Exception as e:
            last_error = e
            logger.error(f"[{type_name}] Unexpected error downloading {url}: {str(e)}")
            break  # 非网络错误立即终止

        finally:
            # 失败时清理临时文件
            if last_error and os.path.exists(save_path):
                os.remove(save_path)

    # 重试全部失败后抛出自定义异常
    raise FileDownloadError(url, max_retries, last_error, save_path)


def save_json(data, name):
    """保存 JSON 数据"""
    os.makedirs(os.path.dirname(name), exist_ok=True)
    with open(name, "w", encoding="utf-8") as f:
        json.dump(data, f)


def load_json(file):
    """加载 JSON 数据"""
    with open(file, 'r', encoding='utf8') as f:
        return json.load(f)


def md5_filelike(fobj):
    """计算文件流的 MD5 值"""
    md5 = hashlib.md5()
    for chunk in iter(lambda: fobj.read(8192), b""):
        md5.update(chunk)
    return md5.hexdigest()


def file_hash(path, algo="md5"):
    """计算文件路径的哈希"""
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def is_elf(file_path):
    """判断文件是否为 ELF 文件"""
    return lief.is_elf(file_path)
