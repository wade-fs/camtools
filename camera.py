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
LOCAL_DIR = os.path.expanduser("~/Pictures/Camera")  # For sync functionality
TODAY = datetime.now().strftime("%Y%m%d")

# -------------------
# 工具函式
# -------------------

def find_files(exts):
    """(舊版) 僅在 CAM_DIR 尋找特定副檔名檔案，用於 --last 和 --date 統計模式。"""
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
        
        # 處理副檔名：如果要求 .mp4 且使用者未指定副檔名，則強制加上 .mp4
        if require_mp4 and not ext and pattern not in ['.', CAM_DIR]: # 避免對 '.' 和 'Camera' 加上 .mp4
             pattern_to_search = pattern + ".mp4"
        else:
             pattern_to_search = pattern

        # 搜尋當前目錄和 Camera/
        for search_dir in ['.', CAM_DIR]:
            if os.path.isabs(pattern_to_search):
                if os.path.isfile(pattern_to_search):
                    found_files.add(pattern_to_search)
                break
            
            full_pattern = os.path.join(search_dir, pattern_to_search)
            for f in glob.glob(full_pattern, recursive=False):
                if os.path.isfile(f):
                    found_files.add(f)

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
    # 根據要求，顯示所有檔案按日期的數量統計，不再區分影片/照片類型
    dates = sorted({extract_date(f) for f in files if extract_date(f)})
    if not dates:
        print("沒有找到符合日期的檔案")
        return
        
    all_files = find_files(["mp4", "heic", "HEIC", "jpg", "JPG", "jpeg", "JPEG"])
    date_counts = {}
    
    for f in all_files:
        d = extract_date(f)
        if d:
            date_counts[d] = date_counts.get(d, 0) + 1
            
    sorted_dates = sorted(date_counts.keys())
    
    for d in sorted_dates:
        print(f"{d} = {date_counts[d]}")


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

    v_speed = duration / target_seconds
    a_speed = duration / target_seconds

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", input_file],
        capture_output=True, text=True
    )
    has_audio = bool(out.stdout.strip())

    a_speed_f = a_speed
    atempo_filters = []
    while a_speed_f > 2.0:
        atempo_filters.append("atempo=2.0")
        a_speed_f /= 2.0
    if a_speed_f > 0.01:
        atempo_filters.append(f"atempo={a_speed_f}")
    
    atempo_str = ",".join(atempo_filters)
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
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    
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

    try:
        start_str, end_str = slice_range.split('-', 1)
        start = parse_time_str(start_str)
        end = parse_time_str(end_str)
    except ValueError:
        print("錯誤: 時間格式解析錯誤，請確認輸入是否為 mm:ss.ms 或 ss.ms")
        sys.exit(1)

    if end <= start:
        print("錯誤: 結束時間必須大於開始時間")
        sys.exit(1)

    duration = end - start
    
    # 使用 -i 參數在 -ss 之前，配合 -c copy 會有更精確的切片效果（尤其對於關鍵影格）。
    # 但會略慢，為了精確性，調整順序
    cmd = [
        "ffmpeg", "-i", input_file, "-ss", str(start), "-to", str(end), # -to 替代 -t duration, 更精確
        "-c", "copy", output_file
    ]
    print(f"裁剪 {input_file} {start:.3f}s → {end:.3f}s (共 {duration:.3f}s) (輸出 {output_file})")
    subprocess.run(cmd, check=True)
    print(f"完成切片輸出：{output_file}")

# -------------------
# 同步功能 (來自 sync-camera.py)
# -------------------

def run_adb_command(args, capture_output=True, check=True):
    """Run an adb command and return the result."""
    try:
        result = subprocess.run(
            ["adb"] + args,
            capture_output=capture_output,
            text=True,
            check=check
        )
        return result
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e

def check_adb():
    """Check if adb is installed and a device is connected."""
    if not shutil.which("adb"):
        print("錯誤: adb 未安裝或不在 PATH 中")
        sys.exit(1)
    try:
        run_adb_command(["get-state"])
    except subprocess.CalledProcessError:
        print("錯誤: 沒有找到 adb 裝置，請確認已連線")
        sys.exit(1)

