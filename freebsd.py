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
# 优先级探测列表
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
    """下载文件到指定路径，针对 404 进行降级处理"""
    try:
        response = session.get(url, stream=True, timeout=timeout)
        if response.status_code == 404:
            logger.warning(f"文件已失效 (404): {url}")
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
    """
    智能解压：兼容 Zstd (.tzst / .pkg) 和 XZ (.txz / .pkg)
    """
    try:
        # 尝试使用 Zstd 解压流
        try:
            with open(file_path, "rb") as fh:
                dctx = zstd.ZstdDecompressor()
                with dctx.stream_reader(fh) as reader:
                    # 注意：元数据解压我们依然可以使用流模式，因为 extractall 是一次性顺序操作
                    with tarfile.open(fileobj=reader, mode="r|") as tar:
                        tar.extractall(extract_dir)
            return True
        except Exception:
            # 如果 Zstd 失败，回退到标准 tarfile (处理 XZ/Gzip 等)
            with tarfile.open(file_path, "r:*") as tar:
                tar.extractall(extract_dir)
            return True
    except Exception as e:
        logger.error(f"解压失败 {file_path}: {e}")
        return False

def parse_packagesite_file(extract_dir: str) -> list:
    """解析 FreeBSD packagesite 文件"""
    packages = []
    target_file = None
    for name in ["packagesite.yaml", "packagesite"]:
        p = os.path.join(extract_dir, name)
        if os.path.exists(p):
            target_file = p
            break

    if not target_file:
        return []

    with open(target_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                packages.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(f"JSON解析错误: {e}")
    return packages

def get_pkg_file_hashes(session, pkg_url: str, timeout: int) -> list | None:
    """下载 .pkg 文件并计算其中文件的哈希"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_path = os.path.join(tmpdir, "pkg.pkg")
        if not download_file(session, pkg_url, pkg_path, timeout):
            return None

        file_hashes = []
        try:
            # 探测是否为 Zstd 压缩
            is_zstd = False
            with open(pkg_path, 'rb') as f:
                if f.read(4) == b'\x28\xb5\x2f\xfd': # Zstd Magic Number
                    is_zstd = True

            # --- 核心修复：预解压到临时 tar 文件以支持 Seeking ---
            work_tar = os.path.join(tmpdir, "work.tar")

            if is_zstd:
                with open(pkg_path, "rb") as fh, open(work_tar, "wb") as wh:
                    dctx = zstd.ZstdDecompressor()
                    dctx.copy_stream(fh, wh)
            else:
                # 如果是 XZ 等其他格式，tarfile 的 "r:*" 模式在打开磁盘文件时支持回溯
                work_tar = pkg_path

            # 使用标准 "r" 模式打开本地文件，支持 getmembers() 后再次 extractfile()
            with tarfile.open(work_tar, "r:*") as tar:
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
            logger.error(f"解析 pkg 文件失败: {pkg_url} - {e}")
            return None

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
    session = requests.Session()

    for pkg_set in PKG_SETS:
        safe_pkg = pkg_set.replace(":", "_")
        set_url = f"{base_url}/{pkg_set}"

        releases = []
        try:
            resp = session.get(set_url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")
            releases = [a["href"].strip() for a in soup.find_all("a", href=True)
                        if a["href"].strip() and a["href"] != "../" and a["href"].endswith("/")]
        except Exception as e:
            logger.error(f"无法访问目录 {set_url}: {e}")
            continue

        for release in releases:
            extract_dir = os.path.join(output_dir, safe_pkg, release.strip("/"))
            os.makedirs(extract_dir, exist_ok=True)

            metadata_downloaded = False
            for meta_filename in METADATA_FILES:
                meta_url = f"{set_url}/{release}{meta_filename}"

                try:
                    check = session.head(meta_url, timeout=10)
                    if check.status_code != 200:
                        continue
                except:
                    continue

                logger.info(f"[{type_name}] 正在尝试获取元数据: {meta_url}")
                with tempfile.TemporaryDirectory() as tmpdir:
                    temp_file = os.path.join(tmpdir, meta_filename)
                    if download_file(session, meta_url, temp_file, timeout):
                        if smart_extract(temp_file, extract_dir):
                            metadata_downloaded = True
                            break

            if not metadata_downloaded:
                continue

            packages = parse_packagesite_file(extract_dir)
            logger.info(f"[{type_name}] {pkg_set}/{release} 解析完成，共 {len(packages)} 个包")

            for pkg in packages:
                name, version, repopath = pkg.get("name"), pkg.get("version"), pkg.get("repopath")
                if not all([name, version, repopath]):
                    continue

                safe_name = name.replace("/", "_").replace("\\", "_")
                safe_version = version.replace("/", "_").replace("\\", "_")
                save_path = os.path.join(extract_dir, f"{safe_name}_{safe_version}.json")

                if cache and os.path.exists(save_path):
                    continue

                pkg_url = f"{set_url}/{release}{repopath}"
                # 此处会进入修复后的 get_pkg_file_hashes
                pkg["file_hashes"] = get_pkg_file_hashes(session, pkg_url, timeout)

                # 只有成功获取到文件列表才保存，避免产生空数据 JSON
                if pkg["file_hashes"]:
                    save_json(pkg, save_path)
                    logger.info(f"[{type_name}] 已处理: {name}-{version}")

if __name__ == "__main__":
    collect_freebsd()