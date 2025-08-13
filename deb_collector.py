import os
import gzip
import requests
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

DEB_MIRROR = "http://archive.ubuntu.com/ubuntu/dists/jammy/main/binary-amd64"

def _download_file(url, output_dir, callback=None):
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, os.path.basename(url))
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        with open(file_path, "wb") as f:
            f.write(r.content)
        print(f"[Deb] Downloaded {url}")
        if callback:
            callback(file_path)
    except Exception as e:
        print(f"[Deb] Failed {url}: {e}")

def collect_deb(output_dir="downloads/deb", parallel=False, callback=None):
    os.makedirs(output_dir, exist_ok=True)
    index_url = f"{DEB_MIRROR}/Packages.gz"
    print(f"[Deb] Downloading index from {index_url}...")
    resp = requests.get(index_url, timeout=30)
    resp.raise_for_status()

    pkg_list = []
    pkg_info = {}

    with gzip.open(BytesIO(resp.content), "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                if "Filename" in pkg_info:
                    pkg_list.append(pkg_info["Filename"])
                pkg_info = {}
            else:
                if line.startswith("Filename:"):
                    pkg_info["Filename"] = line.split(":", 1)[1].strip()

    print(f"[Deb] Found {len(pkg_list)} packages.")
    base_url = DEB_MIRROR.rsplit("/dists/", 1)[0]

    if parallel:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(_download_file, f"{base_url}/{path}", output_dir, callback)
                for path in pkg_list
            ]
            for _ in as_completed(futures):
                pass
    else:
        for path in pkg_list:
            _download_file(f"{base_url}/{path}", output_dir, callback)
