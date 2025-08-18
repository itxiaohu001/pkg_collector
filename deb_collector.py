import gzip
import bz2
import lzma
import hashlib
import os
import random
import time

from debian import debfile
from urllib.parse import urljoin
from utils import get_links, logger, download_file, save_json, load_json, file_hash

os_dir_version_key = "os_dir_version"
os_dir_repo_key = "os_dir_repo"
os_dir_arch_key = "os_dir_arch"

packages_rel_path_key = "Filename"  # Packages文件内deb资源的相对路径的key


def load_and_parse_packages(path, version, repo, arch):
    """
    加载并解析 Debian/Ubuntu Packages 文件（支持多种压缩格式）
    :param arch: 架构
    :param repo: 仓库类型
    :param version: os版本
    :param path: 文件路径（支持 .gz, .bz2, .xz, 或未压缩）
    :return: list[dict]
    """
    # 1. 根据扩展名选择解压方式
    ext = os.path.splitext(path)[1].lower()

    if ext == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            content = f.read()
    elif ext == ".bz2":
        with bz2.open(path, "rt", encoding="utf-8", errors="replace") as f:
            content = f.read()
    elif ext == ".xz":
        with lzma.open(path, "rt", encoding="utf-8", errors="replace") as f:
            content = f.read()
    else:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

    # 2. 解析逻辑（自动合并跨行字段）
    try:
        res = parse_packages_file(content, version, repo, arch)
        return res
    except Exception as e:
        raise ValueError(f"Failed to parse packages file {path}: {e}")


def parse_packages_file(content, version, repo, arch):
    """
    解析 Debian/Ubuntu Packages 文件
    跨行字段自动合并成一行
    """
    packages = []
    current_pkg = {}
    current_key = None

    for line in content.splitlines():
        if not line.strip():
            if current_pkg:
                packages.append(current_pkg)
                current_pkg = {os_dir_version_key: version, os_dir_repo_key: repo, os_dir_arch_key: arch}
                current_key = None
            continue

        if line.startswith(" "):
            if current_key:
                current_pkg[current_key] += " " + line.strip()
        else:
            if ":" in line:
                key, value = line.split(":", 1)
                current_pkg[key.strip()] = value.strip()
                current_key = key.strip()

    if current_pkg:
        packages.append(current_pkg)

    return packages


def _parse_deb(file_path, additional):
    if not additional:
        return

    package = additional.get("package")
    if not package:
        raise ValueError(f"Invalid package {file_path}")

    if not os.path.exists(file_path):
        raise ValueError(f"File {file_path} not exists")

    source_name = os.path.basename(file_path)
    source_hash = file_hash(file_path)
    package["source_name"] = source_name
    package["source_hash"] = source_hash

    results = []

    try:
        # 打开 deb 文件
        deb = debfile.DebFile(file_path)

        # data.tgz() 返回 TarFile 对象（不管是 gz、xz、bz2 都会解压）
        tar = deb.data.tgz()

        for member in tar.getmembers():
            if member.isfile():
                fobj = tar.extractfile(member)
                if fobj:
                    data = fobj.read()
                    md5 = hashlib.md5(data).hexdigest()
                    results.append({
                        "path": member.name,
                        "size": member.mode,
                        "md5": md5
                    })
    except Exception as e:
        raise ValueError(f"Failed to parse deb {file_path}: {e}")

    if len(results) > 0:
        package["files"] = results
        save_json(package, file_path + ".json")
    else:
        raise ValueError(f"No files found in {file_path}")


