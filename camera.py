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
REMOTE_DIR = "/storage/emulated/0/DCIM/Camera"
LOCAL_DIR = os.path.expanduser("~/Pictures/Camera") # For sync functionality
TODAY = datetime.now().strftime("%Y%m%d")
LATEST_DATE_CONST = "LATEST_DATE"
DEFAULT_FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

# -------------------
# 工具函式
# -------------------
def find_files(exts):
    """在 CAM_DIR 尋找特定副檔名檔案，用於 --last 和 --date 統計模式。"""
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(CAM_DIR, f"*.{ext}")))
    return files

def resolve_files(patterns, require_mp4=True):
    """
    根據使用者輸入的 patterns (可能包含通配符或無副檔名) 尋找檔案。
    - 搜尋路徑: Camera/ 和 ./
    - 預設副檔名: .mp4 (如果 require_mp4 為 True)
    - 保持使用者輸入的順序，並排除重複檔案。
    """
    ordered_files = []
    seen = set()

    for pattern in patterns:
        base, ext = os.path.splitext(pattern)
        
        # 處理副檔名：如果要求 .mp4 且使用者未指定副檔名，則強制加上 .mp4
        if require_mp4 and not ext and pattern not in ['.', CAM_DIR]: # 避免對 '.' 和 'Camera' 加上 .mp4
            pattern_to_search = pattern + ".mp4"
        else:
            pattern_to_search = pattern
            
        # 暫存這一個 pattern 找到的檔案
        matched_for_pattern = []
        
        # 搜尋當前目錄和 Camera/
        for search_dir in ['.', CAM_DIR]:
            if os.path.isabs(pattern_to_search):
                if os.path.isfile(pattern_to_search):
                    matched_for_pattern.append(pattern_to_search)
                break
            
            full_pattern = os.path.join(search_dir, pattern_to_search)
            for f in glob.glob(full_pattern, recursive=False):
                if os.path.isfile(f):
                    matched_for_pattern.append(f)
                    
        # 針對這一個 pattern 找到的檔案進行排序 
        # (確保當使用萬用字元如 20260301* 時，展開的這批檔案能照時間/字母順序排列)
        matched_for_pattern.sort()

        # 依序加入最終清單，並利用 seen 集合過濾掉已經加入過的檔案
        for f in matched_for_pattern:
            # 正規化路徑 (把 ./file.mp4 轉成 file.mp4)，避免路徑寫法不同造成重複計算
            norm_f = os.path.normpath(f)
            if norm_f not in seen:
                seen.add(norm_f)
                ordered_files.append(norm_f)

    return ordered_files

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

def show_last(files, target_date=None):
    """ 顯示最新日期或指定日期的影片清單，並依檔名排序。 """
   
    if target_date:
        print(f"🔹 顯示指定日期 {target_date} 的影片清單:")
        date_to_show = target_date
    else:
        dates = sorted({extract_date(f) for f in files if extract_date(f)})
        if not dates:
            print("沒有找到符合的影片檔案")
            return
        date_to_show = dates[-1]
        print(f"🔹 顯示最新日期 {date_to_show} 的影片清單:")
       
    matched = [f for f in files if date_to_show in os.path.basename(f)]
   
    if not matched:
        print(f"在 {CAM_DIR} 中沒有找到日期為 {date_to_show} 的影片檔案。")
        return
    # 依檔名排序
    matched.sort(key=os.path.basename)
    for f in matched:
        dur = get_duration(f)
        print(f"{f} ({dur:.2f}s)")
    print(f"總數: {len(matched)}")

