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
    """下载文件到指定路径"""
    try:
        response = session.get(url, stream=True, timeout=timeout)
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
                    with tarfile.open(fileobj=reader, mode="r|") as tar:
                        tar.extractall(extract_dir)
            return True
        except Exception:
            # 如果 Zstd 失败，回退到标准 tarfile (处理 XZ/Gzip 等)
            # mode="r:*" 会自动探测格式
            with tarfile.open(file_path, "r:*") as tar:
                tar.extractall(extract_dir)
            return True
    except Exception as e:
        logger.error(f"解压失败 {file_path}: {e}")
        return False

def parse_packagesite_file(extract_dir: str) -> list:
    """解析 FreeBSD packagesite 文件"""
    packages = []
    # 兼容两种可能的内部文件名
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
            # 对于 .pkg，我们也需要应用 smart_extract 类似的逻辑
            # 这里为了读取内容不解压到磁盘，直接内存操作
            is_zstd = False
            with open(pkg_path, 'rb') as f:
                if f.read(4) == b'\x28\xb5\x2f\xfd': # Zstd Magic Number
                    is_zstd = True

            if is_zstd:
                with open(pkg_path, "rb") as fh:
                    dctx = zstd.ZstdDecompressor()
                    with dctx.stream_reader(fh) as reader:
                        with tarfile.open(fileobj=reader, mode="r|") as tar:
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
            else:
                with tarfile.open(pkg_path, "r:*") as tar:
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
    session = requests.Session() # 使用 Session 复用连接

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

            # --- 核心逻辑改进：多文件探测避免 404 ---
            metadata_downloaded = False
            for meta_filename in METADATA_FILES:
                meta_url = f"{set_url}/{release}{meta_filename}"

                # 先发 HEAD 请求检查文件是否存在
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
                            break # 成功获取一个，跳过后续后缀

            if not metadata_downloaded:
                logger.error(f"[{type_name}] 无法找到有效的 packagesite 文件: {set_url}/{release}")
                continue

            # 解析解析
            packages = parse_packagesite_file(extract_dir)
            logger.info(f"[{type_name}] 解析完成，共 {len(packages)} 个包")

            for pkg in packages:
                name, version, repopath = pkg.get("name"), pkg.get("version"), pkg.get("repopath")
                if not all([name, version, repopath]):
                    continue

                safe_name = name.replace("/", "_").replace("\\", "_")
                safe_version = version.replace("/", "_").replace("\\", "_")
                save_path = f"{extract_dir}/{safe_name}_{safe_version}.json"

                if cache and os.path.exists(save_path):
                    continue

                pkg_url = f"{set_url}/{release}{repopath}"
                pkg["file_hashes"] = get_pkg_file_hashes(session, pkg_url, timeout)
                if pkg["file_hashes"]:
                    save_json(pkg, save_path)
                    logger.info(f"[{type_name}] 保存: {save_path}")

if __name__ == "__main__":
    collect_freebsd()