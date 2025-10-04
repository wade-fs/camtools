#!/bin/bash
# merge.sh
# 用法: ./merge.sh <prefix>
# 會合併 Camera 目錄下所有符合 prefix*.mp4 的影片，輸出為 prefix_merged.mp4
# 預設使用 ffmpeg concat 模式，不重新編碼。

show_help() {
    cat <<EOF
用法: $0 <prefix>

選項:
  -h, --help    顯示本說明

說明:
  這個腳本會尋找 Camera/<prefix>*.mp4 的檔案，
  依檔名排序後合併成一個影片 <prefix>_merged.mp4。
  使用 ffmpeg concat 模式，影片不會重新編碼。

範例:
  $0 20250816
  -> 會合併 Camera/20250816*.mp4 成 20250816_merged.mp4
EOF
}

# 若參數為 -h 或 --help
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# 檢查是否有傳入 prefix
if [[ -z "$1" ]]; then
    echo "錯誤: 缺少 prefix 參數"
    echo "使用 '$0 --help' 查看說明"
    exit 1
fi

prefix="$1"

# 檢查 Camera 目錄是否存在
if [[ ! -d "Camera" ]]; then
    echo "錯誤: 找不到 Camera 目錄"
    exit 1
fi

# 清掉舊的清單
rm -f file_list.txt

# 依檔名排序，把符合的 mp4 加進清單
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

