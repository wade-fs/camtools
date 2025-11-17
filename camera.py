#!/usr/bin/env python3
import argparse
import glob
import os
import re
import shlex
import subprocess
import sys
import shutil
from datetime import datetime
from pathlib import Path

# ==================== 設定 ====================
CAM_DIR = "Camera"
REMOTE_DIR = "/sdcard/DCIM/Camera"
LOCAL_DIR = os.path.expanduser("~/Pictures/Camera")
TODAY = datetime.now().strftime("%Y%m%d")

# 字幕字型（請依你的系統調整）
SUBTITLE_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

# ==================== 工具函式 ====================
def run_cmd(cmd, **kwargs):
    print("執行:", shlex.join(cmd) if isinstance(cmd, list) else cmd)
    subprocess.run(cmd, check=True, **kwargs)

def resolve_files(patterns, require_mp4=True):
    """支援通配符、相對路徑、自動補 .mp4"""
    found = set()
    for p in patterns:
        base, ext = os.path.splitext(p)
        search = p if ext else (p + ".mp4" if require_mp4 else p)
        for base_dir in ['.', CAM_DIR]:
            full = os.path.join(base_dir, search)
            found.update(glob.glob(full))
    return sorted([f for f in found if os.path.isfile(f)])

def extract_date(filename):
    m = re.search(r'(?:VID_)?(\d{8})', os.path.basename(filename))
    return m.group(1) if m else None

def get_duration(file_path):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ], capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return 0.0

def get_video_info(file_path):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-show_entries", "format=duration",
           "-of", "csv=p=0", file_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    parts = [x for x in result.stdout.strip().split(',') if x]
    duration = float(parts[2]) if len(parts) >= 3 else 0.0
    width = parts[0] if len(parts) >= 1 else "?"
    height = parts[1] if len(parts) >= 2 else "?"
    return duration, width, height

def build_concat_list(files):
    list_file = f"/tmp/concat_list_{os.getpid()}.txt"
    with open(list_file, "w") as f:
        for fp in files:
            f.write(f"file '{os.path.abspath(fp)}'\n")
    return list_file

def shorten_video(input_file, target_sec):
    duration = get_duration(input_file)
    if duration <= target_sec:
        print(f"已 ≤ {target_sec}s，無需縮短")
        return
    speed = duration / target_sec
    tmp = f"/tmp/shortened_{os.getpid()}.mp4"
    # 加速影片
    vf = f"setpts={1/speed:.6f}*PTS"
    # 加速音訊（多次 atempo 避免超過限制）
    af = []
    s = speed
    while s > 2:
        af.append("atempo=2")
        s /= 2
    if s > 1:
        af.append(f"atempo={s}")
    filter_complex = f"[0:v]{vf}[v];[0:a]{','.join(af)}[a]" if af else f"[0:v]{vf}[v]"
    cmd = ["ffmpeg", "-y", "-i", input_file, "-filter_complex", filter_complex,
           "-map", "[v]", "-map", "[a]" if af else "", tmp]
    run_cmd(cmd)
    shutil.move(tmp, input_file)
    print(f"縮短完成 → {get_duration(input_file):.2f}s")

def slice_video(input_file, time_range, output_file):
    if '-' not in time_range:
        raise ValueError("時間範圍必須為 start-end")
    start_str, end_str = time_range.split('-', 1)
    def to_sec(t):
        if ':' in t:
            m, s = t.split(':')
            return int(m)*60 + float(s)
        return float(t)
    start = to_sec(start_str.strip())
    end = to_sec(end_str.strip())
    duration = end - start
    cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", input_file,
           "-t", str(duration), "-c", "copy", output_file]
    run_cmd(cmd)

