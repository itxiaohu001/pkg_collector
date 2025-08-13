import os
import tarfile
import requests
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

ALPINE_MIRROR = "https://dl-cdn.alpinelinux.org/alpine/latest-stable/main/x86_64"

def _download_file(url, output_dir, callback=None):
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, os.path.basename(url))
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        with open(file_path, "wb") as f:
            f.write(r.content)
        print(f"[Alpine] Downloaded {url}")
        if callback:
            callback(file_path)
    except Exception as e:
        print(f"[Alpine] Failed {url}: {e}")

def collect_alpine(output_dir="downloads/alpine", parallel=False, callback=None):
    os.makedirs(output_dir, exist_ok=True)
    index_url = f"{ALPINE_MIRROR}/APKINDEX.tar.gz"
    print(f"[Alpine] Downloading index from {index_url}...")
    resp = requests.get(index_url, timeout=30)
    resp.raise_for_status()

    tar = tarfile.open(fileobj=BytesIO(resp.content), mode="r:gz")
    apk_list = []
    pkg_info = {}

    for member in tar:
        if member.name == "APKINDEX":
            for line in tar.extractfile(member):
                line = line.decode("utf-8").strip()
                if not line:
                    if "F" in pkg_info:
                        apk_list.append(pkg_info["F"])
                    pkg_info = {}
                else:
                    key = line[0]
                    val = line[2:]
                    pkg_info[key] = val

    print(f"[Alpine] Found {len(apk_list)} packages.")

    if parallel:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(_download_file, f"{ALPINE_MIRROR}/{apk}", output_dir, callback)
                for apk in apk_list
            ]
            for _ in as_completed(futures):
                pass
    else:
        for apk in apk_list:
            _download_file(f"{ALPINE_MIRROR}/{apk}", output_dir, callback)
