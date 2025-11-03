import json
import requests
from bs4 import BeautifulSoup
import tarfile
import os
import zstandard as zstd
from utils import logger,save_json
import tempfile
import hashlib


def parse_packagesite_file(filename):
    """
    解析FreeBSD packagesite文件

    Args:
        filename (str): packagesite文件路径

    Returns:
        list: 包含所有包信息的字典列表
    """
    packages = []

    with open(filename, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line:
                continue

            try:
                # 解析每一行的JSON数据
                package_info = json.loads(line)
                packages.append(package_info)
            except json.JSONDecodeError as e:
                print(f"解析JSON时出错: {e}")
                print(f"问题行: {line}")
                continue

    return packages


def parse_packagesite_file_generator(filename):
    """
    使用生成器方式解析FreeBSD packagesite文件（适用于大文件）

    Args:
        filename (str): packagesite文件路径

    Yields:
        dict: 每个包的信息字典
    """
    with open(filename, 'r', encoding='utf-8') as file:
        for line_num, line in enumerate(file, 1):
            line = line.strip()
            if not line:
                continue

            try:
                package_info = json.loads(line)
                yield package_info
            except json.JSONDecodeError as e:
                print(f"第{line_num}行解析JSON时出错: {e}")
                continue


# 后续可能会变化
pkg_sets = ['FreeBSD:13:amd64','FreeBSD:13:aarch64','FreeBSD:14:amd64','FreeBSD:14:aarch64',
        'FreeBSD:15:amd64','FreeBSD:15:aarch64','FreeBSD:16:amd64','FreeBSD:16:aarch64']


def extract_href_list(url):
    """
    从URL提取所有href链接

    Args:
        url (str): 目标网页URL

    Returns:
        list: 包含所有href值的列表
    """
    try:
        # 发送请求获取网页内容
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # 解析HTML
        soup = BeautifulSoup(response.content, 'html.parser')

        # 提取所有href属性
        href_list = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            if href and href != '../':  # 过滤空链接和父目录
                href_list.append(href)

        return href_list

    except Exception as e:
        print(f"错误: {e}")
        return []


def extract_tzst_file(tzst_path, extract_path):
    """
    解压 .tzst 文件

    Args:
        tzst_path (str): .tzst 文件路径
        extract_path (str): 解压目标目录
    """
    try:
        # 先使用 zstd 解压，然后再用 tar 解包
        temp_tar = tzst_path + '.tar'

        # 使用 zstandard 解压
        with open(tzst_path, 'rb') as compressed:
            with open(temp_tar, 'wb') as decompressed:
                dctx = zstd.ZstdDecompressor()
                dctx.copy_stream(compressed, decompressed)

        # 解压 tar 文件
        with tarfile.open(temp_tar, 'r') as tar:
            tar.extractall(extract_path)

        # 清理临时文件
        os.remove(temp_tar)
        return True

    except Exception as e:
        print(f"解压失败: {e}")
        return False

def download_and_extract_packagesite_tzst(url,timeout, extract_path="packagesite",type_name=""):
    """
    下载并解压 .tzst 格式的 packagesite 文件
    """
    try:
        # 下载文件
        logger.info(f"[{type_name}] Downloading {url}")
        response = requests.get(url, stream=True, timeout=timeout)
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            logger.error(f"[{type_name}] Failed to download {url}: {response.status_code}")
            return False

        # 保存临时文件
        temp_file = "temp_packagesite.tzst"
        with open(temp_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        # 创建解压目录
        os.makedirs(extract_path, exist_ok=True)

        # 解压 .tzst 文件
        success = extract_tzst_file(temp_file, extract_path)

        if success:
            return True
        else:
            return False

    except Exception as e:
        logger.error(f"[{type_name}] Failed to download {url}: {str(e)}")
        return False
    finally:
        # 清理临时文件
        if os.path.exists(temp_file):
            os.remove(temp_file)

def get_pkg_file_hashes(pkg_url,timeout):
    """
    下载 FreeBSD pkg 文件并返回每个文件的相对路径及其哈希值。

    Args:
        pkg_url (str): .pkg 文件的完整 URL。
        timeout (int): 请求超时时间（秒）。

    Returns:
        list: 一个字典列表，每个字典包含：
              - 'path': 文件在 pkg 内的相对路径
              - 'md5': 文件的 MD5 哈希值
              - 'sha256': 文件的 SHA256 哈希值
        如果出错则返回 None。
    """
    # 创建临时目录用于下载和提取
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # 1. 下载文件
            local_pkg_path = os.path.join(temp_dir, "package.pkg")
            print(f"正在下载: {pkg_url}")
            response = requests.get(pkg_url, stream=True, timeout=timeout)
            response.raise_for_status()

            with open(local_pkg_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # 2. 提取 pkg 文件 (假设是 tar 格式)
            extracted_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extracted_dir)

            file_hashes = []
            with tarfile.open(local_pkg_path, 'r') as tar:
                # 获取所有成员（文件/目录）的信息
                for member in tar.getmembers():
                    if member.isfile():  # 只处理文件，忽略目录
                        # 提取单个文件到临时位置
                        extracted_file_path = tar.extractfile(member).read()

                        # 计算哈希值
                        md5_hash = hashlib.md5(extracted_file_path).hexdigest()
                        sha256_hash = hashlib.sha256(extracted_file_path).hexdigest()

                        # 存储结果 (member.name 是相对路径)
                        file_hashes.append({
                            'path': member.name,
                            'md5': md5_hash,
                            'sha256': sha256_hash
                        })

            return file_hashes

        except Exception as e:
            print(f"处理过程中出错: {e}")
            return None



def collect_freebsd(output_dir="downloads/freebsd", base_url="https://pkg.freebsd.org", type_name="FreeBSD", timeout=60, save=False, randint=2,
                cache=True):
    for pkg_set in pkg_sets:
        for release in extract_href_list(f"{base_url}/{pkg_set}"):
            if not release.endswith("/"):
                continue
            package_file_url = f"{base_url}/{pkg_set}/{release}packagesite.tzst"
            safe_pkg_set = pkg_set.replace(":","_",-1)
            extract_path = f"{output_dir}/{safe_pkg_set}/{release}"
            if download_and_extract_packagesite_tzst(package_file_url,extract_path=extract_path,type_name=type_name,timeout=timeout):
                logger.info(f"[{type_name}] Successfully downloaded packagesite.tzst for {package_file_url}")
                packages = parse_packagesite_file(f"{extract_path}/packagesite.yaml")
                logger.info(f"[{type_name}] Successfully parsed packagesite.yaml for {package_file_url},total {len(packages)} packages")
                for i,pkg in enumerate(packages):
                    repopath = pkg.get('repopath')
                    pkg_name = pkg.get('name')
                    pkg_version = pkg.get('version')
                    if not repopath or not pkg_name or not  pkg_version:
                        logger.error(f"[{type_name}] Invalid package: {pkg}")
                        continue
                    save_dist = f"{output_dir}/{safe_pkg_set}{release}/{pkg_name}_{pkg_version}.json"
                    # 如果save_dist存在，则无需重复下载
                    if cache and os.path.exists(save_dist):
                        continue
                    pkg_url = f"{base_url}/{pkg_set}/latest/{repopath}"
                    file_hashes = get_pkg_file_hashes(pkg_url,timeout=timeout)
                    pkg["file_hashes"] = file_hashes
                    save_json(pkg, save_dist)
# 使用示例
if __name__ == "__main__":
    collect_freebsd()