import os
import json
import tarfile
import tempfile
import hashlib
import requests
import zstandard as zstd
from bs4 import BeautifulSoup
from utils import logger, save_json

# ===========================
# 配置
# ===========================
BASE_URL = "https://pkg.freebsd.org"
DEFAULT_OUTPUT = "downloads/freebsd"
DEFAULT_TIMEOUT = 60
METADATA_FILES = ["packagesite.tzst", "packagesite.pkg", "packagesite.txz"]

PKG_SETS = [
    "FreeBSD:13:amd64", "FreeBSD:13:aarch64",
    "FreeBSD:14:amd64", "FreeBSD:14:aarch64",
    "FreeBSD:15:amd64", "FreeBSD:15:aarch64",
    "FreeBSD:16:amd64", "FreeBSD:16:aarch64",
]

# ===========================
# 工具函数
# ===========================

def download_file(session, url: str, dest_path: str, timeout: int) -> bool:
    """下载文件到指定路径，针对 404 进行优化处理"""
    try:
        response = session.get(url, stream=True, timeout=timeout)
        if response.status_code == 404:
            # 镜像站包更新极快，404 通常意味着该版本的包已被新版本替换
            logger.warning(f"包已失效 (404): {url}")
            return False
        if response.status_code != 200:
            logger.error(f"下载失败: {url} [{response.status_code}]")
            return False

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"下载异常 {url}: {e}")
        return False

def smart_extract(file_path: str, extract_dir: str) -> bool:
    """智能解压元数据文件"""
    try:
        # 尝试 Zstd 解压
        try:
            with open(file_path, "rb") as fh:
                dctx = zstd.ZstdDecompressor()
                with dctx.stream_reader(fh) as reader:
                    with tarfile.open(fileobj=reader, mode="r|") as tar:
                        tar.extractall(extract_dir)
            return True
        except Exception:
            # 回退到标准模式
            with tarfile.open(file_path, "r:*") as tar:
                tar.extractall(extract_dir)
            return True
    except Exception as e:
        logger.error(f"解压失败 {file_path}: {e}")
        return False

def get_pkg_file_hashes(session, pkg_url: str, timeout: int) -> list | None:
    """下载并计算 .pkg 内部文件哈希，解决流模式不可回溯问题"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_path = os.path.join(tmpdir, "pkg.pkg")
        if not download_file(session, pkg_url, pkg_path, timeout):
            return None

        file_hashes = []
        try:
            # 1. 探测是否为 Zstd 压缩
            is_zstd = False
            with open(pkg_path, 'rb') as f:
                if f.read(4) == b'\x28\xb5\x2f\xfd':
                    is_zstd = True

            # 2. 预解压处理：将压缩包转换为标准的本地 tar 文件
            # 这样 tarfile 就可以进行随机访问（Seek），避免 "seeking backwards" 错误
            temp_tar_path = os.path.join(tmpdir, "work.tar")

            if is_zstd:
                with open(pkg_path, "rb") as comp, open(temp_tar_path, "wb") as decomp:
                    zstd.ZstdDecompressor().copy_stream(comp, decomp)
            else:
                # 如果是 XZ/GZ，tarfile 的 "r:*" 模式在打开本地文件时支持 seek
                temp_tar_path = pkg_path

            # 3. 使用标准模式读取
            with tarfile.open(temp_tar_path, "r:*") as tar:
                for member in tar.getmembers():
                    if member.isfile():
                        f_obj = tar.extractfile(member)
                        if f_obj:
                            data = f_obj.read()
                            file_hashes.append({
                                "path": member.name,
                                "md5": hashlib.md5(data).hexdigest(),
                                "sha256": hashlib.sha256(data).hexdigest(),
                            })
            return file_hashes
        except Exception as e:
            logger.error(f"解析 pkg 内部文件失败: {pkg_url} - {e}")
            return None

def parse_packagesite_file(extract_dir: str) -> list:
    """解析元数据 JSON"""
    for name in ["packagesite.yaml", "packagesite"]:
        p = os.path.join(extract_dir, name)
        if os.path.exists(p):
            packages = []
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            packages.append(json.loads(line))
                        except: continue
            return packages
    return []

# ===========================
# 主流程
# ===========================

def collect_freebsd(output_dir=DEFAULT_OUTPUT, cache=True):
    session = requests.Session()

    for pkg_set in PKG_SETS:
        safe_pkg = pkg_set.replace(":", "_")
        set_url = f"{BASE_URL}/{pkg_set}"

        try:
            resp = session.get(set_url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")
            releases = [a["href"] for a in soup.find_all("a", href=True)
                        if a["href"] != "../" and a["href"].endswith("/")]
        except Exception as e:
            logger.error(f"无法获取 Release 列表 {set_url}: {e}")
            continue

        for rel in releases:
            extract_dir = os.path.join(output_dir, safe_pkg, rel.strip("/"))
            os.makedirs(extract_dir, exist_ok=True)

            # 探测元数据
            metadata_found = False
            for ext_file in METADATA_FILES:
                meta_url = f"{set_url}/{rel}{ext_file}"

                try:
                    if session.head(meta_url, timeout=10).status_code == 200:
                        with tempfile.TemporaryDirectory() as tmpdir:
                            tmp_p = os.path.join(tmpdir, "meta")
                            if download_file(session, meta_url, tmp_p, DEFAULT_TIMEOUT):
                                if smart_extract(tmp_p, extract_dir):
                                    metadata_found = True
                                    break
                except: continue

            if not metadata_found:
                continue

            packages = parse_packagesite_file(extract_dir)
            logger.info(f"开始处理 {pkg_set}/{rel}, 共 {len(packages)} 个包")

            for pkg in packages:
                name, version, repopath = pkg.get("name"), pkg.get("version"), pkg.get("repopath")
                if not all([name, version, repopath]): continue

                safe_name = name.replace("/", "_")
                save_path = os.path.join(extract_dir, f"{safe_name}_{version}.json")

                if cache and os.path.exists(save_path):
                    continue

                pkg_url = f"{set_url}/{rel}{repopath}"
                hashes = get_pkg_file_hashes(session, pkg_url, DEFAULT_TIMEOUT)

                if hashes:
                    pkg["file_hashes"] = hashes
                    save_json(pkg, save_path)
                    logger.info(f"保存成功: {name}-{version}")

if __name__ == "__main__":
    collect_freebsd()