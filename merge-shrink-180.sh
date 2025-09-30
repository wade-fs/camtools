#!/bin/bash
#
# 利用 ffmpeg 合併指定資料夾內、日期開頭的影片，
# 若合併後長度超過 180 秒，自動加速壓縮至 180 秒
#
# 用法:
#   merge_and_shorten.sh -s SOURCE_FOLDER -d DATE -o OUTPUT_FILE
#
# 範例:
#   ./merge_and_shorten.sh -s ./videos -d 20250930 -o final.mp4

set -e

#==== 預設值 ====
SOURCE_FOLDER="."
DATE_PREFIX=""
OUTPUT_FILE=""

#==== 參數解析 ====
while getopts "s:d:o:" opt; do
    case "$opt" in
        s) SOURCE_FOLDER="$OPTARG" ;;
        d) DATE_PREFIX="$OPTARG" ;;
        o) OUTPUT_FILE="$OPTARG" ;;
        *) echo "用法: $0 -s SOURCE_FOLDER -d DATE -o OUTPUT_FILE"; exit 1 ;;
    esac
done

if [ -z "$DATE_PREFIX" ]; then
    echo "❌ 請使用 -d 指定日期前綴，例如: 20250930"
    exit 1
fi

if [ -z "$OUTPUT_FILE" ]; then
    OUTPUT_FILE="merged_${DATE_PREFIX}.mp4"
fi

if [ ! -d "$SOURCE_FOLDER" ]; then
    echo "❌ 資料夾不存在: $SOURCE_FOLDER"
    exit 1
fi

cd "$SOURCE_FOLDER"

#==== 找出符合日期前綴的檔案 ====
FILES=( ${DATE_PREFIX}*.mp4 )
if [ ${#FILES[@]} -eq 0 ]; then
    echo "❌ 找不到符合 ${DATE_PREFIX} 開頭的 mp4 檔案於 $SOURCE_FOLDER"
    exit 1
fi

#==== 建立 ffmpeg 合併清單 ====
LIST_FILE="merge_list_${DATE_PREFIX}.txt"
rm -f "$LIST_FILE"
for f in "${FILES[@]}"; do
    echo "file '$PWD/$f'" >> "$LIST_FILE"
done

#==== 合併影片 ====
MERGED_FILE="merged_temp_${DATE_PREFIX}.mp4"
echo "🔗 合併影片中..."
ffmpeg -y -f concat -safe 0 -i "$LIST_FILE" -c copy "$MERGED_FILE"

#==== 取得合併後影片長度 ====
DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$MERGED_FILE")
DURATION=${DURATION%.*}

#==== 判斷是否需要壓縮 ====
if [ "$DURATION" -gt 180 ]; then
    echo "⚡ 合併後長度 ${DURATION}s > 180s，開始壓縮..."
    # 計算加速倍數 (原長度 / 180)
    SPEED=$(awk -v dur="$DURATION" 'BEGIN {print dur/180}')
    # atempo 允許範圍 0.5~2.0，若倍數過大需鏈接多次
    # 這裡簡單處理一般情況
    ffmpeg -y -i "$MERGED_FILE" \
        -filter_complex "[0:v]setpts=PTS/${SPEED}[v];[0:a]atempo=${SPEED}[a]" \
        -map "[v]" -map "[a]" -movflags +faststart "$OUTPUT_FILE"
else
    echo "✅ 長度 ${DURATION}s <= 180s，直接輸出"
    mv "$MERGED_FILE" "$OUTPUT_FILE"
fi

#==== 清理暫存檔 ====
rm -f "$MERGED_FILE" "$LIST_FILE"

echo "🎉 完成：輸出檔案 -> $SOURCE_FOLDER/$OUTPUT_FILE"

