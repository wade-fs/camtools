#!/usr/bin/env python3
import argparse
import glob
import os
import subprocess
import sys
from datetime import datetime

CAM_DIR = "Camera"
TODAY = datetime.now().strftime("%Y%m%d")

def find_files(exts):
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(CAM_DIR, f"*.{ext}")))
    return files

def extract_date(filename):
    basename = os.path.basename(filename)
    import re
    m = re.match(r'(?:VID_)?(\d{8})', basename)
    return m.group(1) if m else None

def get_duration(file_path):
    """取得影片長度（秒）"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", file_path],
        capture_output=True, text=True
    )
    try:
        return float(out.stdout.strip())
    except:
        return 0.0

def show_last(files):
    dates = sorted({extract_date(f) for f in files if extract_date(f)})
    if not dates:
        print("沒有找到符合的檔案")
        return
    last_date = dates[-1]
    matched = [f for f in files if last_date in os.path.basename(f)]
    print(f"最新日期: {last_date}")
    for f in matched:
        dur = get_duration(f)
        print(f"{f}  ({dur:.2f}s)")
    print(f"總數: {len(matched)}")

def show_date(files):
    dates = sorted({extract_date(f) for f in files if extract_date(f)})
    for d in dates:
        count = sum(1 for f in files if d in os.path.basename(f))
        print(f"{d} = {count}")

def build_concat_file(files):
    list_file = os.path.join("/tmp", f"fflist.{os.getpid()}.txt")
    with open(list_file, "w") as f:
        for file_path in files:
            f.write(f"file '{os.path.abspath(file_path)}'\n")
    return list_file

def total_duration(files):
    total = 0.0
    for f in files:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", f],
            capture_output=True, text=True
        )
        total += float(out.stdout.strip())
    return total

def shorten_video(output_file, target_seconds):
    duration = total_duration([output_file])
    if duration <= target_seconds:
        print(f"總長度 {duration:.2f}s <= {target_seconds}s，不需要縮短")
        return
    print(f"總長度 {duration:.2f}s > {target_seconds}s，開始縮短")
    v_speed = target_seconds / duration
    a_speed = duration / target_seconds

    # 音訊處理
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", output_file],
        capture_output=True, text=True
    )
    has_audio = bool(out.stdout.strip())

    # 產生 atempo filter
    a_speed_f = a_speed
    atempo_filters = []
    while a_speed_f > 2.0:
        atempo_filters.append("atempo=2.0")
        a_speed_f /= 2.0
    atempo_filters.append(f"atempo={a_speed_f}")
    atempo_str = ",".join(atempo_filters)

    tmp_out = f"/tmp/shortened.{os.getpid()}.mp4"

    if has_audio:
        cmd = [
            "ffmpeg", "-i", output_file,
            "-filter_complex", f"[0:v]setpts={v_speed}*PTS[v];[0:a]{atempo_str}[a]",
            "-map", "[v]", "-map", "[a]", tmp_out
        ]
    else:
        cmd = [
            "ffmpeg", "-i", output_file,
            "-filter_complex", f"[0:v]setpts={v_speed}*PTS[v]",
            "-map", "[v]", "-an", tmp_out
        ]
    subprocess.run(cmd, check=True)
    os.replace(tmp_out, output_file)

def main():
    parser = argparse.ArgumentParser(description="影片統計與合併工具")
    parser.add_argument("-l", "--last", action="store_true", help="顯示最新日期檔案清單")
    parser.add_argument("-d", "--date", action="store_true", help="顯示所有日期檔案數量")
    parser.add_argument("-t", "--type", choices=["m", "p"], default="m", help="檔案類型 (m=影片, p=照片)")
    parser.add_argument("-p", "--prefix", help="合併 Camera/PREFIX*.mp4，輸出 <prefix>-merged.mp4")
    parser.add_argument("-m", "--merge", help='合併指定檔案清單，輸出 TODAY-merged.mp4 (空格分隔)')
    parser.add_argument('-i', '--info', help='顯示總長度（秒數）')
    parser.add_argument("-s", "--shorten", type=float, help="縮短影片至指定秒數")
    args = parser.parse_args()

    if not os.path.isdir(CAM_DIR):
        print(f"錯誤: 找不到 {CAM_DIR} 目錄")
        sys.exit(1)

    if args.last or args.date:
        exts = ["mp4"] if args.type == "m" else ["heic","HEIC","jpg","JPG","jpeg","JPEG"]
        files = find_files(exts)
        if not files:
            print("沒有找到符合的檔案")
            return
        if args.last:
            show_last(files)
        else:
            show_date(files)
        return

    # 合併模式
    if args.prefix and args.merge:
        print("錯誤: -p 和 -m 不能同時使用")
        sys.exit(1)

    if args.prefix:
        files = sorted(glob.glob(os.path.join(CAM_DIR, f"{args.prefix}*.mp4")))
        if not files:
            print(f"錯誤: 沒有找到符合的檔案 {CAM_DIR}/{args.prefix}*.mp4")
            sys.exit(1)
        output_file = f"{args.prefix}-merged.mp4"
    elif args.merge:
        file_names = args.merge.split()
        files = []
        for f in file_names:
            fpath = os.path.join(CAM_DIR, f)
            if not os.path.isfile(fpath):
                print(f"錯誤: 檔案不存在 {fpath}")
                sys.exit(1)
            files.append(fpath)
        output_file = f"{TODAY}-merged.mp4"
    elif args.info:
        file_names = args.info.split()
        files = []
        total_duration = 0.0
        for f in file_names:
            fpath = os.path.join(CAM_DIR, f)
            if not os.path.isfile(fpath):
                print(f"錯誤: 檔案不存在 {fpath}")
                continue
            duration = get_duration(fpath)
            total_duration += duration
            print(f"{fpath} {duration}秒")
        print(f"總長度 {total_duration}秒")
        sys.exit(0)
    else:
        print("錯誤: 必須指定 -p 或 -m")
        sys.exit(1)

    # 建立 concat 清單
    concat_file = build_concat_file(files)
    print(f"合併影片輸出: {output_file}")
    subprocess.run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", output_file], check=True)

    # 縮短處理
    if args.shorten:
        shorten_video(output_file, args.shorten)

    os.remove(concat_file)
    print(f"完成，輸出檔案：{output_file}")

if __name__ == "__main__":
    main()
