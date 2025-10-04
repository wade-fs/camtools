#!/bin/bash

# 使用方式：./shorts.sh input.mp4

if [ $# -ne 1 ]; then
    echo "用法: $0 <影片檔名>"
    exit 1
fi

input="$1"
target_duration=179
output="${input%.*}-s.mp4"

if [ ! -f "$input" ]; then
    echo "錯誤：找不到檔案 $input"
    exit 1
fi

# 取得影片長度（秒）
duration=$(ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 "$input")

duration=$(printf "%.2f" "$duration")
echo "duration = $duration"

# 計算視訊與音訊倍率
v_speed=$(echo "scale=5; $target_duration / $duration" | bc)
a_speed=$(echo "scale=5; $duration / $target_duration" | bc)

# 檢查是否有音訊軌道
has_audio=$(ffprobe -v error -select_streams a -show_entries stream=index \
  -of csv=p=0 "$input")

# 建立 atempo 濾鏡（必要時分段）
atempo_filters=""
a_speed_f=$a_speed
if (( $(echo "$a_speed_f < 0.5" | bc -l) )); then
    while (( $(echo "$a_speed_f > 2.0" | bc -l) )); do
        atempo_filters="${atempo_filters}atempo=2.0,"
        a_speed_f=$(echo "scale=5; $a_speed_f / 2.0" | bc)
    done
    atempo_filters="${atempo_filters}atempo=$a_speed_f"
else
    atempo_filters="atempo=$a_speed_f"
fi

echo "原始長度：$duration 秒"
echo "轉換為：$target_duration 秒"
echo "視訊速度倍率：$v_speed"
if [ -n "$has_audio" ]; then
    echo "音訊 atempo：$atempo_filters"
    ffmpeg -i "$input" -filter_complex \
    "[0:v]setpts=${v_speed}*PTS[v];[0:a]$atempo_filters[a]" \
    -map "[v]" -map "[a]" "$output"
else
    echo "此影片無音訊，僅調整視訊速度"
    ffmpeg -i "$input" -filter_complex \
    "[0:v]setpts=${v_speed}*PTS[v]" \
    -map "[v]" -an "$output"
fi

