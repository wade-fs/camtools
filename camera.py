#!/usr/bin/env python3
import argparse
import glob
import os
import re
import subprocess
import sys
from datetime import datetime
import shutil # 引入 shutil 處理跨裝置移動

CAM_DIR = "Camera"
TODAY = datetime.now().strftime("%Y%m%d")

# -------------------
# 工具函式
# -------------------

def find_files(exts):
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(CAM_DIR, f"*.{ext}")))
    return files

def extract_date(filename):
    basename = os.path.basename(filename)
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

def shorten_video(output_file, target_seconds):
    duration = get_duration(output_file)
    if duration <= target_seconds:
        print(f"總長度 {duration:.2f}s <= {target_seconds}s，不需要縮短")
        return
    print(f"總長度 {duration:.2f}s > {target_seconds}s，開始縮短 (目標 {target_seconds}s)")

    v_speed = duration / target_seconds # 影片加速因子 (PTS 縮減)
    a_speed = duration / target_seconds # 音訊加速因子 (atempo 增加)

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", output_file],
        capture_output=True, text=True
    )
    has_audio = bool(out.stdout.strip())

    # 產生 atempo filter
    a_speed_f = a_speed
    atempo_filters = []
    # atempo filter 限制單次最大為 2.0，超過需串接
    while a_speed_f > 2.0:
        atempo_filters.append("atempo=2.0")
        a_speed_f /= 2.0
    # 處理最後的餘數
    if a_speed_f > 0.01: # 避免生成 atempo=0.0 的錯誤
        atempo_filters.append(f"atempo={a_speed_f}")
    
    atempo_str = ",".join(atempo_filters)
    
    # 影片 PTS 調整
    pts_str = f"setpts={1/v_speed}*PTS"

    tmp_out = f"/tmp/shortened.{os.getpid()}.mp4"

    cmd = ["ffmpeg", "-y", "-i", output_file]
    filter_complex = ""
    
    if has_audio and atempo_filters:
        # 影片和音訊都加速
        filter_complex = f"[0:v]{pts_str}[v];[0:a]{atempo_str}[a]"
        cmd.extend(["-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]", tmp_out])
    else:
        # 僅影片加速 (無音訊或音訊加速因數接近 1.0)
        filter_complex = f"[0:v]{pts_str}[v]"
        cmd.extend(["-filter_complex", filter_complex, "-map", "[v]", "-an", tmp_out])

    print(f"執行 FFmpeg: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    
    # *** 修正錯誤: 使用 shutil.move 處理跨裝置移動的問題 ***
    shutil.move(tmp_out, output_file)
    
    new_duration = get_duration(output_file)
    print(f"縮短完成，新長度為 {new_duration:.2f}s")


def find_file_in_dirs(filename):
    """在 Camera/ 或當前目錄尋找檔案"""
    candidates = [
        os.path.join(CAM_DIR, filename),
        filename  # 當前目錄
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None

def parse_time_str(ts):
    """將 'mm:ss.ms' 或 'ss.ms' 轉成秒數"""
    if ':' in ts:
        m, s = ts.split(':', 1)
        return int(m) * 60 + float(s)
    else:
        return float(ts)

def slice_video(input_file, slice_range):
    """裁剪影片區間，例如 3.2-8.7 或 1:20.5-2:10.25"""
    if '-' not in slice_range:
        print("錯誤: --slice 格式錯誤，必須為 start-end (例如: 1:30-2:00.5)")
        sys.exit(1)

    start_str, end_str = slice_range.split('-', 1)
    try:
        start = parse_time_str(start_str)
        end = parse_time_str(end_str)
    except ValueError:
        print("錯誤: 時間格式解析錯誤，請確認輸入是否為 mm:ss.ms 或 ss.ms")
        sys.exit(1)

    if end <= start:
        print("錯誤: 結束時間必須大於開始時間")
        sys.exit(1)

    duration = end - start
    output_file = f"{TODAY}-slice.mp4"
    # 使用 -c copy (串流複製) 進行快速切片
    cmd = [
        "ffmpeg", "-ss", str(start), "-i", input_file, "-t", str(duration),
        "-c", "copy", output_file
    ]
    print(f"裁剪 {input_file} {start:.3f}s → {end:.3f}s (共 {duration:.3f}s) (輸出 {output_file})")
    subprocess.run(cmd, check=True)
    print(f"完成切片輸出：{output_file}")

# -------------------
# 主程式
# -------------------

def main():
    examples = """
範例用法:
  # 1. 顯示最新一天的影片清單
  ./camera.py -l

  # 2. 顯示所有照片 (jpg/heic) 的日期統計
  ./camera.py -d -t p

  # 3. 合併 'Camera/20230101*.mp4' 開頭的所有影片，輸出為 '20230101-merged.mp4'
  ./camera.py -p 20230101

  # 4. 合併指定的兩個影片檔案，輸出為 '20251019-merged.mp4' (當前日期)
  ./camera.py -m "Camera/fileA.mp4 Camera/fileB.mp4"

  # 5. 顯示多個檔案的總長度
  ./camera.py -i "fileC.mp4 Camera/fileD.mp4"

  # 6. 合併影片後，將結果 ('20230101-merged.mp4') 縮短至 30 秒 (影片及音訊都會加速)
  ./camera.py -p 20230101 -s 30

  # 7. 裁剪單一影片 'test.mp4' 的 1 分 30 秒 到 2 分 0.5 秒區間
  #    注意：-S 必須搭配 -p 或 -m 且只能指定一個檔案
  ./camera.py -m "test.mp4" -S 1:30-2:00.5
  
  # 8. 裁剪單一影片 'Camera/20230101-merged.mp4' 的 5 秒 到 15.5 秒區間
  ./camera.py -p 20230101 -S 5-15.5
    """

    parser = argparse.ArgumentParser(
        description="Camera 影片統計與合併工具 (依賴 ffprobe/ffmpeg)",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=examples
    )
    
    parser.add_argument("-l", "--last", action="store_true", help="顯示 Camera/ 目錄中最新日期影片的檔案清單與長度")
    parser.add_argument("-d", "--date", action="store_true", help="顯示所有影片/照片按日期的數量統計")
    parser.add_argument("-t", "--type", choices=["m", "p"], default="m", 
                        help="統計模式的檔案類型 (m=影片 mp4, p=照片 heic/jpg)")
    
    parser.add_argument("-p", "--prefix", 
                        help="合併 Camera/PREFIX*.mp4，輸出 <prefix>-merged.mp4")
    parser.add_argument("-m", "--merge", 
                        help='合併指定檔案清單，輸出 TODAY-merged.mp4 (多個檔案路徑以空格分隔)')
    
    parser.add_argument("-i", "--info", 
                        help='顯示指定檔案（可多個）的長度（秒數）與總長度')
    
    parser.add_argument("-s", "--shorten", type=float, 
                        help="將合併後的影片 (需搭配 -p 或 -m) 或單一影片縮短至指定秒數 (例如: -s 30)")
    parser.add_argument("-S", "--slice", 
                        help="裁剪單一影片區間。格式: start-end，時間可為 mm:ss.ms 或 ss.ms (例如: 1:30-2:00.5 或 5-15.5)")
    
    args = parser.parse_args()

    if not os.path.isdir(CAM_DIR):
        print(f"錯誤: 找不到 {CAM_DIR} 目錄")
        sys.exit(1)

    # --- 統計模式 ---
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

    # --- 顯示影片長度 ---
    if args.info:
        file_names = args.info.split()
        total_duration_val = 0.0
        for f in file_names:
            fpath = find_file_in_dirs(f)
            if fpath is None:
                print(f"錯誤: 檔案不存在 {f}")
                continue
            duration = get_duration(fpath)
            total_duration_val += duration
            print(f"{fpath} {duration:.2f}秒")
        print(f"總長度 {total_duration_val:.2f}秒")
        return

    # --- 切片模式 ---
    if args.slice:
        input_file = None
        # 切片需要從 -p 或 -m 確定單一輸入影片
        if args.prefix:
            files = sorted(glob.glob(os.path.join(CAM_DIR, f"{args.prefix}*.mp4")))
            if len(files) != 1:
                print("錯誤: --slice 僅支援單一影片 (prefix 需對應一個檔案)")
                sys.exit(1)
            input_file = files[0]
        elif args.merge:
            file_names = args.merge.split()
            if len(file_names) != 1:
                print("錯誤: --slice 僅支援單一影片")
                sys.exit(1)
            fpath = find_file_in_dirs(file_names[0])
            if fpath is None:
                print(f"錯誤: 檔案不存在 {file_names[0]}")
                sys.exit(1)
            input_file = fpath
        else:
            print("錯誤: --slice 必須搭配 --prefix 或 --merge 單一影片來指定輸入檔案")
            sys.exit(1)

        slice_video(input_file, args.slice)
        return

    # --- 合併模式 / 僅縮短模式 ---
    if args.prefix and args.merge:
        print("錯誤: -p 和 -m 不能同時使用")
        sys.exit(1)
    
    files = []
    output_file = None

    if args.prefix:
        files = sorted(glob.glob(os.path.join(CAM_DIR, f"{args.prefix}*.mp4")))
        if not files:
            print(f"錯誤: 沒有找到符合的檔案 {CAM_DIR}/{args.prefix}*.mp4")
            sys.exit(1)
        output_file = f"{args.prefix}-merged.mp4"
    elif args.merge:
        file_names = args.merge.split()
        for f in file_names:
            fpath = find_file_in_dirs(f)
            if fpath is None:
                print(f"錯誤: 檔案不存在 {f} (在 Camera/ 或當前目錄)")
                sys.exit(1)
            files.append(fpath)
        
        # 如果只指定一個檔案，且同時要求縮短 (-s)，則執行縮短單一檔案
        if len(files) == 1 and args.shorten and not args.prefix:
            # 必須使用 find_file_in_dirs 找到完整的路徑，避免在 /tmp 中操作
            target_file = find_file_in_dirs(file_names[0])
            if not target_file:
                print(f"錯誤: 找不到檔案 {file_names[0]} 進行縮短操作")
                sys.exit(1)
            
            print(f"偵測到僅縮短模式，目標檔案：{target_file}")
            shorten_video(target_file, args.shorten)
            return # 縮短完成，程式結束

        output_file = f"{TODAY}-merged.mp4"

    # 如果沒有 -p, -m, -i, -S 且沒有 -l, -d，則顯示錯誤
    if not files and not (args.last or args.date or args.info or args.slice):
        parser.print_help()
        sys.exit(1)
    
    # --- 執行合併 ---
    if files:
        concat_file = build_concat_file(files)
        print(f"合併影片輸出: {output_file}")
        # -safe 0 允許絕對路徑
        subprocess.run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", output_file], check=True)

        if args.shorten:
            shorten_video(output_file, args.shorten)

        os.remove(concat_file)
        print(f"完成，輸出檔案：{output_file}")

if __name__ == "__main__":
    main()