def show_date(files):
    """ 顯示所有檔案按日期的數量統計，並依日期排序。 """
   
    all_files = find_files(["mp4", "heic", "HEIC", "jpg", "JPG", "jpeg", "JPEG"])
    date_counts = {}
   
    for f in all_files:
        d = extract_date(f)
        if d:
            date_counts[d] = date_counts.get(d, 0) + 1
           
    if not date_counts:
        print("沒有找到符合日期的檔案")
        return
       
    # 依日期 (YYYYmmdd) 排序
    sorted_dates = sorted(date_counts.keys())
   
    print("🔹 所有檔案按日期的數量統計:")
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
    # 不把 stdout 全部吃掉，這樣 ffmpeg 出錯時可以看見原因
    subprocess.run(cmd, check=True)
   
    # 用縮短後的暫存檔替換 input_file（覆蓋）
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
        "ffmpeg", "-i", input_file, "-ss", str(start), "-to", str(end),
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
    """2025 終極同步函數：支援所有 Android 版本與 Scoped Storage"""
    check_adb()

    # === Fallback：暴力搜尋所有可能路徑 ===
    possible_bases = [
        REMOTE_DIR,
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
        print(f"下載 {rel}")
        try:
            run_adb_command(["pull", src_path, dst_path])
            print(f"完成 {rel}")
            success += 1
        except:
            print(f"失敗 {rel}")

    print(f"\n同步完成！成功下載 {success}/{len(to_download)} 個檔案")

def get_video_info(file_path):
    """🔹 取得影片的長度與解析度資訊
    回傳 (duration: float, width: int|None, height: int|None)
    此函式會盡量將 width/height 轉為 int；若解析度無法取得則回傳 None。
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    # 執行 ffprobe
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()

    duration = 0.0
    width = None
    height = None

    # ffprobe 典型輸出： width\nheight\nduration\n
    try:
        if len(lines) >= 3:
            # 安全轉型
            try:
                width = int(lines[0])
            except (ValueError, TypeError):
                width = None
            try:
                height = int(lines[1])
            except (ValueError, TypeError):
                height = None
            try:
                duration = float(lines[2])
            except (ValueError, TypeError):
                duration = 0.0
        elif len(lines) == 1:
            # 只有 duration
            try:
                duration = float(lines[0])
            except (ValueError, TypeError):
                duration = 0.0
    except Exception:
        # 防止意外的解析錯誤
        duration = 0.0
        width = None
        height = None

    return duration, width, height

def shrink_video(resolution, file_path):
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

def parse_pos(pos_str, width, height):
    pos_str = pos_str.lower()

    pos_map = {
        "top-left": {"Alignment": "4", "MarginV": "10"},
        "top-center": {"Alignment": "6", "MarginV": "0"},
        "top-right": {"Alignment": "7", "MarginV": "10"},
        "middle-left": {"Alignment": "8", "MarginV": "0"},
        "middle-center": {"Alignment": "8", "MarginL": "100", "MarginV": "0"},
        "middle-right": {"Alignment": "8", "MarginL": "200", "MarginV": "0"},
        "bottom-left": {"Alignment": "1", "MarginV": "10"},
        "bottom-center": {"Alignment": "2", "MarginV": "10"},
        "bottom-right": {"Alignment": "3", "MarginV": "10"},
        "top": {"Alignment": "6", "MarginV": "0"},
        "bottom": {"Alignment": "2", "MarginV": "10"},
        "center": {"Alignment": "8", "MarginV": "50"},
    }

    if pos_str in pos_map:
        return pos_map[pos_str]
    print(f"錯誤: 無效的位置格式 '{pos_str}'")
    sys.exit(1)

def add_subtitle(input_file, subtitle_file, output_file, font, pos, size):
    """將 SRT 字幕檔加到影片中，並輸出到指定的 output_file。"""
    # 檢查字幕檔是否存在
    if not os.path.exists(subtitle_file):
        print(f"錯誤: 找不到字幕檔案 {subtitle_file}")
        sys.exit(1)
    # 取得影片資訊
    _, width, height = get_video_info(input_file)
    if width is None or height is None:
        print(f"錯誤: 無法取得影片解析度 {input_file}")
        sys.exit(1)
    # width/height 已為 int（或 None），此處可直接使用
    # 解析位置
    pos_styles = parse_pos(pos, width, height)
    # 建構 styles
    styles = pos_styles.copy()
    styles["Fontsize"] = str(size)
    styles["Fontname"] = font
    force_style_str = ','.join(f"{k}={v}" for k,v in styles.items())
    cmd = [
        "ffmpeg", "-i", input_file,
        "-vf", f"subtitles={shlex.quote(subtitle_file)}:force_style='{force_style_str}'",
        "-c:a", "copy",
        output_file
    ]
    print(f"添加字幕 {subtitle_file} 到 {input_file} (輸出 {output_file})")
    print(f"執行命令： {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"✅ 完成添加字幕輸出：{output_file}")

def mute_video(input_file, output_file=None):
    if not output_file:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_mute{ext}"

    print(f"靜音處理：{os.path.basename(input_file)} → {os.path.basename(output_file)}")
    cmd = [
        "ffmpeg", "-y",
        "-i", input_file,
        "-c", "copy",       # 影片流直接 copy，不重新編碼
        "-an",              # 移除所有音訊
        output_file
    ]
    subprocess.run(cmd, check=True)
    print(f"✅ 靜音完成：{output_file}")
    return output_file

# camera.py (在同步功能區塊內新增)

def push_files(local_files):
    """將本地檔案推送到 REMOTE_DIR (手機的 /storage/emulated/0/DCIM/Camera)。"""
    check_adb()
    
    print(f"✅ 遠端目錄準備就緒。開始推送 {len(local_files)} 個檔案...")
    success_count = 0
    for file_path in local_files:
        # 只保留檔名部分，直接推送到 REMOTE_DIR 下
        file_name = os.path.basename(file_path)
        remote_path = f"{REMOTE_DIR}/{file_name}"
        
        print(f"正在推送 {file_path} → {remote_path}...")
        try:
            # 使用 adb push
            run_adb_command(["push", file_path, remote_path])
            print(f"成功推送: {file_name}")
            success_count += 1
        except subprocess.CalledProcessError as e:
            print(f"推送失敗 {file_name}: {e.stderr.strip()}")
        except Exception as e:
            print(f"發生未預期錯誤 {file_name}: {e}")
            
    print(f"\n推送完成！成功推送 {success_count}/{len(local_files)} 個檔案到手機。")

# -------------------
# 主程式
# -------------------
def validate_date_format_opt(date_str):
    """驗證日期字串是否為 YYYYmmdd 格式，允許 None (即沒有傳入參數)。"""
    # 允許 None 或是預設常數 LATEST_DATE_CONST 通過驗證
    if date_str is None or date_str == LATEST_DATE_CONST:
        return date_str
        
    if not re.match(r'^\d{8}$', date_str):
        # 這裡需要一個 ArgumentTypeError 來讓 argparse 捕捉錯誤
        raise argparse.ArgumentTypeError(f"日期格式錯誤: '{date_str}'，必須是 YYYYmmdd 格式。")
    try:
        datetime.strptime(date_str, "%Y%m%d")
        return date_str
    except ValueError:
        raise argparse.ArgumentTypeError(f"日期無效: '{date_str}'，請檢查月份和日期是否合法。")

def main():
    examples = f"""
功能分類:

【統計 / 查詢】
  -l [YYYYmmdd]     顯示最新一天或指定日期的影片清單
  -d                顯示所有檔案依日期的數量統計
  -i                顯示影片長度與解析度資訊
     --info-sort    排序方式 (name|duration|resolution)
     --info-sum     顯示總影片長度

【處理】
  -m                合併影片
  -s SECONDS        縮短影片長度至指定秒數
  -S START-END     影片切片 (mm:ss.ms-mm:ss.ms)
  -f "PATTERNS"     指定檔案或萬用字元
  -n OUTPUT.mp4    指定輸出檔名

【影片處理】
  --shrink WxH     縮小解析度 (輸出 input-WxH.mp4)
  --text           添加字幕
     --subtitle    SRT 字幕檔
     --font PATH   字型檔 (預設 NotoSansCJK)
     --pos POS     top-left / bottom-center / center ...
     --size N      字幕大小
  -u, --mute       移除影片音軌

【手機同步】
  -y, --sync       從 Android DCIM/Camera 同步到本機
  -p, --push       將本機檔案推送到手機 Camera

依賴:
  ffmpeg / ffprobe / adb
    """

    parser = argparse.ArgumentParser(
        description="Camera 影片工具：統計、合併、縮短、切片、同步手機檔案 (依賴 ffprobe/ffmpeg/adb)",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=examples,
        add_help=False
    )
   
    # 統計/資訊
    parser.add_argument("-h", "--help", action="help", help=argparse.SUPPRESS)
    parser.add_argument("-l", "--last", nargs='?', const=LATEST_DATE_CONST, type=validate_date_format_opt,
        help=argparse.SUPPRESS)
    parser.add_argument("-d", "--date", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-i", "--info", action="store_true", help=argparse.SUPPRESS)
    # 加上 info sort / sum 選項（若呼叫者需要）
    parser.add_argument("--info-sort", choices=["name","duration","resolution"], default="name", help=argparse.SUPPRESS)
    parser.add_argument("--info-sum", action="store_true", help=argparse.SUPPRESS)
   
    # 處理功能
    parser.add_argument("-f", "--files", help=argparse.SUPPRESS)
    parser.add_argument("-m", "--merge", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-s", "--shorten", type=float, help=argparse.SUPPRESS)
    parser.add_argument("-S", "--slice", help=argparse.SUPPRESS)
    parser.add_argument("-n", "--name", help=argparse.SUPPRESS)
    parser.add_argument("--shrink", type=str, metavar="RESOLUTION", help=argparse.SUPPRESS)
    parser.add_argument("--text", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--subtitle", type=str, help=argparse.SUPPRESS)
    parser.add_argument("--font", type=str, default=DEFAULT_FONT_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--pos", type=str, default="top-left", help=argparse.SUPPRESS)
    parser.add_argument("--size", type=int, default=16, help=argparse.SUPPRESS)
    parser.add_argument("-y", "--sync", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-p", "--push", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument( "-u", "--mute", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()
    # --- 判斷是否有任何參數被使用 ---
    is_any_arg_used = any(arg is not None and arg is not False for arg in vars(args).values() if arg != LATEST_DATE_CONST) or args.last

    if not is_any_arg_used:
        parser.print_help()
        sys.exit(0)
    # --- 1. 同步模式 (--sync) ---
    if args.sync:
        # 檢查其他衝突選項 (排除 args.last 可能是 LATEST_DATE_CONST)
        conflict_args = [args.date, args.info, args.merge, args.files, args.shorten, args.slice, args.shrink, args.name, args.text, args.subtitle]
        if any(conflict_args) or (args.last is not None):
            print("錯誤: --sync 不能與其他處理選項同時使用")
            sys.exit(1)
        sync_files()
        return

    # --- 1.5. 推送模式 (--push) ---
    if args.push:
        conflict_args = [args.sync, args.date, args.info, args.merge, args.shorten, args.slice, args.shrink, args.name, args.text, args.subtitle, args.mute]
        if any(conflict_args) or (args.last is not None):
            print("錯誤: --push 不能與其他模式或處理選項同時使用")
            sys.exit(1)
            
        if not args.files:
            print("錯誤: --push 必須搭配 -f 指定要推送的本地檔案。")
            sys.exit(1)
            
        patterns = args.files.split()
        # require_mp4=False 允許推送任何檔案類型 (mp4, jpg, heic...)
        files_to_push = resolve_files(patterns, require_mp4=False) 
        
        if not files_to_push:
            print(f"錯誤: 沒有找到符合檔案模式 '{args.files}' 的本地檔案")
            sys.exit(1)
        
        push_files(files_to_push)
        return

    # --- 2. 統計模式 (--last, --date, --info) ---
    if args.last is not None or args.date:
        conflict_args = [args.info, args.merge, args.files, args.shorten, args.slice, args.shrink, args.name, args.text, args.subtitle, args.sync, args.mute]

        if any(conflict_args):
            print("錯誤: 統計模式不能與其他處理選項同時使用")
            sys.exit(1)
            
        if args.date:
            if args.last is not None:
                print("錯誤: --date 不能搭配 --last (或指定日期) 使用")
                sys.exit(1)
            show_date(None)
            return
        # --last 模式 (現在處理日期)
        files = find_files(["mp4", "heic", "HEIC", "jpg", "JPG", "jpeg"])
       
        target_date = None
        if args.last != LATEST_DATE_CONST:
            # 如果 args.last 是有效日期字串
            target_date = args.last
           
        show_last(files, target_date=target_date)
        return

    if args.info:
        if not args.files:
            print("錯誤: --info 必須搭配 -f 使用")
            sys.exit(1)

        files = resolve_files(args.files.split(), require_mp4=False)
        if not files:
            print("沒有找到符合的檔案")
            sys.exit(1)

        infos = []
        total_duration = 0.0

        for f in files:
            duration, w, h = get_video_info(f)
            total_duration += duration
            # w, h 已保證為 int 或 None
            infos.append({
                "file": f,
                "duration": duration,
                "width": w,
                "height": h,
                "pixels": (w or 0) * (h or 0)
            })

        # -------- sorting --------
        if args.info_sort == "duration":
            infos.sort(key=lambda x: x["duration"])
        elif args.info_sort == "resolution":
            infos.sort(key=lambda x: x["pixels"])
        else:
            infos.sort(key=lambda x: os.path.basename(x["file"]))

        # -------- output --------
        for i in infos:
            if i["width"] and i["height"]:
                print(f"{i['file']}  {i['duration']:.2f}s  ({i['width']}x{i['height']})")
            else:
                print(f"{i['file']}  {i['duration']:.2f}s")

        if args.info_sum:
            print("-" * 33)
            mins = int(total_duration // 60)
            secs = total_duration % 60
            print(f"總影片數量 : {len(infos)}")
            print(f"總播放時間 : {mins}分{secs:.2f}秒")

        return

    # --- 3. 處理模式 (合併, 縮短, 切片) ---
    if args.merge or args.shorten or args.slice:
        if args.last is not None:
            print("錯誤: --last (或指定日期) 僅能用於統計模式")
            sys.exit(1)
            
        if not args.files:
            print("錯誤: --merge, --shorten, 或 --slice 必須搭配 --files 使用。")
            sys.exit(1)
            
        # 處理 -n 的邏輯
        manual_output_name = args.name
       
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
                if os.path.exists(concat_file): os.remove(concat_file)
                if os.path.exists(temp_merged_file): os.remove(temp_merged_file)
                sys.exit(1)
            finally:
                if os.path.exists(concat_file): os.remove(concat_file)
            # 決定最終輸出檔名
            if manual_output_name:
                output_file = manual_output_name
            else:
                safe_file_tag = re.sub(r'[^\w\-]', '_', os.path.basename(args.files.split()[0].replace('*','').replace('?','')))
                action = "shorten" if args.shorten else "slice"
                output_file = f"{TODAY}-{safe_file_tag}-{action}.mp4"
           
            try:
                if args.shorten:
                    # 在中介檔上先執行縮短，完成後再移動到最終檔名
                    shorten_video(temp_merged_file, args.shorten)
                    shutil.move(temp_merged_file, output_file)
                    print(f"✅ 成功建立檔案: {output_file}")
                elif args.slice:
                    # 切片會產生新檔：slice_video(輸入, 區間, 輸出)
                    slice_video(temp_merged_file, args.slice, output_file)
                    print(f"✅ 成功建立檔案: {output_file}")
                
                # ===== 新增：印出合併的檔案清單 =====
                print("\n🔹 實際合併的檔案清單 (依序):")
                for idx, f in enumerate(files_to_process, 1):
                    print(f"  {idx}. {f}")
                print("-" * 30)
                # ==================================

            except subprocess.CalledProcessError as e:
                print(f"FFmpeg 處理失敗: {e}")
                if os.path.exists(temp_merged_file): os.remove(temp_merged_file)
                sys.exit(1)
            finally:
                # 無論成功或失敗，都嘗試清除中介檔（如果還存在）
                if os.path.exists(temp_merged_file):
                    try:
                        os.remove(temp_merged_file)
                    except:
                        pass
            return
        elif args.merge:
            # 模式 2: 純合併 (-m, -f)
            output_file = manual_output_name if manual_output_name else f"{TODAY}-merge.mp4"
           
            concat_file = build_concat_file(files_to_process)
            print(f"合併影片輸出: {output_file}")
           
            try:
                subprocess.run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", output_file], check=True)
                print(f"✅ 成功建立檔案：{output_file}")
                
                # ===== 新增：印出合併的檔案清單 =====
                print("\n🔹 實際合併的檔案清單 (依序):")
                for idx, f in enumerate(files_to_process, 1):
                    print(f"  {idx}. {f}")
                print("-" * 30)
                # ==================================

            except subprocess.CalledProcessError as e:
                print(f"FFmpeg 合併失敗: {e}")
                sys.exit(1)
            finally:
                if os.path.exists(concat_file):
                    os.remove(concat_file)
            return
        elif args.shorten:
            # 模式 3: 純縮短 (對每個檔案獨立縮短, -s, -f)
           
            # 注意：如果單獨縮短，且使用了 -n，則只能處理一個檔案
            if manual_output_name and len(files_to_process) > 1:
                print("錯誤: 單獨縮短 (-s) 並指定輸出檔名 (-n) 時，一次只能處理一個檔案。")
                sys.exit(1)
                
            print(f"準備對 {len(files_to_process)} 個檔案執行獨立縮短...")
            for input_file in files_to_process:
                # 如果指定了檔名，且只有一個檔案，則將結果移動為指定名稱
                if manual_output_name:
                    # 使用一個臨時檔名，然後移動到指定檔名
                    base, ext = os.path.splitext(input_file)
                    temp_output = f"{base}-temp{ext}"
                    shutil.copy(input_file, temp_output) # 複製一份到臨時檔
                    try:
                        shorten_video(temp_output, args.shorten)
                        shutil.move(temp_output, manual_output_name)
                        print(f"✅ 成功建立檔案: {manual_output_name}")
                    except subprocess.CalledProcessError as e:
                        print(f"縮短失敗 {input_file}: {e}")
                        if os.path.exists(temp_output): os.remove(temp_output)
                else:
                    # 覆蓋原檔案
                    try:
                        shorten_video(input_file, args.shorten)
                        print(f"✅ 成功建立檔案: {input_file} (已覆蓋原檔)")
                    except subprocess.CalledProcessError as e:
                        print(f"縮短失敗 {input_file}: {e}")
            print("所有縮短操作完成。")
            return
        elif args.slice:
            # 模式 4: 純切片 (對每個檔案獨立切片, -S, -f)
           
            # 注意：如果單獨切片，且使用了 -n，則只能處理一個檔案
            if manual_output_name and len(files_to_process) > 1:
                print("錯誤: 單獨切片 (-S) 並指定輸出檔名 (-n) 時，一次只能處理一個檔案。")
                sys.exit(1)
            print(f"準備對 {len(files_to_process)} 個檔案執行獨立切片...")
           
            for input_file in files_to_process:
                if manual_output_name:
                    output_file = manual_output_name
                else:
                    basename = os.path.splitext(os.path.basename(input_file))[0]
                    output_file = f"{basename}-slice.mp4"
               
                try:
                    slice_video(input_file, args.slice, output_file)
                    print(f"✅ 成功建立檔案: {output_file}")
                except subprocess.CalledProcessError as e:
                    print(f"FFmpeg 切片失敗 for {input_file}: {e}")
           
            print("所有切片操作完成。")
            return
    # --- 4. Shrink 模式 ---
    if args.shrink:
        if args.last is not None or args.text or args.subtitle:
            print("錯誤: --shrink 不能搭配 --last (或指定日期) 或 --text 使用")
            sys.exit(1)
            
        if not args.files:
            print("錯誤: --shrink 必須搭配 -f 指定檔案")
            sys.exit(1)
            
        resolution = args.shrink
        patterns = args.files.split()
       
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
    # --- 5. 加字幕 模式 ---
    if args.text:
        if args.last is not None or args.shrink:
            print("錯誤: --text 不能搭配 --last (或指定日期) 或 --shrink 使用")
            sys.exit(1)
            
        if not args.files:
            print("錯誤: --text 必須搭配 -f 指定檔案")
            sys.exit(1)
            
        if not args.subtitle:
            print("錯誤: --text 必須搭配 --subtitle 指定 SRT 檔")
            sys.exit(1)
            
        manual_output_name = args.name
           
        patterns = args.files.split()
        files_to_process = resolve_files(patterns, require_mp4=True)
           
        if not files_to_process:
            print(f"錯誤: 沒有找到符合檔案模式 '{args.files}' 的 .mp4 檔案")
            sys.exit(1)
           
        # 注意：如果使用了 -n，則只能處理一個檔案
        if manual_output_name and len(files_to_process) > 1:
            print("錯誤: 加字幕 (--text) 並指定輸出檔名 (-n) 時，一次只能處理一個檔案。")
            sys.exit(1)
                
        print(f"準備對 {len(files_to_process)} 個檔案添加字幕...")
        for input_file in files_to_process:
            if manual_output_name:
                output_file = manual_output_name
            else:
                basename = os.path.splitext(os.path.basename(input_file))[0]
                output_file = f"{basename}-subtitled.mp4"
               
            try:
                add_subtitle(input_file, args.subtitle, output_file, args.font, args.pos, args.size)
                print(f"✅ 成功建立檔案: {output_file}")
            except subprocess.CalledProcessError as e:
                print(f"添加字幕失敗 for {input_file}: {e}")
           
        print("所有添加字幕操作完成。")
        return

    # --- 移除音軌 (-u / --mute) ---
    if args.mute:
        if args.last is not None or args.shrink or args.text:
            print("錯誤: --mute 不能與 --last、--shrink 或 --text 同時使用")
            sys.exit(1)
         
        if not args.files:
            print("錯誤: --mute 必須搭配 -f 指定要靜音的影片")
            sys.exit(1)
         
        manual_output_name = args.name
        patterns = args.files.split()
        files_to_mute = resolve_files(patterns, require_mp4=False)
         
        if not files_to_mute:
            print("錯誤: 沒有找到要靜音的影片檔案")
            sys.exit(1)
         
        # 使用 -n 指定輸出檔名時只能處理一個檔案（跟其他功能保持一致）
        if manual_output_name and len(files_to_mute) > 1:
            print("錯誤: 使用 -n 指定輸出檔名時，一次只能靜音一個檔案")
            sys.exit(1)
         
        print(f"準備靜音 {len(files_to_mute)} 個影片檔案...")
        for input_file in files_to_mute:
            if manual_output_name:
                output_file = manual_output_name
            else:
                base, ext = os.path.splitext(input_file)
                output_file = f"{base}_mute{ext}"   # 你原本寫 _mute，我保持一致
            mute_video(input_file, output_file)
            print(f"✅ 成功建立檔案: {output_file}")
         
        print("所有影片已靜音完成！")
        return
       
    # --- last. 錯誤處理 ---
    parser.print_help()
    sys.exit(1)

if __name__ == "__main__":
    main()

