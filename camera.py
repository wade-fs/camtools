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
    """(舊版) 僅在 CAM_DIR 尋找特定副檔名檔案，用於 -l 和 -d 統計模式。"""
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(CAM_DIR, f"*.{ext}")))
    return files

def resolve_files(patterns, require_mp4=True):
    """
    根據使用者輸入的 patterns (可能包含通配符或無副檔名) 尋找檔案。
    - 搜尋路徑: Camera/ 和 ./
    - 預設副檔名: .mp4 (如果 require_mp4 為 True)
    """
    found_files = set()
    for pattern in patterns:
        base, ext = os.path.splitext(pattern)
        
        # 1. 處理副檔名：如果要求 .mp4 且使用者未指定副檔名，則強制加上 .mp4
        if require_mp4 and not ext:
            pattern_to_search = pattern + ".mp4"
        else:
            pattern_to_search = pattern

        # 2. 搜尋當前目錄和 Camera/
        for search_dir in ['.', CAM_DIR]:
            # 注意: os.path.join 在這裡可能導致錯誤的路徑組合，
            # 必須確保模式是相對路徑，然後 join。
            if os.path.isabs(pattern_to_search):
                 # 如果是絕對路徑，只搜索一次
                if os.path.isfile(pattern_to_search):
                    found_files.add(pattern_to_search)
                break
            
            full_pattern = os.path.join(search_dir, pattern_to_search)
            for f in glob.glob(full_pattern, recursive=False):
                # 確保找到的是檔案
                if os.path.isfile(f):
                    found_files.add(f)

    # 確保返回的檔案路徑是獨特的且已排序
    return sorted(list(found_files))


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

def shorten_video(input_file, target_seconds):
    """縮短影片至目標秒數。會覆蓋 input_file。"""
    duration = get_duration(input_file)
    if duration <= target_seconds:
        print(f"總長度 {duration:.2f}s <= {target_seconds}s，不需要縮短")
        return
    print(f"總長度 {duration:.2f}s > {target_seconds}s，開始縮短 (目標 {target_seconds}s)")

    v_speed = duration / target_seconds # 影片加速因子 (PTS 縮減)
    a_speed = duration / target_seconds # 音訊加速因子 (atempo 增加)

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", input_file],
        capture_output=True, text=True
    )
    has_audio = bool(out.stdout.strip())

    # 產生 atempo filter
    a_speed_f = a_speed
    atempo_filters = []
    while a_speed_f > 2.0:
        atempo_filters.append("atempo=2.0")
        a_speed_f /= 2.0
    if a_speed_f > 0.01:
        atempo_filters.append(f"atempo={a_speed_f}")
    
    atempo_str = ",".join(atempo_filters)
    
    # 影片 PTS 調整 (加速 factor 是 1/v_speed)
    pts_str = f"setpts={1/v_speed}*PTS"

    tmp_out = f"/tmp/shortened.{os.getpid()}.mp4"

    cmd = ["ffmpeg", "-y", "-i", input_file]
    
    if has_audio and atempo_filters:
        filter_complex = f"[0:v]{pts_str}[v];[0:a]{atempo_str}[a]"
        cmd.extend(["-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]", tmp_out])
    else:
        filter_complex = f"[0:v]{pts_str}[v]"
        cmd.extend(["-filter_complex", filter_complex, "-map", "[v]", "-an", tmp_out])

    print(f"執行 FFmpeg: {' '.join(cmd)}")
    # 隱藏 ffmpeg 輸出
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    
    # 使用 shutil.move 處理跨裝置移動 (例如 /tmp 到 /home)
    shutil.move(tmp_out, input_file)
    
    new_duration = get_duration(input_file)
    print(f"縮短完成，新長度為 {new_duration:.2f}s")

def parse_time_str(ts):
    """將 'mm:ss.ms' 或 'ss.ms' 轉成秒數"""
    if ':' in ts:
        m, s = ts.split(':', 1)
        return int(m) * 60 + float(s)
    else:
        return float(ts)

