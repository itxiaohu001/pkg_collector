import hashlib
import json
import os
import re
import requests
import lief
import logging
from logging.handlers import RotatingFileHandler

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


def get_links(url, pattern=None, type_name="", timeout=60):
    """获取目录下所有匹配 pattern 的链接"""
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        links = re.findall(r'href="([^"]+)"', r.text)
        if pattern:
            links = [l for l in links if re.match(pattern, l)]
        return links
    except Exception as e:
        logger.error(f"[{type_name}] Failed to list {url}: {e}")
        return []


def download_file(url, output_dir, version, repo, arch, save=False, callback=None, type_name="", timeout=60):
    """下载文件"""
    file_path = os.path.normpath(os.path.join(output_dir, version, repo, arch, os.path.basename(url)))
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    if os.path.exists(f'{file_path}.json'):
        return

    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        with open(file_path, "wb") as f:
            f.write(r.content)
        logger.info(f"[{type_name}] Downloaded {url}")
        if callback:
            callback(file_path, version, repo.strip("/"), arch.strip("/"), save)
    except Exception as e:
        logger.error(f"[{type_name}] Failed {url}: {e}")


def save_json(data, name):
    """保存 JSON 数据"""
    os.makedirs(os.path.dirname(name), exist_ok=True)
    with open(name, "w", encoding="utf-8") as f:
        json.dump(data, f)


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