def check_remote_dir():
    """Check if the remote Camera directory exists."""
    result = run_adb_command(["shell", f"[ -d '{REMOTE_DIR}' ] && echo exists"], check=False)
    if result.returncode != 0 or "exists" not in result.stdout:
        print(f"錯誤: 遠端目錄 {REMOTE_DIR} 不存在")
        sys.exit(1)

def get_file_list(directory, is_remote=False):
    """Get sorted list of relative file paths from a directory."""
    if is_remote:
        # 排除 .trashed* 檔案
        cmd = ["shell", f"cd '{directory}' && find . -type f -not -name '.trashed*' -printf '%P\\n'"]
        result = run_adb_command(cmd)
        files = result.stdout.strip().splitlines()
    else:
        files = []
        for path in Path(directory).rglob("*"):
            if path.is_file():
                files.append(str(path.relative_to(directory)))
    return sorted(files)

def sync_files():
    """Sync files from REMOTE_DIR to LOCAL_DIR."""
    check_adb()
    check_remote_dir()
    os.makedirs(LOCAL_DIR, exist_ok=True)

    remote_files = get_file_list(REMOTE_DIR, is_remote=True)
    local_files = get_file_list(LOCAL_DIR, is_remote=False)
    new_files = sorted(set(remote_files) - set(local_files))

    if not new_files:
        print("✅ 已經是最新狀態，沒有新檔案")
        return
        
    for file in new_files:
        if file:
            local_path = os.path.join(LOCAL_DIR, file)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            print(f"正在下載 {file}...")
            run_adb_command(["pull", f"{REMOTE_DIR}/{file}", local_path])
    print("同步完成！")

def get_video_info(file_path):
    """🔹 取得影片的長度與解析度資訊"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    # print(shlex.join(cmd)) # 移除不必要的 debug 輸出
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    duration = 0.0
    width, height = (None, None)
    
    # 由於 ffprobe 輸出的順序可能是 (width, height, duration) 或只有 duration (非影片)
    # 這裡調整解析邏輯以避免索引錯誤
    if len(lines) >= 3 and lines[0].isdigit() and lines[1].isdigit():
        width = lines[0]
        height = lines[1]
        try:
            duration = float(lines[2])
        except ValueError:
            pass # duration 解析失敗，保持 0.0
    elif len(lines) == 1 and lines[0].replace('.', '', 1).isdigit():
        try:
            duration = float(lines[0])
        except ValueError:
            pass # duration 解析失敗，保持 0.0
    else:
        # print("⚠️ ffprobe 輸出異常，無法解析。") # 資訊模式不適合報錯
        pass
        
    return duration, width, height

def shrink_video(resolution, file_path):
    # print(f"shrink_video({resolution}, {file_path})") # 移除不必要的 debug 輸出
    # 驗證解析度格式，例如 "1024x768"
    if not re.match(r'^\d+x\d+$', resolution):
        print("錯誤: 解析度格式必須為 WxH，例如 640x480")
        sys.exit(1)

    # 檢查檔案是否存在
    if not os.path.exists(file_path):
        print(f"錯誤: 找不到檔案 {file_path}")
        sys.exit(1)

    base, ext = os.path.splitext(file_path)
    output_file = f"{base}-{resolution}{ext}"

    cmd = [
        "ffmpeg", "-i", file_path,
        "-vf", f"scale={resolution}",
        "-c:a", "copy",
        output_file
    ]

    print("執行命令：", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"✅ 已輸出: {output_file}")

# -------------------
# 主程式
# -------------------

def main():
    examples = f"""