def slice_video(input_file, slice_range, output_file):
    """裁剪影片區間並輸出到指定的 output_file。"""
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
    examples = f"""
範例用法:
  # 1. (統計) 顯示最新一天的影片清單 (-l, -d, -i 不變)
  ./camera.py -l

  # 2. (統計) 顯示所有照片 (jpg/heic) 的日期統計
  ./camera.py -d -t p

  # 3. (資訊) 顯示多個檔案的總長度 (支援 Camera/ 或 ./ 路徑)
  ./camera.py -i "fileC.mp4 Camera/fileD.mp4"

  # 4. (合併 -m) 合併指定的影片檔案 (支援通配符 *、自動加 .mp4)
  #    輸出: {TODAY}-merge.mp4
  ./camera.py -m "20230101_12* 20230101_13" 

  # 5. (縮短 -p -s) 尋找 Camera/ 或 ./ 下以 'test' 開頭的 mp4 檔
  #    -> 將所有找到的檔案先合併 -> 將合併結果縮短至 30 秒
  #    輸出: {TODAY}-shorten.mp4
  ./camera.py -p test -s 30

  # 6. (切片 -p -S) 尋找 Camera/ 或 ./ 下以 'VID_20240101' 開頭的 mp4 檔
  #    -> 對每一個找到的檔案獨立裁剪 5 秒 到 15.5 秒區間
  #    輸出: VID_20240101_xxxx.mp4 -> VID_20240101_xxxx-slice.mp4
  ./camera.py -p VID_20240101 -S 5-15.5
    """

    parser = argparse.ArgumentParser(
        description="Camera 影片工具：統計、合併、縮短、切片 (依賴 ffprobe/ffmpeg)",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=examples
    )
    
    parser.add_argument("-l", "--last", action="store_true", help="[統計] 顯示最新日期影片的檔案清單。")
    parser.add_argument("-d", "--date", action="store_true", help="[統計] 顯示所有檔案按日期的數量統計。")
    parser.add_argument("-t", "--type", choices=["m", "p"], default="m", 
                        help="[統計] 統計模式的檔案類型 (m=影片 mp4, p=照片 heic/jpg)。")
    
    parser.add_argument("-i", "--info", 
                        help='[資訊] 顯示指定檔案（可多個）的長度與總長度 (支援 Camera/ 或 ./ 路徑)。')
    
    parser.add_argument("-m", "--merge", 
                        help='[合併] 合併指定檔案清單 (支援通配符 *、自動加 .mp4)。輸出: YYYYmmdd-merge.mp4')
    
    parser.add_argument("-p", "--prefix", 
                        help="[縮短/切片] 設定要處理的檔案前綴 (例如: 'VID_20240101')。必須搭配 -s 或 -S 使用，僅搜尋 *.mp4 檔案。")
    parser.add_argument("-s", "--shorten", type=float, 
                        help="[縮短] 搭配 -p，將所有符合前綴的影片合併後，縮短至指定秒數。輸出: YYYYmmdd-shorten.mp4")
    parser.add_argument("-S", "--slice", 
                        help="[切片] 搭配 -p，對每個符合前綴的影片獨立裁剪區間 (例如: 5-15.5 或 1:30-2:00.5)。")
    
    args = parser.parse_args()

    if not os.path.isdir(CAM_DIR):
        print(f"錯誤: 找不到 {CAM_DIR} 目錄，請確認當前工作目錄結構")
        # 如果是純粹的縮短/切片操作，且檔案不在 Camera/ 下，可以不退出
        # 但統計模式必須依賴 Camera/，因此保留這項檢查。
        # 讓 resolve_files 處理更彈性的路徑。
        pass 

    # --- 1. 統計模式 (-l, -d, -i) ---
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

    if args.info:
        file_names = args.info.split()
        files_to_info = resolve_files(file_names, require_mp4=False) # 允許非 mp4
        
        if not files_to_info:
            print("沒有找到檔案或檔案不存在")
            return

        total_duration_val = 0.0
        for f in files_to_info:
            duration = get_duration(f)
            total_duration_val += duration
            print(f"{f} {duration:.2f}秒")
        print(f"總長度 {total_duration_val:.2f}秒")
        return

    # --- 2. 處理 -m, -p 模式的互斥與組合 ---
    if args.merge and (args.shorten or args.slice or args.prefix):
        print("錯誤: -m (合併) 與 -p/-s/-S 不能同時使用。")
        sys.exit(1)
    
    if args.shorten and not args.prefix:
        print("錯誤: -s (縮短) 必須搭配 -p (前綴) 使用。")
        sys.exit(1)

    if args.slice and not args.prefix:
        print("錯誤: -S (切片) 必須搭配 -p (前綴) 使用。")
        sys.exit(1)
        
    # --- 3. 合併模式 (-m) ---
    if args.merge:
        patterns = args.merge.split()
        files_to_merge = resolve_files(patterns, require_mp4=True)
        
        if not files_to_merge:
            print(f"錯誤: 沒有找到符合的檔案: {args.merge}")
            sys.exit(1)

        output_file = f"{TODAY}-merge.mp4"
        concat_file = build_concat_file(files_to_merge)
        print(f"合併影片輸出: {output_file}")
        
        try:
            subprocess.run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", output_file], check=True)
            print(f"完成，輸出檔案：{output_file}")
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg 合併失敗: {e}")
            sys.exit(1)
        finally:
            if os.path.exists(concat_file):
                os.remove(concat_file)
        return


    # --- 4. 縮短模式 (-p 和 -s) ---
    if args.prefix and args.shorten:
        # 規則 4: 找到檔案 -> 合併 (隱含) -> 縮短合併結果 -> 輸出 YYYYmmdd-shorten.mp4
        
        # 1. 根據前綴找出所有檔案
        patterns = [f"{args.prefix}*.mp4"]
        files_to_process = resolve_files(patterns, require_mp4=False)
        
        if not files_to_process:
            print(f"錯誤: 沒有找到符合前綴 '{args.prefix}' 的 .mp4 檔案")
            sys.exit(1)

        # 2. 暫時合併到 /tmp
        temp_merged_file = os.path.join("/tmp", f"temp_merge_shorten.{os.getpid()}.mp4")
        concat_file = build_concat_file(files_to_process)
        print(f"暫時合併 {len(files_to_process)} 個檔案到 {temp_merged_file}...")
        
        try:
            subprocess.run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", temp_merged_file], 
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg 暫時合併失敗: {e}")
            if os.path.exists(concat_file): os.remove(concat_file)
            sys.exit(1)
        
        if os.path.exists(concat_file): os.remove(concat_file)

        # 3. 將暫存檔移動到最終輸出位置，然後進行縮短 (縮短會覆蓋檔案)
        output_file = f"{TODAY}-shorten.mp4"
        shutil.move(temp_merged_file, output_file)
        
        # 4. 執行縮短
        shorten_video(output_file, args.shorten)
        return


    # --- 5. 切片模式 (-p 和 -S) ---
    if args.prefix and args.slice:
        # 規則 5: 對每個檔案獨立切片 -> 輸出 filename-slice.mp4
        
        # 1. 根據前綴找出所有檔案
        patterns = [f"{args.prefix}*.mp4"]
        files_to_slice = resolve_files(patterns, require_mp4=False)
        
        if not files_to_slice:
            print(f"錯誤: 沒有找到符合前綴 '{args.prefix}' 的 .mp4 檔案進行切片")
            sys.exit(1)

        print(f"準備對 {len(files_to_slice)} 個檔案執行獨立切片...")
        
        for input_file in files_to_slice:
            basename = os.path.splitext(os.path.basename(input_file))[0]
            output_file = f"{basename}-slice.mp4"
            
            try:
                slice_video(input_file, args.slice, output_file)
            except subprocess.CalledProcessError as e:
                print(f"FFmpeg 切片失敗 for {input_file}: {e}")
                
        print("所有切片操作完成。")
        return
        
    # --- 6. 錯誤處理 ---
    if not (args.last or args.date or args.info or args.merge or args.shorten or args.slice):
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()

