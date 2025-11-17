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

# ==================== 在全域加入一個常數 ====================
SUBTITLE_FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"  # macOS
# Linux 常用："/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
# Windows 常用： "C:/Windows/Fonts/Arial.ttf"  (要用雙引號 + : 前面要跳脫)
# 你可以改成你系統有的中文字型，例如 PingFang SC、Noto Sans CJK 等
# ===========================================================

def add_subtitle(input_file, subtitle_file, position, output_file=None):
    """
    使用 ffmpeg 把純文字字幕燒進影片
    position 格式例如： "20:20" 或 "center" 或 "10:bottom-10"
    """
    if output_file is None:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}-sub{ext}"

    # 讓 ffmpeg 自動處理 end 關鍵字
    filter_complex = (
        f"subtitles={shlex.quote(subtitle_file)}"
        f":force_style='Alignment=10,FontName=Arial Unicode,FontSize=24,"
        f"PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,BackColour=&H00000000&,BorderStyle=1,"
        f"Outline=2,Shadow=1,MarginV=20'"
    )

    # 位置處理
    if position.lower() == "center":
        force_style += ",Alignment=5"   # 5 = 中間
    elif position.lower().startswith("bottom"):
        force_style += ",Alignment=4"   # 4 = 下中
    elif position.lower().startswith("top"):
        force_style += ",Alignment=8"   # 8 = 上中
    else:
        # 自訂位置 WxH
        try:
            x, y = position.split("x", 1)
            # ffmpeg subtitles 的座標是從左上角 (0,0)
            force_style += f",MarginL={int(x)},MarginV={int(y)}"
        except:
            print("⚠️ 位置格式錯誤，使用預設下中")
            force_style += ",Alignment=4"

    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf", filter_complex,
        "-c:a", "copy",
        output_file
    ]
    print(f"正在燒錄字幕 → {output_file}")
    print("執行命令：", shlex.join(cmd))
    subprocess.run(cmd, check=True)
    print(f"字幕完成：{output_file}")

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
        if require_mp4 and not ext:
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
    cmd = [
        "ffmpeg", "-ss", str(start), "-i", input_file, "-t", str(duration),
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
        cmd = ["shell", f"cd '{directory}' && find . -type f -not -name '.trashed*' -printf '%P\\n'"]
        result = run_adb_command(cmd)
        files = result.stdout.strip().splitlines()
    else:
        files = []
        for path in Path(directory).rglob("*"):
            if path.is_file():
                files.append(str(path.relative_to(directory)))
    return sorted(files)

def sync_files(check_only=False):
    """Sync files from REMOTE_DIR to LOCAL_DIR, or check for new files."""
    check_adb()
    check_remote_dir()
    os.makedirs(LOCAL_DIR, exist_ok=True)

    remote_files = get_file_list(REMOTE_DIR, is_remote=True)
    local_files = get_file_list(LOCAL_DIR, is_remote=False)
    new_files = sorted(set(remote_files) - set(local_files))

    if check_only:
        if new_files:
            print("⚠️ 有新的檔案尚未同步：")
            for file in new_files:
                print(file)
        else:
            print("✅ 已經是最新狀態，沒有新檔案")
    else:
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
    print(shlex.join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    duration = float(lines[0]) if lines and lines[0].replace('.', '', 1).isdigit() else 0.0
    width, height = (None, None)
    if len(lines) >= 3:
        width = lines[0]
        height = lines[1]
        duration = float(lines[2])
    else:
        print("⚠️ ffprobe 輸出異常，無法解析。")
    return duration, width, height

def shrink_video(resolution, file_path):
    print(f"shrink_video({resolution}, {file_path})")
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
  ./camera.py --last
  # 2. (統計) 顯示所有照片 (jpg/heic) 的日期統計
  ./camera.py --date --type p
  # 3. (資訊) 顯示多個檔案的總長度 (支援 Camera/ 或 ./ 路徑)
  ./camera.py --info "fileC.mp4 Camera/fileD.mp4"
  # 4. (合併) 合併指定的影片檔案 (支援通配符 *、自動加 .mp4)
  ./camera.py --merge "20230101_12* 20230101_13"
  # 5. (縮短) 尋找 Camera/ 或 ./ 下以 'test' 開頭的 mp4 檔
  #    -> 將所有找到的檔案先合併 -> 將合併結果縮短至 30 秒
  ./camera.py --prefix test --shorten 30
  # 6. (切片) 尋找 VID_20240101*.mp4 檔, 對每一個檔案裁剪5秒到15.5秒區間
  ./camera.py --prefix VID_20240101 --slice 5-15.5
  # 7. (同步) 檢查手機 DCIM/Camera 中是否有新檔案
  ./camera.py --check
  # 8. (同步) 從手機 DCIM/Camera 同步新檔案到 {LOCAL_DIR}
  ./camera.py --sync
    """

    parser = argparse.ArgumentParser(
        description="Camera 影片工具：統計、合併、縮短、切片、同步手機檔案 (依賴 ffprobe/ffmpeg/adb)",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=examples
    )
    
    parser.add_argument("--last", action="store_true", help="[統計] 顯示最新日期影片的檔案清單。")
    parser.add_argument("--date", action="store_true", help="[統計] 顯示所有檔案按日期的數量統計。")
    parser.add_argument("--type", choices=["m", "p"], default="m", 
        help="[統計] 統計模式的檔案類型 (m=影片 mp4, p=照片 heic/jpg)。")
    parser.add_argument("--info", 
        help="[資訊] 顯示指定檔案（可多個）的長度與總長度。")
    parser.add_argument("--merge", 
        help="[合併] 合併指定檔案清單。")
    parser.add_argument("--prefix", 
        help="[縮短/切片] 設定要處理的檔案前綴。必須搭配 --shorten 或 --slice 使用。")
    parser.add_argument("--shorten", type=float, 
        help="[縮短] 搭配 --prefix，將所有符合的影片合併後，縮短至指定秒數。")
    parser.add_argument("--slice", 
        help="[切片] 搭配 --prefix，對每個符合的影片裁剪區間 (例如: 5-15.5)")
    parser.add_argument("--check", action="store_true", 
        help="[同步] 檢查手機 DCIM/Camera 中是否有新檔案，列出清單但不下載。")
    parser.add_argument("--sync", action="store_true", 
        help="[同步] 從手機 DCIM/Camera 同步新檔案到本地目錄。")
    parser.add_argument("--shrink", nargs=2, metavar=("RESOLUTION", "FILE"),
        help="Shrink video to given resolution (e.g. 1024x768 input.mp4)")
    parser.add_argument("--text", metavar="SUBTITLE_FILE",
        help="加入純文字字幕檔（支援 .txt / .vtt / .srt）")
    parser.add_argument("--pos", default="top", metavar="WxH",
        help="字幕位置，預設 center。可用：center / bottom / top / 100x50")

    args = parser.parse_args()

    # Check if no arguments are provided (to show help)
    if not any(vars(args).values()):
        parser.print_help()
        sys.exit(0)

    # --- 1. 同步模式 (--sync, --check) ---
    if args.sync or args.check:
        if any([args.last, args.date, args.info, args.merge, args.prefix, args.shorten, args.slice]):
            print("錯誤: --sync 或 --check 不能與其他處理選項同時使用")
            sys.exit(1)
        sync_files(check_only=args.check)
        return

    # --- 2. 統計模式 (--last, --date, --info) ---
    if args.last or args.date:
        if any([args.info, args.merge, args.prefix, args.shorten, args.slice]):
            print("錯誤: --last 或 --date 不能與其他處理選項同時使用")
            sys.exit(1)
        exts = ["mp4"] if args.type == "m" else ["heic", "HEIC", "jpg", "JPG", "jpeg", "JPEG"]
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
        if any([args.merge, args.prefix, args.shorten, args.slice, args.shrink]):
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


    # --- 3. 處理 --merge, --prefix 模式的互斥與組合 ---
    if args.merge and (args.shorten or args.slice or args.prefix):
        print("錯誤: --merge 與 --prefix/--shorten/--slice 不能同時使用。")
        sys.exit(1)
    
    if args.shorten and not args.prefix:
        print("錯誤: --shorten 必須搭配 --prefix 使用。")
        sys.exit(1)

    if args.slice and not args.prefix:
        print("錯誤: --slice 必須搭配 --prefix 使用。")
        sys.exit(1)

    # --- 4. 合併模式 (--merge) ---
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

    # --- 5. 縮短模式 (--prefix 和 --shorten) ---
    if args.prefix and args.shorten:
        patterns = [f"{args.prefix}*.mp4"]
        files_to_process = resolve_files(patterns, require_mp4=False)
        
        if not files_to_process:
            print(f"錯誤: 沒有找到符合前綴 '{args.prefix}' 的 .mp4 檔案")
            sys.exit(1)

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

        output_file = f"{TODAY}-shorten.mp4"
        shutil.move(temp_merged_file, output_file)
        
        shorten_video(output_file, args.shorten)
        return

    # --- 6. 切片模式 (--prefix 和 --slice) ---
    if args.prefix and args.slice:
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

    # --- 7. Shrink 模式 ---
    if args.shrink:
        # 支援多個檔案或通配符
        patterns = sys.argv[sys.argv.index("--shrink")+2:]  # 取得 shrink 後的檔案清單
        if not patterns:
            print("錯誤: --shrink 需要至少一個檔案參數")
            sys.exit(1)
        resolution = args.shrink[0] if isinstance(args.shrink, list) else args.shrink
        files_to_shrink = resolve_files(patterns, require_mp4=False)
        if not files_to_shrink:
            print("錯誤: 沒有找到要縮小的檔案")
            sys.exit(1)
        for f in files_to_shrink:
            try:
                shrink_video(resolution,f)
            except subprocess.CalledProcessError as e:
                print(f"縮小失敗 {f}: {e}")
        return

    # --- 8. 加字幕模式 (-text) ---
    if args.text:
        if not os.path.exists(args.text):
            print(f"錯誤: 字幕檔不存在 {args.text}")
            sys.exit(1)

        # 如果有提供檔案，就處理這些；否則處理當前目錄 + Camera/ 所有 mp4
        if len(sys.argv) > sys.argv.index("--text") + 2:
            # 用戶在 -text 後面又打了檔案
            patterns = sys.argv[sys.argv.index("--text") + 2:]
            target_files = resolve_files(patterns, require_mp4=True)
        else:
            # 沒有指定檔案 → 預設處理最新的 merge 檔或今天的所有影片
            today_files = resolve_files([f"*{TODAY}*"], require_mp4=True)
            if today_files:
                target_files = today_files
            else:
                print("沒有指定要處理的影片，且找不到今天的影片")
                sys.exit(1)

        if not target_files:
            print("找不到符合的影片檔案")
            sys.exit(1)

        for video in target_files:
            add_subtitle(video, args.text, args.pos)
        return
        
    # --- last. 錯誤處理 ---
    parser.print_help()
    sys.exit(1)

if __name__ == "__main__":
    main()
