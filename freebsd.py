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
PKG_SETS = [
    "FreeBSD:13:amd64", "FreeBSD:13:aarch64",
    "FreeBSD:14:amd64", "FreeBSD:14:aarch64",
    "FreeBSD:15:amd64", "FreeBSD:15:aarch64",
    "FreeBSD:16:amd64", "FreeBSD:16:aarch64",
]


# ===========================
# 工具函数
# ===========================

def download_file(url: str, dest_path: str, timeout: int) -> bool:
    """下载文件到指定路径"""
    try:
        response = requests.get(url, stream=True, timeout=timeout)
        if response.status_code != 200:
            logger.error(f"下载失败: {url} [{response.status_code}]")
            return False

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True

    except Exception as e:
        logger.error(f"下载异常 {url}: {e}")
        return False


def extract_tzst_file(tzst_path: str, extract_dir: str) -> bool:
    """解压 .tzst 文件"""
    temp_tar = tzst_path + ".tar"
    try:
        # Step 1: zstd 解压
        with open(tzst_path, "rb") as comp, open(temp_tar, "wb") as decomp:
            zstd.ZstdDecompressor().copy_stream(comp, decomp)

        # Step 2: tar 解包
        with tarfile.open(temp_tar, "r") as tar:
            tar.extractall(extract_dir)

        return True
    except Exception as e:
        logger.error(f"解压失败: {tzst_path} - {e}")
        return False
    finally:
        if os.path.exists(temp_tar):
            os.remove(temp_tar)


def parse_packagesite_file(filename: str) -> list:
    """解析 FreeBSD packagesite 文件 (JSON 每行一个包)"""
    packages = []
    with open(filename, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                packages.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(f"[JSON解析错误] 第{line_num}行: {e}")
    return packages


def extract_href_list(url: str) -> list:
    """获取目录页中的所有子链接"""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        return [
            a["href"].strip() for a in soup.find_all("a", href=True)
            if a["href"].strip() and a["href"] != "../"
        ]
    except Exception as e:
        logger.error(f"无法提取链接: {url} - {e}")
        return []


def get_pkg_file_hashes(pkg_url: str, timeout: int) -> list | None:
    """下载 .pkg 文件并计算其中文件的 MD5 与 SHA256"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_path = os.path.join(tmpdir, "pkg.pkg")

        if not download_file(pkg_url, pkg_path, timeout):
            return None

        file_hashes = []
        try:
            with tarfile.open(pkg_path, "r") as tar:
                for member in tar.getmembers():
                    if member.isfile():
                        data = tar.extractfile(member).read()
                        file_hashes.append({
                            "path": member.name,
                            "md5": hashlib.md5(data).hexdigest(),
                            "sha256": hashlib.sha256(data).hexdigest(),
                        })
            return file_hashes
        except Exception as e:
            logger.error(f"解析 pkg 文件失败: {pkg_url} - {e}")
            return None


def download_and_extract_packagesite(url: str, extract_dir: str, timeout: int, type_name: str) -> bool:
    """下载并解压 packagesite.tzst"""
    logger.info(f"[{type_name}] 下载: {url}")

    os.makedirs(extract_dir, exist_ok=True)
    temp_file = "temp_packagesite.tzst"

    try:
        if not download_file(url, temp_file, timeout):
            return False

        if extract_tzst_file(temp_file, extract_dir):
            logger.info(f"[{type_name}] 解压成功: {url}")
            return True
        else:
            return False
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


# ===========================
# 主流程
# ===========================

def collect_freebsd(
    output_dir: str = DEFAULT_OUTPUT,
    base_url: str = BASE_URL,
    type_name: str = "FreeBSD",
    timeout: int = DEFAULT_TIMEOUT,
    cache: bool = True
):
    """采集 FreeBSD Packages 信息"""
    for pkg_set in PKG_SETS:
        safe_pkg = pkg_set.replace(":", "_")

        for release in extract_href_list(f"{base_url}/{pkg_set}"):
            if not release.endswith("/"):
                continue

            pkgsite_url = f"{base_url}/{pkg_set}/{release}packagesite.tzst"
            extract_dir = f"{output_dir}/{safe_pkg}/{release}"

            if not download_and_extract_packagesite(pkgsite_url, extract_dir, timeout, type_name):
                logger.error(f"[{type_name}] 获取 packagesite.tzst 失败: {pkgsite_url}")
                continue

            pkgsite_file = os.path.join(extract_dir, "packagesite.yaml")
            if not os.path.exists(pkgsite_file):
                logger.error(f"[{type_name}] 缺少文件: {pkgsite_file}")
                continue

            packages = parse_packagesite_file(pkgsite_file)
            logger.info(f"[{type_name}] 成功解析 {pkgsite_file}，共 {len(packages)} 个包")

            for pkg in packages:
                name, version, repopath = pkg.get("name"), pkg.get("version"), pkg.get("repopath")
                if not all([name, version, repopath]):
                    logger.warning(f"[{type_name}] 无效包信息: {pkg}")
                    continue

                save_path = f"{output_dir}/{safe_pkg}/{release}{name}_{version}.json"
                if cache and os.path.exists(save_path):
                    logger.info(f"[{type_name}] 跳过已存在: {save_path}")
                    continue

                pkg_url = f"{base_url}/{pkg_set}/latest/{repopath}"
                pkg["file_hashes"] = get_pkg_file_hashes(pkg_url, timeout)
                if pkg["file_hashes"]:
                    save_json(pkg, save_path)
                    logger.info(f"[{type_name}] 保存: {save_path}")
                else:
                    logger.info(f"[{type_name}] 无文件列表信息: {pkg_url}")


# ===========================
# 入口
# ===========================

if __name__ == "__main__":
    collect_freebsd()
