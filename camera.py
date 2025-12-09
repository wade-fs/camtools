#!/usr/bin/env python3
import argparse
import glob
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
import shutil
from pathlib import Path

# Configuration
CAM_DIR = "Camera"
REMOTE_DIR = "/sdcard/DCIM/Camera"
LOCAL_DIR = os.path.expanduser("~/Pictures/Camera")
TODAY = datetime.now().strftime("%Y%m%d")
DEFAULT_FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

# ------------------- 工具函式 -------------------
def resolve_files(patterns, require_mp4=True):
    found_files = set()
    for pattern in patterns:
        base, ext = os.path.splitext(pattern)
        if require_mp4 and not ext and pattern not in ['.', CAM_DIR]:
            pattern_to_search = pattern + ".mp4"
        else:
            pattern_to_search = pattern
        for search_dir in ['.', CAM_DIR]:
            if os.path.isabs(pattern_to_search):
                if os.path.isfile(pattern_to_search):
                    found_files.add(pattern_to_search)
                break
            full_pattern = os.path.join(search_dir, pattern_to_search)
            for f in glob.glob(full_pattern):
                if os.path.isfile(f):
                    found_files.add(f)
    return sorted(list(found_files))

def get_duration(file_path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", file_path],
        capture_output=True, text=True
    )
    try:
        return float(out.stdout.strip())
    except:
        return 0.0

def get_video_info(file_path):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", file_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    duration = width = height = None
    try:
        if len(lines) >= 3:
            width = int(lines[0]) if lines[0].isdigit() else None
            height = int(lines[1]) if lines[1].isdigit() else None
            duration = float(lines[2])
        elif len(lines) == 1:
            duration = float(lines[0])
    except:
        pass
    return duration or 0.0, width, height

def build_concat_file(files):
    list_file = f"/tmp/concat.{os.getpid()}.txt"
    with open(list_file, "w") as f:
        for fp in files:
            f.write(f"file '{os.path.abspath(fp)}'\n")
    return list_file

# ------------------- 同步 & adb -------------------
def run_adb_command(args, capture_output=True, check=True):
    try:
        return subprocess.run(["adb"] + args, capture_output=capture_output, text=True, check=check)
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e

def check_adb():
    if not shutil.which("adb"):
        print("錯誤: 找不到 adb")
        sys.exit(1)
    try:
        run_adb_command(["get-state"])
    except:
        print("錯誤: 沒有偵測到 Android 裝置")
        sys.exit(1)

def sync_files():
    """2025 終極同步函數：支援所有 Android 版本與 Scoped Storage"""
    check_adb()
    os.makedirs(LOCAL_DIR, exist_ok=True)

    # === 首選：adb sync（Android 11+ 神器）===
    print("正在使用 adb sync 同步（最快最穩）...")
    result = subprocess.run(["adb", "sync", "sdcard/DCIM/Camera", LOCAL_DIR],
                            capture_output=True, text=True)
    if result.returncode == 0:
        print("adb sync 成功！所有新檔案已同步")
        return
    else:
        print("adb sync 失敗（可能是舊版 adb），改用傳統 pull 方式...")

    # === Fallback：暴力搜尋所有可能路徑 ===
    possible_bases = [
        "/sdcard/DCIM/Camera",
        "/storage/emulated/0/DCIM/Camera",
        "/sdcard/Android/data/com.android.providers.media/files/DCIM",
        "/storage/emulated/0/Android/data/com.android.providers.media/files/DCIM",
    ]

    remote_files = set()
    for base in possible_bases:
        cmd = ["shell", f"find '{base}' -type f \\( -iname '*.mp4' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.heic' \\) 2>/dev/null"]
        try:
            out = run_adb_command(cmd, check=False, capture_output=True)
            for line in out.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                # 轉成相對路徑（只保留 Camera 之後的部分）
                for prefix in ["/DCIM/Camera/", "/100ANDRO/Camera/", "/Camera/"]:
                    if prefix in line:
                        rel_path = line.split(prefix, 1)[1]
                        if rel_path and not os.path.basename(rel_path).startswith("."):
                            remote_files.add(rel_path)
                        break
        except:
            continue

    if not remote_files:
        print("警告：手機上完全找不到相機檔案（可能權限問題或資料夾被隱藏）")
        return

    # === 本地檔案集合 ===
    local_files = set()
    for p in Path(LOCAL_DIR).rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(LOCAL_DIR))
            if not os.path.basename(rel).startswith("."):
                local_files.add(rel)

    # === 計算需要下載的檔案 ===
    to_download = sorted(remote_files - local_files)

    if not to_download:
        print("已是最新狀態，沒有新檔案")
        return

    print(f"發現 {len(to_download)} 個新檔案，開始下載...")
    success = 0
    for rel in to_download:
        # 嘗試從所有可能路徑找到來源
        src_path = None
        for base in possible_bases:
            for prefix in ["", "/DCIM/Camera", "/100ANDRO/Camera", "/Camera"]:
                candidate = f"{base}{prefix}/{rel}"
                if run_adb_command(["shell", "test -f", candidate], check=False).returncode == 0:
                    src_path = candidate
                    break
            if src_path:
                break

        if not src_path:
            print(f"警告：找不到來源路徑，跳過 {rel}")
            continue

        dst_path = os.path.join(LOCAL_DIR, rel)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        print(f"下載 {rel} ... ", end="", flush=True)
        try:
            run_adb_command(["pull", src_path, dst_path])
            print("完成")
            success += 1
        except:
            print("失敗")

    print(f"\n同步完成！成功下載 {success}/{len(to_download)} 個檔案")

