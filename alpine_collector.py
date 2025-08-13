import os
import tarfile
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import md5_filelike, download_file, get_links, file_hash, save_json, logger

BASE_URL = "https://mirrors.aliyun.com/alpine/"
FAILED_LIST_FILE = "failed_downloads.txt"
type_name = 'Alpine'


def _process_arch_dir(arch_url, version, repo, arch, output_dir, parallel=False, workers=4, save=False):
    # 获取目录下所有 .apk 文件
    apk_files = get_links(arch_url, r".+\.apk$", type_name)
    logger.info(f"[Alpine] {arch_url} → Found {len(apk_files)} APKs")

    if parallel:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    download_file, urljoin(arch_url, apk), output_dir, version, repo, arch, save, _process_apk_file,
                    type_name
                )
                for apk in apk_files
            ]
            for _ in as_completed(futures):
                pass
    else:
        for apk in apk_files:
            download_file(urljoin(arch_url, apk), output_dir, version, repo, arch, save, _process_apk_file, type_name)


def _parse_apk(apk_path):
    """解析 .apk文件"""
    pkginfo = {'source_name': os.path.basename(apk_path), 'source_hash': file_hash(apk_path)}
    files = []

    with tarfile.open(apk_path, "r:gz") as tar:
        for member in tar.getmembers():
            # 解析 .PKGINFO
            if member.name == ".PKGINFO":
                f = tar.extractfile(member)
                for raw_line in f:
                    line = raw_line.decode().strip()
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key, val = key.strip(), val.strip()
                        # 支持同名字段多次出现（如 depend）
                        if key in pkginfo:
                            if isinstance(pkginfo[key], list):
                                pkginfo[key].append(val)
                            else:
                                pkginfo[key] = [pkginfo[key], val]
                        else:
                            pkginfo[key] = val

            # 收集 bin/ 或 usr/bin 下的文件
            elif (
                    member.isfile()
                    # and (member.name.startswith("bin/") or member.name.startswith("usr/bin/"))
            ):
                f = tar.extractfile(member)
                md5_val = md5_filelike(f)
                files.append({
                    "name": member.name,
                    "md5": md5_val
                })

    if files:
        pkginfo['files'] = files

    return pkginfo


def _process_apk_file(file_path, version, repo, arch, save):
    # 下载后处理逻辑
    logger.info(f"[{type_name}] Processing {version} -> {repo} -> {arch} -> {os.path.basename(file_path)}")
    res = _parse_apk(file_path)
    if res:
        save_json(res, f'{file_path}.json')
    if not save:
        logger.info(f"[{type_name}] Removing {file_path}")
        os.remove(file_path)


def collect_alpine(output_dir="downloads/alpine", parallel=False, save=False, workers=4):
    # 1. 获取所有版本目录
    versions = get_links(BASE_URL, r"(v[0-9]+\.[0-9]+|edge|latest-stable)/$", type_name)
    logger.info(f"[Alpine] Found versions: {versions}")

    for ver in versions:
        ver_url = urljoin(BASE_URL, ver)
        # 2. 获取仓库类型
        repos = get_links(ver_url, r"(main|community|releases|testing)/$", type_name)
        for repo in repos:
            repo_url = urljoin(ver_url, repo)
            # 3. 获取架构目录
            arches = get_links(repo_url, r"(x86|x86_64|aarch64|armhf|armv7|ppc64le|s390x)/$", type_name)
            for arch in arches:
                arch_url = urljoin(repo_url, arch)
                _process_arch_dir(arch_url, ver.strip("/"), repo, arch, output_dir, parallel, workers, save)