def add_subtitle(video_file, subtitle_file, pos="center"):
    base, ext = os.path.splitext(video_file)
    output = f"{base}-sub{ext}"

    style = "FontName=Arial Unicode,FontSize=28,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,BorderStyle=3,Outline=2,Shadow=1"
    if pos.lower() == "center":
        style += ",Alignment=5"
    elif pos.lower() == "bottom":
        style += ",Alignment=4"
    elif pos.lower() == "top":
        style += ",Alignment=10"
    else:
        try:
            x, y = map(int, pos.split('x'))
            style += f",MarginL={x},MarginV={y}"
        except:
            style += ",Alignment=4"

    cmd = [
        "ffmpeg", "-y", "-i", video_file,
        "-vf", f"subtitles={shlex.quote(subtitle_file)}:force_style='{style}'",
        "-c:a", "copy", output
    ]
    run_cmd(cmd)
    print(f"字幕燒錄完成 → {output}")

# ==================== 手機同步 ====================
def adb_check():
    if not shutil.which("adb"):
        print("錯誤: 找不到 adb")
        sys.exit(1)
    try:
        subprocess.run(["adb", "get-state"], capture_output=True, check=True)
    except:
        print("錯誤: 沒有連接 Android 裝置")
        sys.exit(1)

def sync_or_check(check_only=False):
    adb_check()
    os.makedirs(LOCAL_DIR, exist_ok=True)
    remote_files = subprocess.run(
        ["adb", "shell", f"find '{REMOTE_DIR}' -type f -name '*.MP4' -o -name '*.JPG' -o -name '*.HEIC'"],
        capture_output=True, text=True).stdout.strip().splitlines()
    remote_files = [f[len(REMOTE_DIR)+1:] for f in remote_files if REMOTE_DIR in f]

    local_files = {p.relative_to(LOCAL_DIR).__str__() for p in Path(LOCAL_DIR).rglob("*") if p.is_file()}
    new_files = [f for f in remote_files if f not in local_files]

    if check_only:
        if new_files:
            print("有新檔案未同步：")
            for f in new_files[:20]: print("  " + f)
            if len(new_files) > 20: print(f"  ... 等共 {len(new_files)} 個")
        else:
            print("已是最新狀態")
    else:
        for f in new_files:
            local_path = os.path.join(LOCAL_DIR, f)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            print(f"下載 {f}")
            subprocess.run(["adb", "pull", f"{REMOTE_DIR}/{f}", local_path], check=True)
        print("同步完成")