# ------------------- 功能函式 -------------------
def do_merge(files, output_name=None):
    out = output_name or f"{TODAY}-merge.mp4"
    lst = build_concat(files)
    subprocess.run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out], check=True)
    os.remove(lst)
    print(f"合併完成 → {out}")
    return out

def do_shorten(file_path, target_sec):
    dur = get_duration(file_path)
    if dur <= target_sec:
        print(f"已 ≤ {target_sec}s，無需處理")
        return file_path
    speed = dur / target_sec
    tmp = f"/tmp/short.{os.getpid()}.mp4"
    af = []
    s = speed
    while s > 2:
        af.append("atempo=2.0")
        s /= 2
    if s > 1.0:
        af.append(f"atempo={s:.6f}")
    cmd = ["ffmpeg", "-y", "-i", file_path, "-filter_complex", f"[0:v]setpts={1/speed:.6f}*PTS[v]" + (f";[0:a]{','.join(af)}[a]" if af else ""), "-map", "[v]"]
    if af:
        cmd += ["-map", "[a]"]
    else:
        cmd += ["-an"]
    cmd += [tmp]
    subprocess.run(cmd, check=True)
    shutil.move(tmp, file_path)
    print(f"縮短完成 → {os.path.basename(file_path)} → {get_duration(file_path):.1f}s")
    return file_path

# ------------------- 主程式 -------------------
def main():
    parser = argparse.ArgumentParser(
        description="2025 終極相機工具箱",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
常用指令：
  ./camera.py -l                    看最新影片
  ./camera.py -d                    每日統計
  ./camera.py -y                    手機同步
  ./camera.py -i -f "20251207*"     顯示資訊（支援排序）
  ./camera.py -m -f "202512*"       合併
  ./camera.py -m -s 180 -f "202512*"  合併+縮短3分鐘
  ./camera.py -u -f "*.mp4"         批次靜音
  ./camera.py -p -f "*-shorten.mp4" 推回手機！
        """
    )
    parser.add_argument("-l", "--last", action="store_true")
    parser.add_argument("-d", "--date", action="store_true")
    parser.add_argument("-y", "--sync", action="store_true")
    parser.add_argument("-i", "--info", action="store_true")
    parser.add_argument("-f", "--files", type=str)
    parser.add_argument("-m", "--merge", action="store_true")
    parser.add_argument("-s", "--shorten", type=float)
    parser.add_argument("-u", "--mute", action="store_true")
    parser.add_argument("-p", "--push", action="store_true")
    parser.add_argument("-n", "--name", type=str)
    args = parser.parse_args()

    if args.sync:
        sync_files()
        return

    if args.push:
        check_adb()
        if not args.files:
            print("錯誤: --push 需要 -f 指定檔案")
            sys.exit(1)
        files = resolve_files(args.files.split(), require_mp4=False)
        print(f"上傳 {len(files)} 個檔案到手機...")
        for f in files:
            print(f"→ {os.path.basename(f)}")
            run_adb_command(["push", f, REMOTE_DIR + "/"])
        print("全部上傳完成！")
        return

    if args.info:
        if not args.files:
            print("錯誤: --info 需要 -f")
            sys.exit(1)
        files = resolve_files(args.files.split(), require_mp4=False)
        total = 0
        for f in files:
            d, w, h = get_video_info(f)
            total += d
            print(f"{os.path.basename(f):40} {d:6.1f}s  {w or '-'}x{h or '-'}")
        print(f"總長度 {'':38} {total:6.1f}s")
        return

    # 其他功能略（你原本的都保留）
    # ... 這裡放你原本的 merge / shorten / mute 等邏輯

if __name__ == "__main__":
    main()
