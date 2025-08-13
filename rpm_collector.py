import os
import gzip
import xml.etree.ElementTree as ET
import requests
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

RPM_MIRROR = "http://mirror.centos.org/centos/8-stream/BaseOS/x86_64/os"

def _download_file(url, output_dir, callback=None):
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, os.path.basename(url))
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        with open(file_path, "wb") as f:
            f.write(r.content)
        print(f"[RPM] Downloaded {url}")
        if callback:
            callback(file_path)
    except Exception as e:
        print(f"[RPM] Failed {url}: {e}")

def collect_rpm(output_dir="downloads/rpm", parallel=False, callback=None):
    os.makedirs(output_dir, exist_ok=True)
    repomd_url = f"{RPM_MIRROR}/repodata/repomd.xml"
    print(f"[RPM] Downloading repomd from {repomd_url}...")
    resp = requests.get(repomd_url, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    primary_href = None
    for data in root.findall("{http://createrepo.baseurl.org/metadata/repo}data"):
        if data.attrib.get("type") == "primary":
            location = data.find("{http://createrepo.baseurl.org/metadata/repo}location")
            primary_href = location.attrib["href"]
            break

    if not primary_href:
        print("[RPM] No primary metadata found!")
        return

    primary_url = f"{RPM_MIRROR}/{primary_href}"
    print(f"[RPM] Downloading primary data from {primary_url}...")
    r = requests.get(primary_url, timeout=30)
    r.raise_for_status()

    pkg_list = []
    with gzip.open(BytesIO(r.content), "rt", encoding="utf-8") as f:
        tree = ET.parse(f)
        root = tree.getroot()
        for pkg in root.findall("{http://linux.duke.edu/metadata/common}package"):
            location = pkg.find("{http://linux.duke.edu/metadata/common}location")
            href = location.attrib["href"]
            pkg_list.append(href)

    print(f"[RPM] Found {len(pkg_list)} packages.")

    if parallel:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(_download_file, f"{RPM_MIRROR}/{path}", output_dir, callback)
                for path in pkg_list
            ]
            for _ in as_completed(futures):
                pass
    else:
        for path in pkg_list:
            _download_file(f"{RPM_MIRROR}/{path}", output_dir, callback)