# ==================== 主程式 ====================
def main():
    examples = """
範例用法：
  ./camera.py --last                    # 顯示最新一天的影片
  ./camera.py --date                    # 顯示所有日期統計（僅限 Camera/ 資料夾）
  ./camera.py --check                   # 只檢查有無新檔案
  ./camera.py --sync                    # 真正下載新檔案
  ./camera.py --info --file "VID_20250101*.mp4 Camera/*.mp4"
  ./camera.py --merge --file "20250101_12* 20250101_13*.mp4"
  ./camera.py --shorten 30 --file "test*.mp4"     # 合併後縮短到 30 秒
  ./camera.py --slice 5-15.5 --file "VID_20250101*.mp4"
  ./camera.py --shrink 1280x720 --file "*.mp4"
  ./camera.py --text --subtitle subtitles.txt --pos center --file "*.mp4"
  ./camera.py --text --subtitle time.srt --pos 50x100 --file "20250101-merge.mp4"
    """.strip()

    parser = argparse.ArgumentParser(
        description="手機相機影片管理工具（合併/縮短/切片/字幕/同步）",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=examples
    )

    # 獨立指令（不需要參數）
    parser.add_argument("--last", action="store_true", help="顯示最新一天的影片清單")
    parser.add_argument("--date", action="store_true", help="顯示 Camera/ 內所有檔案的日期統計")
    parser.add_argument("--check", action="store_true", help="檢查手機是否有新檔案（不下载）")
    parser.add_argument("--sync", action="store_true", help="從手機同步新檔案到 ~/Pictures/Camera")

    # 需要 --file 的指令群
    parser.add_argument("--info", action="store_true", help="顯示影片長度與解析度")
    parser.add_argument("--merge", action="store_true", help="合併多個影片（快速 concat）")
    parser.add_argument("--shorten", type=float, metavar="SEC", help="先合併再加速縮短到指定秒數")
    parser.add_argument("--slice", metavar="START-END", help="對每個影片切出指定區間（如 1:23-45.5）")
    parser.add_argument("--shrink", metavar="WxH", help="縮小解析度（如 1280x720）")
    parser.add_argument("--text", action="store_true", help="燒錄字幕到影片")

    # 共用參數
    parser.add_argument("--file", nargs="+", help="要處理的檔案（支援通配符、自動補 .mp4）")
    parser.add_argument("--pos", default="center", help="字幕位置：center / bottom / top / 100x50")
    parser.add_argument("--subtitle", help="字幕檔案（.srt / .vtt / .txt）")

    args = parser.parse_args()

    # 無參數時顯示說明
    if not any(vars(args).values()):
        parser.print_help()
        return

    # === 獨立功能 ===
    if args.last:
        files = glob.glob("Camera/*.mp4") + glob.glob("Camera/*.MP4")
        dates = sorted({extract_date(f) for f in files if extract_date(f)})
        if dates:
            last = dates[-1]
            matched = [f for f in files if last in f]
            print(f"最新日期: {last} （{len(matched)} 支）")
            for f in matched:
                print(f"  {os.path.basename(f)}  {get_duration(f):.2f}s")
        return

    if args.date:
        files = glob.glob("Camera/*.*")
        stats = {}
        for f in files:
            d = extract_date(f) or "未知"
            stats[d] = stats.get(d, 0) + 1
        for d in sorted(stats):
            print(f"{d}: {stats[d]} 個")
        return

    if args.check:
        sync_or_check(check_only=True)
        return
    if args.sync:
        sync_or_check(check_only=False)
        return

    # === 需要 --file 的功能 ===
    if not args.file and any([args.info, args.merge, args.shorten, args.slice, args.shrink, args.text]):
        print("錯誤: 這些指令必須搭配 --file 指定檔案")
        parser.print_help()
        sys.exit(1)

    files = resolve_files(args.file, require_mp4="merge" in sys.argv or "shorten" in sys.argv or "slice" in sys.argv)

    if not files:
        print("找不到符合的檔案")
        return

    # --info
    if args.info:
        total = 0
        for f in files:
            dur, w, h = get_video_info(f)
            total += dur
            print(f"{os.path.basename(f):30} {dur:6.2f}s  {w}x{h}")
        print(f"總長度: {total:.2f} 秒")
        return

    # --merge
    if args.merge:
        output = f"{TODAY}-merge.mp4"
        concat_list = build_concat_list(files)
        run_cmd(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", output])
        os.remove(concat_list)
        print(f"合併完成 → {output}")
        return

    # --shorten
    if args.shorten is not None:
        tmp = f"/tmp/temp_merge_{os.getpid()}.mp4"
        concat_list = build_concat_list(files)
        run_cmd(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", tmp])
        os.remove(concat_list)
        shutil.move(tmp, f"{TODAY}-shorten.mp4")
        shorten_video(f"{TODAY}-shorten.mp4", args.shorten)
        return

    # --slice
    if args.slice:
        for f in files:
            base = os.path.splitext(os.path.basename(f))[0]
            out = f"{base}-slice.mp4"
            slice_video(f, args.slice, out)
        print("所有切片完成")
        return

    # --shrink
    if args.shrink:
        if not re.match(r'^\d+x\d+$', args.shrink):
            print("解析度格式錯誤，需為 WxH")
            sys.exit(1)
        for f in files:
            base, ext = os.path.splitext(f)
            out = f"{base}-{args.shrink}{ext}"
            run_cmd(["ffmpeg", "-i", f, "-vf", f"scale={args.shrink}", "-c:a", "copy", out])
        return

    # --text
    if args.text:
        if not args.subtitle or not os.path.exists(args.subtitle):
            print("必須使用 --subtitle 指定存在的字幕檔")
            sys.exit(1)
        for f in files:
            add_subtitle(f, args.subtitle, args.pos)
        return

    parser.print_help()

if __name__ == "__main__":
    main()
