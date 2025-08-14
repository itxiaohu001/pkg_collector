import os
import gzip
import bz2
import lzma
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import get_links, logger, download_file, download_file, save_json, load_json

os_dir_version_key = "os_dir_version"
os_dir_repo_key = "os_dir_repo"
os_dir_arch_key = "os_dir_arch"

packages_rel_path_key = "Filename"  # Packages文件内deb资源的相对路径的key


def _get_package_infos(base_url, type_name, out_dir, cache):
    url_info = {}
    res = []
    cur = 0

    # 获取所有的Packages的url
    try:
        dists_url = urljoin(base_url, "dists/")
        versions = get_links(url=dists_url, pattern=r'^(?!\.\.).*\/$')
        packages_json_cache = os.path.join(out_dir, "packages_urls.json")
        if cache and os.path.exists(packages_json_cache):
            url_info = load_json(packages_json_cache)
        else:
            for version in versions:
                repo_url = urljoin(dists_url, version)
                repos = get_links(url=repo_url, pattern=r'^(?!\.\.).*\/$')
                for repo in repos:
                    arch_url = urljoin(repo_url, repo)
                    arches = get_links(url=arch_url, pattern=r'^binary-.*\/$')
                    for arch in arches:
                        packages_url = urljoin(arch_url, arch)
                        packages = get_links(packages_url, pattern=r'^Packages(?!.*/$).*$')
                        if len(packages) > 0:
                            # 存在多种格式的Packages压缩包的话只需要任选一个
                            package_url = urljoin(packages_url, packages[0])
                            url_info[package_url] = {}
                            url_info[package_url][os_dir_version_key] = version
                            url_info[package_url][os_dir_repo_key] = repo
                            url_info[package_url][os_dir_arch_key] = arch
        save_json(url_info, packages_json_cache)
        logger.info(f"[{type_name}] Found {len(url_info)} packages urls")
    except Exception as e:
        logger.error(f"[{type_name}] Failed to get packages url: {e}")
        return []

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
                file_dist = download_file(url=index_packages_url, save=True,
                                          save_dir=os.path.join(out_dir, version, repo, arch),
                                          type_name=type_name, timeout=60)
                if file_dist:
                    pkg_list = load_and_parse_packages(file_dist, version, repo, arch)
                    os.remove(file_dist)
            if len(pkg_list) > 0:
                save_json(pkg_list, json_cache)
                res += pkg_list
            else:
                logger.warn(f"[{type_name}] No packages found in {index_packages_url}")
        except Exception as e:
            logger.error(f"[{type_name}] Failed to process packages file: {e}")
            return []

    return res


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
    return parse_packages_file(content, version, repo, arch)


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


def collect_deb(base_url, output_dir, type_name, parallel=False,  timeout=60):
    os.makedirs(output_dir, exist_ok=True)

    all_pakages = _get_package_infos(base_url, type_name, output_dir, True)
    logger.info(f"[{type_name}] Found {len(all_pakages)} packages")

    if parallel:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for package in all_pakages:
                deb_rel_path = package[packages_rel_path_key]
                version = package[os_dir_version_key]
                repo = package[os_dir_repo_key]
                arch = package[os_dir_arch_key]
                if not version or not repo or not arch or not deb_rel_path:
                    logger.warn(f"[{type_name}] Invalid package info: {package}")
                    continue
                deb_url = urljoin(base_url, deb_rel_path)
                save_dir = os.path.join(output_dir, version, repo, arch)
                future = executor.submit(
                    download_file,
                    deb_url,
                    save_dir,
                    save=False,
                    callback=None,
                    type_name=type_name,
                    timeout=60,
                )
                futures.append(future)
            for _ in as_completed(futures):
                pass
    else:
        for package in all_pakages:
            deb_rel_path = package[packages_rel_path_key]
            version = package[os_dir_version_key]
            repo = package[os_dir_repo_key]
            arch = package[os_dir_arch_key]
            if not version or not repo or not arch or not deb_rel_path:
                logger.warn(f"[{type_name}] Invalid package info: {package}")
                continue
            deb_url = urljoin(base_url, deb_rel_path)
            save_dir = os.path.join(output_dir, version, repo, arch)
            download_file(deb_url, save_dir, save=False, callback=None, type_name=type_name, timeout=60)
