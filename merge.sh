#!/bin/bash
# merge.sh
# 用法: ./merge.sh <prefix>
# 會合併 Camera 目錄下所有符合 prefix*.mp4 的影片，輸出為 prefix_merged.mp4
# 預設使用 ffmpeg concat 模式，不重新編碼。

show_help() {
    cat <<EOF
用法: $0 [選項] <prefix>

選項:
  -h, --help           顯示本說明
  -l, --last           顯示 Camera/ 目錄下最新日期的檔案
  -d, --date           顯示所有日期與各自的檔案數量
  -t, --type <m|p>     指定檔案類型 (m=影片 mp4, p=照片 heic/jpg)

說明:
  當使用 -l 或 -d 時，必須搭配 -t 指定要統計的類型。
  不加 -l/-d 時，則會使用 prefix 合併 mp4。

範例:
  $0 20250816
    -> 合併 Camera/20250816*.mp4 成 20250816_merged.mp4

  $0 -l -t m
    -> 顯示最新日期的 mp4 檔案清單與數量

  $0 -d -t p
    -> 顯示所有日期的照片數量 (.heic + .jpg)
EOF
}

# 預設
mode=""
type=""

# 參數解析
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -l|--last)
            mode="last"
            shift
            ;;
        -d|--date)
            mode="date"
            shift
            ;;
        -t|--type)
            type="$2"
            shift 2
            ;;
        *)
            # 其餘為 prefix
            prefix="$1"
            shift
            ;;
    esac
done

# 檢查 Camera 目錄
if [[ ! -d "Camera" ]]; then
    echo "錯誤: 找不到 Camera 目錄"
    exit 1
fi

# 判斷 type 的副檔名
if [[ "$type" == "m" ]]; then
    exts=("mp4")
elif [[ "$type" == "p" ]]; then
    exts=("heic" "jpg" "JPG" "jpeg" "JPEG" "HEIC")
fi

# helper: 取符合的檔案清單
get_files() {
    local prefix="$1"
    local patterns=()
    for ext in "${exts[@]}"; do
        patterns+=("Camera/${prefix}*.${ext}")
    done
    echo "${patterns[@]}"
}

# --- mode = last/date 統計 ---
if [[ "$mode" == "last" || "$mode" == "date" ]]; then
    if [[ -z "$type" ]]; then
        echo "錯誤: -l/-d 需要搭配 -t m|p"
        exit 1
    fi

    # 收集所有符合的檔案
    shopt -s nullglob
    all_files=()
    for ext in "${exts[@]}"; do
        all_files+=("Camera/"*."$ext")
    done
    shopt -u nullglob

    if [[ ${#all_files[@]} -eq 0 ]]; then
        echo "沒有找到符合的檔案"
        exit 1
    fi

    # 提取日期 (檔名前 8 碼)
    dates=$(printf "%s\n" "${all_files[@]}" | sed -E 's#.*/([0-9]{8}).*#\1#' | sort -u)

    if [[ "$mode" == "last" ]]; then
        last_date=$(echo "$dates" | tail -n 1)
        echo "最新日期: $last_date"
        count=0
        for f in "${all_files[@]}"; do
            if [[ "$f" =~ ${last_date} ]]; then
                echo "$f"
                ((count++))
            fi
        done
        echo "總數: $count"
        exit 0
    elif [[ "$mode" == "date" ]]; then
        for d in $dates; do
            count=$(printf "%s\n" "${all_files[@]}" | grep "$d" | wc -l)
            echo "$d = $count"
        done
        exit 0
    fi
fi

# --- 合併影片 ---
if [[ -z "$prefix" ]]; then
    echo "錯誤: 缺少 prefix 參數"
    echo "使用 '$0 --help' 查看說明"
    exit 1
fi

# 只允許 mp4 合併
exts=("mp4")

# 清掉舊的清單
rm -f file_list.txt

# 收集符合 prefix 的 mp4
shopt -s nullglob
files=(Camera/${prefix}*.mp4)
if [[ ${#files[@]} -eq 0 ]]; then
    echo "錯誤: 沒有找到符合的檔案: Camera/${prefix}*.mp4"
    exit 1
fi

for f in "${files[@]}"; do
    echo "file '$PWD/$f'" >> file_list.txt
done

# 使用 concat 模式合併（不重新編碼）
output="${prefix}_merged.mp4"
echo "合併影片輸出: $output"
ffmpeg -f concat -safe 0 -i file_list.txt -c copy "$output"

