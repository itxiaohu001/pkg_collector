import hashlib
import json
import os
import re
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


def get_links(url, pattern=None, type_name="", timeout=60):
    """获取 <tbody> 中匹配 pattern 的链接"""
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        # 只找 <tbody> 范围
        tbody = soup.find("tbody")
        if not tbody:
            logger.warning(f"[{type_name}] No <tbody> found in {url}")
            return []

        anchors = tbody.find_all("a")
        links = []
        for a in anchors:
            href = a.get("href")
            if not href:
                continue
            if pattern:
                if re.match(pattern, href):
                    links.append(href)
            else:
                links.append(href)

        return links

    except Exception as e:
        logger.error(f"[{type_name}] Failed to list {url}: {e}")
        return []


def download_file(url, save_dir, save=False, callback=None, type_name="", timeout=60, additional=None):
    """下载文件"""
    file_path = os.path.normpath(os.path.join(save_dir, os.path.basename(url)))
    os.makedirs(save_dir, exist_ok=True)

    if os.path.exists(f'{file_path}.json'):
        return ""

    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        with open(file_path, "wb") as f:
            f.write(r.content)
        logger.info(f"[{type_name}] Downloaded {url}")
        if callback:
            callback(file_path, additional)
        if not save:
            os.remove(file_path)
            logger.info(f"[{type_name}] Deleted {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"[{type_name}] Failed {url}: {e}")
        if not save:
            os.remove(file_path)
        return ""


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
