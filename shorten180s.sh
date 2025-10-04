#!/bin/bash
# merge_shorten180s.sh
set -e

prefix="$1"
target_duration=180
merged="${prefix}_merged.mp4"
output="${prefix}s.mp4"

if [ -z "$prefix" ]; then
    echo "用法: $0 prefix"
    exit 1
fi

# 找出檔案
files=( Camera/${prefix}*.mp4 )
if [ ${#files[@]} -eq 0 ]; then
    echo "找不到檔案 Camera/${prefix}*.mp4"
    exit 1
fi

# 先建立 ffmpeg concat 用的清單
listfile="$(mktemp)"
for f in "${files[@]}"; do
    echo "file '$PWD/$f'" >> "$listfile"
done

# 計算總長度
total_duration=0
for f in "${files[@]}"; do
    dur=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$f")
    dur=$(printf "%.2f" "$dur")
    total_duration=$(echo "$total_duration + $dur" | bc)
done

echo "影片總長度：$total_duration 秒"

# 先合併
ffmpeg -f concat -safe 0 -i "$listfile" -c copy "$merged"

if (( $(echo "$total_duration <= $target_duration" | bc -l) )); then
    echo "總長度 <= 180 秒，直接輸出"
    mv "$merged" "$output"
else
    echo "總長度 > 180 秒，需要縮短至 180 秒"

    # 計算倍率
    v_speed=$(echo "scale=5; $target_duration / $total_duration" | bc)
    a_speed=$(echo "scale=5; $total_duration / $target_duration" | bc)

    has_audio=$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$merged")
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

    if [ -n "$has_audio" ]; then
        ffmpeg -i "$merged" -filter_complex \
        "[0:v]setpts=${v_speed}*PTS[v];[0:a]$atempo_filters[a]" \
        -map "[v]" -map "[a]" "$output"
    else
        ffmpeg -i "$merged" -filter_complex \
        "[0:v]setpts=${v_speed}*PTS[v]" \
        -map "[v]" -an "$output"
    fi
    rm -f "$merged"
fi

rm -f "$listfile"
echo "完成，輸出檔案：$output"