def collect_deb(base_url, out_dir, type_name, timeout=60, save=False, randint=2, cache=True):
    os.makedirs(out_dir, exist_ok=True)

    url_info = {}
    cur = 0

    # 获取所有的Packages的url
    dists_url = urljoin(base_url, "dists/")
    versions = get_links(url=dists_url, pattern=r'^(?!\.\.).*\/$')
    packages_json_cache = os.path.join(out_dir, "packages_urls.json")
    if cache and os.path.exists(packages_json_cache):
        url_info = load_json(packages_json_cache)
    else:
        for version in versions:
            repo_url = urljoin(dists_url, version)
            try:
                repos = get_links(url=repo_url, pattern=r'^(?!\.\.).*\/$')
            except Exception as e:
                logger.warn(f"[{type_name}] Failed to get dists info from {repo_url}: {e}")
                continue
            for repo in repos:
                arch_url = urljoin(repo_url, repo)
                try:
                    arches = get_links(url=arch_url, pattern=r'^binary-.*\/$')
                except Exception as e:
                    logger.warn(f"[{type_name}] Failed to get dists info from {arch_url}: {e}")
                    continue
                for arch in arches:
                    packages_url = urljoin(arch_url, arch)
                    try:
                        packages = get_links(packages_url, pattern=r'^Packages(?!.*/$).*$')
                    except Exception as e:
                        logger.warn(f"[{type_name}] Failed to get dists info from {packages_url}: {e}")
                        continue
                    if len(packages) > 0:
                        # 存在多种格式的Packages压缩包的话只需要任选一个
                        package_url = urljoin(packages_url, packages[0])
                        url_info[package_url] = {}
                        url_info[package_url][os_dir_version_key] = version
                        url_info[package_url][os_dir_repo_key] = repo
                        url_info[package_url][os_dir_arch_key] = arch
    save_json(url_info, packages_json_cache)
    logger.info(f"[{type_name}] Found {len(url_info)} packages urls")

    # 依次下载Packages并解析
    for index_packages_url, info in url_info.items():
        try:
            pkg_list = []
            version = info[os_dir_version_key]
            repo = info[os_dir_repo_key]
            arch = info[os_dir_arch_key]
            if not version or not repo or not arch:
                logger.warn(f"[{type_name}] Invalid package info: {info}")
                continue
            cur += 1
            logger.info(f"[{type_name}] Processing {index_packages_url} {cur}/{len(url_info)}")
            json_cache = os.path.join(out_dir, version, repo, arch, "packages.json")
            if cache and os.path.exists(json_cache):
                pkg_list = load_json(json_cache)
            else:
                save_dir = os.path.normpath(os.path.join(out_dir, version, repo, arch))
                os.makedirs(save_dir, exist_ok=True)
                save_path = os.path.join(save_dir, os.path.basename(index_packages_url))
                download_file(url=index_packages_url, save=True,
                              save_path=save_path,
                              type_name=type_name, timeout=timeout)
                if os.path.exists(save_path):
                    pkg_list = load_and_parse_packages(save_path, version, repo, arch)
                    if len(pkg_list) > 0:
                        save_json(pkg_list, json_cache)
                    os.remove(save_path)
            for package in pkg_list:
                if not package:
                    continue
                additional = {"package": package}
                deb_rel_path = package.get(packages_rel_path_key)
                if not version or not repo or not arch or not deb_rel_path:
                    logger.warn(f"[{type_name}] Invalid package info: {package}")
                    continue
                deb_url = urljoin(base_url, deb_rel_path)
                save_dir = os.path.normpath(os.path.join(out_dir, version, repo, arch))
                os.makedirs(save_dir, exist_ok=True)
                save_path = os.path.join(save_dir, os.path.basename(deb_url))
                if cache and os.path.exists(save_path + ".json"):
                    logger.info(f"[{type_name}] Skipping {deb_url}")
                    continue
                delay = random.randint(0, randint)
                time.sleep(delay)
                try:
                    download_file(deb_url, save_path=save_path, save=save, callback=_parse_deb, type_name=type_name,
                                  timeout=timeout, additional=additional)
                except Exception as e:
                    logger.error(f"[{type_name}] Failed to process {deb_url}: {e}")
        except Exception as e:
            logger.error(f"[{type_name}] Failed to process packages file {index_packages_url}: {e}")
            continue
