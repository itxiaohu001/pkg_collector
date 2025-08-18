import os
import random
import time
from urllib.parse import urljoin
import rpmfile
import hashlib
from utils import save_json, file_hash, get_links, logger, download_file

RPM_KEYS = ['size', 'epoch', 'name', 'version', 'release', 'summary',
            'description', 'buildtime', 'buildhost', 'distribution', 'vendor', 'copyright', 'packager', 'group',
            'url', 'os', 'arch', 'sourcerpm', 'provides', 'requirename', 'requireversion', 'requireflags',
            'conflictflags', 'conflictname', 'conflictversion', 'rpmversion', 'archive_format']

os_dir_version_key = "os_dir_version"


def safe_bytes(val):
    if isinstance(val, bytes):
        # 尝试解码，如果不是文本就转 hex
        try:
            return val.decode(errors='ignore')
        except Exception:
            return val.hex()
    return val


def parse_rpm_basic(rpm_path, additional):
    os_version = ""
    if additional:
        os_version = additional[os_dir_version_key]

    result = {
        os_dir_version_key: os_version,
        "source_hash": file_hash(rpm_path),
        "files": []
    }

    with rpmfile.open(rpm_path) as rpm:
        hdr = rpm.headers

        # 遍历 key 列表
        for key in RPM_KEYS:
            val = hdr.get(key)
            if val is not None:
                if isinstance(val, list):
                    val = [safe_bytes(v) for v in val]
                else:
                    val = safe_bytes(val)
                result[key] = val

        # 文件列表
        for member in rpm.getmembers():
            full_path = member.name
            size = member.size
            if size == 0:
                continue

            md5 = None
            try:
                # 提取文件内容
                fobj = rpm.extractfile(member.name)
                if fobj:
                    data = fobj.read()
                    md5 = hashlib.md5(data).hexdigest()  # 标准 32 字符 MD5
            except KeyError:
                # 有些成员可能无法提取
                pass

            result["files"].append({
                "path": full_path,
                "size": size,
                "md5": md5
            })

        save_json(result, rpm_path + ".json")


def search_rpm_urls(url, rpm_urls, type_name):
    logger.info(f"[{type_name}] Searching rpm from {url}...")
    subs = get_links(url, pattern=r'^(?!\.\.).*\/$|.*\.rpm$')
    for sub in subs:
        sub_url = urljoin(url, sub)
        if not sub:
            continue
        if sub.endswith(".rpm"):
            rpm_urls.append(sub_url)
        elif sub.endswith("/"):
            try:
                search_rpm_urls(sub_url, rpm_urls, type_name)
            except Exception as e:
                logger.info(f"[{type_name}] Failed {sub}: {e}")
                continue


def collect_rpm(output_dir="downloads/rpm", base_url="", type_name="Centos", timeout=60, save=False, randint=2,
                cache=True):
    os.makedirs(output_dir, exist_ok=True)
    url_version = {}

    versions = get_links(base_url, pattern=r'^\d.*\/$')
    for version in versions:
        version_url = urljoin(base_url, version)
        try:
            rpm_urls = []
            search_rpm_urls(version_url, rpm_urls, type_name)
            for rpm_url in rpm_urls:
                url_version[rpm_url] = version
        except Exception as e:
            logger.info(f"[{type_name}] Failed {version_url}: {e}")

    cur = 0
    for url, version in url_version.items():
        save_dir = os.path.normpath(os.path.join(output_dir, version))
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, os.path.basename(url))
        if cache and os.path.exists(save_path+".json"):
            logger.info(f"[{type_name}] Skipping {url}")
            continue
        delay = random.randint(0, randint)
        time.sleep(delay)
        try:
            additional = {os_dir_version_key: version}
            logger.info(f"[{type_name}] Processing {url} {cur}/{len(url_version)}")
            download_file(url, save_path, callback=parse_rpm_basic, type_name=type_name,
                          timeout=timeout, additional=additional, save=save)
        except Exception as e:
            logger.error(f"[{type_name}] Failed {url}: {e}")
