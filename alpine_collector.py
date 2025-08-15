import os
import tarfile
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import md5_filelike, download_file, get_links, file_hash, save_json, logger, load_json

BASE_URL = "https://mirrors.aliyun.com/alpine/"
FAILED_LIST_FILE = "failed_downloads.txt"
type_name = 'Alpine'

os_dir_version_key = "os_dir_version"
os_dir_repo_key = "os_dir_repo"
os_dir_arch_key = "os_dir_arch"


def _process_arch_dir(arch_url, version, repo, arch, output_dir, save=False):
    # 获取目录下所有 .apk 文件
    apk_files = get_links(arch_url, r".+\.apk$", type_name)
    logger.info(f"[Alpine] {arch_url} → Found {len(apk_files)} APKs")
    additional = {os_dir_version_key: version, os_dir_repo_key: repo, os_dir_arch_key: arch}

    for apk in apk_files:
        try:
            download_file(url=urljoin(arch_url, apk), save_dir=os.path.join(output_dir, version, repo, arch),
                          save=save,
                          callback=_process_apk_file, type_name=type_name, additional=additional)
        except Exception as e:
            logger.error(f"[{type_name}] Failed to download {apk}: {e}")


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
                    "size":member.size,
                    "md5": md5_val
                })

    if files:
        pkginfo['files'] = files

    return pkginfo


def _process_apk_file(file_path, additional):
    version = additional[os_dir_version_key]
    repo = additional[os_dir_repo_key]
    arch = additional[os_dir_arch_key]
    # 下载后处理逻辑
    logger.info(f"[{type_name}] Processing {version} -> {repo} -> {arch} -> {os.path.basename(file_path)}")
    res = _parse_apk(file_path)
    if res:
        res[os_dir_version_key] = version
        res[os_dir_repo_key] = repo
        res[os_dir_arch_key] = arch
        save_json(res, f'{file_path}.json')


def _get_repos_arches_info(versions, ver_repos_cache_file, repo_arches_cache_file):
    ver_repos = {}
    repo_arches = {}
    total = 0

    # 尝试加载缓存
    if os.path.exists(ver_repos_cache_file) and os.path.exists(repo_arches_cache_file):
        ver_repos = load_json(ver_repos_cache_file)
        repo_arches = load_json(repo_arches_cache_file)

    if len(ver_repos) == 0 or len(repo_arches) == 0:
        logger.info(f"[{type_name}] Collecting apk dirs...")
        for ver in versions:
            ver_url = urljoin(BASE_URL, ver)
            # 获取仓库类型
            repos = get_links(ver_url, r"(main|community|releases|testing)/$", type_name)
            ver_repos[ver] = repos
            for repo in repos:
                repo_url = urljoin(ver_url, repo)
                # 获取架构目录
                arches = get_links(repo_url, r"(x86|x86_64|aarch64|armhf|armv7|ppc64le|s390x)/$", type_name)
                repo_arches[ver + repo] = arches
                total += len(arches)
    else:
        for ver, repos in ver_repos.items():
            for repo in repos:
                for _ in repo_arches[ver + repo]:
                    total += 1
        logger.info(f"[{type_name}] Using apk dirs cache")

    save_json(ver_repos, ver_repos_cache_file)
    save_json(repo_arches, repo_arches_cache_file)

    return ver_repos, repo_arches, total


def collect_alpine(output_dir="downloads/alpine", save=False):
    # 获取所有版本目录
    versions = get_links(BASE_URL, r"(v[0-9]+\.[0-9]+|edge|latest-stable)/$", type_name)
    logger.info(f"[{type_name}] Found versions: {versions}")
    ver_repos_cache_file = os.path.join(output_dir, "ver_repos.json")
    repo_arches_cache_file = os.path.join(output_dir, "repo_arches.json")

    # 加载目录缓存，获取目录总数
    ver_repos, repo_arches, total = _get_repos_arches_info(versions, ver_repos_cache_file, repo_arches_cache_file)
    logger.info(f"[{type_name}] Found {total} apk dirs.")
    cur = 0
    for ver, repos in ver_repos.items():
        ver_url = urljoin(BASE_URL, ver)
        for repo in repos:
            repo_url = urljoin(ver_url, repo)
            for arch in repo_arches[ver + repo]:
                cur += 1
                logger.info(f"[{type_name}] Progress {cur}/{total}")
                arch_url = urljoin(repo_url, arch)
                # 以arch为单位进行处理
                _process_arch_dir(arch_url, ver.strip("/"), repo.strip("/"), arch.strip("/"), output_dir, save)