範例用法:
  # 1. (統計) 顯示最新一天的影片清單
  ./camera.py -l
  # 2. (統計) 顯示所有檔案 (不分影片/照片) 的日期數量統計
  ./camera.py -d
  # 3. (資訊) 顯示多個檔案的長度與總長度 (支援 Camera/ 或 ./ 路徑)
  ./camera.py -i "fileC.mp4 Camera/fileD.mp4"
  # 4. (合併) 合併指定的影片檔案 (支援通配符 *、自動加 .mp4)
  ./camera.py -m -f "20230101_12* 20230101_13"
  # 5. (縮短) 尋找 Camera/ 或 ./ 下以 'test' 開頭的 mp4 檔
  #    -> 將所有找到的檔案先合併 -> 將合併結果縮短至 30 秒
  ./camera.py -s 30 -f "test*"
  # 6. (切片) 尋找 VID_20240101*.mp4 檔, 對**每個**檔案裁剪5秒到15.5秒區間
  ./camera.py -S 5-15.5 -f "VID_20240101*"
  # 7. (合併+縮短) 合併後縮短
  ./camera.py -m -s 45 -f "VID_20240201*"
  # 8. (合併+切片) 合併後切片
  ./camera.py -m -S 1:00-1:15 -f "VID_20240301*"
  # 9. (同步) 從手機 DCIM/Camera 同步新檔案到 {LOCAL_DIR}
  ./camera.py -y
    """

    parser = argparse.ArgumentParser(
        description="Camera 影片工具：統計、合併、縮短、切片、同步手機檔案 (依賴 ffprobe/ffmpeg/adb)",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=examples
    )
    
    # 統計/資訊
    parser.add_argument("-l", "--last", action="store_true", help="[統計] 顯示最新日期影片的檔案清單。")
    parser.add_argument("-d", "--date", action="store_true", help="[統計] 顯示所有檔案按日期的數量統計。")
    parser.add_argument("-i", "--info", 
        help="[資訊] 顯示指定檔案（可多個）的長度與總長度。")
    
    # 處理功能
    parser.add_argument("-f", "--files",
        help="[處理] 設定要處理的檔案清單 (可包含通配符)。")
    parser.add_argument("-m", "--merge", action="store_true", 
        help="[合併] 合併 --files 指定的影片檔案。")
    parser.add_argument("-s", "--shorten", type=float, 
        help="[縮短] 將影片縮短至指定秒數。若搭配 -m，則先合併再縮短。")
    parser.add_argument("-S", "--slice", 
        help="[切片] 對影片裁剪區間 (例如: 5-15.5)。若搭配 -m，則先合併再切片。")
    parser.add_argument("--shrink", nargs=2, metavar=("RESOLUTION", "FILE"),
        help="Shrink video to given resolution (e.g. 1024x768 input.mp4)")
        
    # 同步功能
    parser.add_argument("-y", "--sync", action="store_true", 
        help="[同步] 從手機 DCIM/Camera 同步新檔案到本地目錄。")
    
    args = parser.parse_args()

    # Check if no arguments are provided (to show help)
    if not any(vars(args).values()) or args.files and not (args.merge or args.shorten or args.slice):
        parser.print_help()
        sys.exit(0)

    # --- 1. 同步模式 (--sync) ---
    if args.sync:
        if any([args.last, args.date, args.info, args.merge, args.files, args.shorten, args.slice, args.shrink]):
            print("錯誤: --sync 不能與其他處理選項同時使用")
            sys.exit(1)
        sync_files()
        return

    # --- 2. 統計模式 (--last, --date, --info) ---
    if args.last or args.date:
        if any([args.info, args.merge, args.files, args.shorten, args.slice, args.shrink]):
            print("錯誤: --last 或 --date 不能與其他處理選項同時使用")
            sys.exit(1)
            
        # 統計模式只在 CAM_DIR 找檔案
        if args.last:
            files = find_files(["mp4"]) # --last 僅適用於影片
            if not files:
                print("沒有找到符合的影片檔案")
                return
            show_last(files)
        else: # --date (統計所有檔案)
            show_date(None) # show_date 內部會查找所有檔案
        return

    if args.info:
        if any([args.merge, args.files, args.shorten, args.slice, args.shrink]):
            print("錯誤: --info 不能與其他處理選項同時使用")
            sys.exit(1)
        
        file_names = args.info.split()
        files_to_info = resolve_files(file_names, require_mp4=False)
    
        if not files_to_info:
            print("沒有找到檔案或檔案不存在")
            return
    
        total_duration_val = 0.0
        for f in files_to_info:
            duration, width, height = get_video_info(f)
            total_duration_val += duration
            if width and height:
                print(f"{f}  {duration:.2f}秒  ({width}x{height})")
            else:
                print(f"{f}  {duration:.2f}秒")
        print(f"總長度 {total_duration_val:.2f}秒")
        return


    # --- 3. 處理模式 (合併, 縮短, 切片) ---
    if args.merge or args.shorten or args.slice:
        if not args.files:
            print("錯誤: --merge, --shorten, 或 --slice 必須搭配 --files 使用。")
            sys.exit(1)

        patterns = args.files.split()
        files_to_process = resolve_files(patterns, require_mp4=True)
        
        if not files_to_process:
            print(f"錯誤: 沒有找到符合檔案模式 '{args.files}' 的 .mp4 檔案")
            sys.exit(1)
            
        is_chain_process = args.merge and (args.shorten or args.slice) # 合併後接縮短/切片
        
        if is_chain_process:
            # 模式 1: 合併 -> (縮短 或 切片)
            temp_merged_file = os.path.join("/tmp", f"temp_merge_chain.{os.getpid()}.mp4")
            concat_file = build_concat_file(files_to_process)
            
            print(f"步驟 1/2: 暫時合併 {len(files_to_process)} 個檔案到 {temp_merged_file}...")
            try:
                subprocess.run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", temp_merged_file], 
                                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                print(f"FFmpeg 暫時合併失敗: {e}")
                sys.exit(1)
            finally:
                if os.path.exists(concat_file): os.remove(concat_file)

            output_file_base = f"{TODAY}-{re.sub(r'[^\w\-]', '_', args.files)}" # 嘗試用 files 參數命名
            
            if args.shorten:
                output_file = f"{output_file_base}-shorten.mp4"
                shutil.move(temp_merged_file, output_file)
                shorten_video(output_file, args.shorten)
            
            elif args.slice:
                output_file = f"{output_file_base}-slice.mp4"
                try:
                    slice_video(temp_merged_file, args.slice, output_file)
                except subprocess.CalledProcessError as e:
                    print(f"FFmpeg 切片失敗 for {temp_merged_file}: {e}")
                    sys.exit(1)
                finally:
                    if os.path.exists(temp_merged_file): os.remove(temp_merged_file) # 移除暫時合併檔
            
            if os.path.exists(temp_merged_file): os.remove(temp_merged_file) # 確保移除

            return

        elif args.merge:
            # 模式 2: 純合併 (--merge, -f)
            output_file = f"{TODAY}-merge.mp4"
            concat_file = build_concat_file(files_to_process)
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

        elif args.shorten:
            # 模式 3: 純縮短 (對每個檔案獨立縮短, -s, -f)
            print(f"準備對 {len(files_to_process)} 個檔案執行獨立縮短...")
            for input_file in files_to_process:
                shorten_video(input_file, args.shorten)
            print("所有縮短操作完成。")
            return

        elif args.slice:
            # 模式 4: 純切片 (對每個檔案獨立切片, -S, -f)
            print(f"準備對 {len(files_to_process)} 個檔案執行獨立切片...")
            
            for input_file in files_to_process:
                basename = os.path.splitext(os.path.basename(input_file))[0]
                output_file = f"{basename}-slice.mp4"
                
                try:
                    slice_video(input_file, args.slice, output_file)
                except subprocess.CalledProcessError as e:
                    print(f"FFmpeg 切片失敗 for {input_file}: {e}")
            
            print("所有切片操作完成。")
            return

    # --- 4. Shrink 模式 ---
    if args.shrink:
        # 為了正確解析檔案清單，需要從 argv 取得 RESOLUTION 後的參數
        # RESOLUTION 是 args.shrink[0]
        # FILEs 是 sys.argv[sys.argv.index("--shrink")+2:]
        try:
            arg_index = sys.argv.index("--shrink")
            if len(sys.argv) <= arg_index + 2:
                raise ValueError
            patterns = sys.argv[arg_index+2:]
        except (ValueError, IndexError):
            print("錯誤: --shrink 格式錯誤，必須為 --shrink RESOLUTION FILE [FILE...]")
            sys.exit(1)
            
        resolution = args.shrink[0]
        
        # 這裡需要檢查 --shrink 是否和其他操作模式衝突
        if any([args.last, args.date, args.info, args.merge, args.files, args.shorten, args.slice, args.sync]):
            print("錯誤: --shrink 不能與其他主要處理選項同時使用")
            sys.exit(1)

        files_to_shrink = resolve_files(patterns, require_mp4=False)
        if not files_to_shrink:
            print("錯誤: 沒有找到要縮小的檔案")
            sys.exit(1)
            
        for f in files_to_shrink:
            try:
                shrink_video(resolution, f)
            except subprocess.CalledProcessError as e:
                print(f"縮小失敗 {f}: {e}")
        return
        
    # --- last. 錯誤處理 ---
    parser.print_help()
    sys.exit(1)

if __name__ == "__main__":
    main()
