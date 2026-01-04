# usage: camera.py
```text
Camera 影片工具：統計、合併、縮短、切片、同步手機檔案 (依賴 ffprobe/ffmpeg/adb)

範例用法:
  # 1. (統計) 顯示最新一天的影片清單
  ./camera.py -l
  # 2. (統計) 顯示指定日期 (20251109) 的影片清單
  ./camera.py -l 20251109
  # 3. (統計) 顯示所有檔案按日期的數量統計
  ./camera.py -d
  # 4. (資訊) 顯示指定檔案的長度與總長度
  ./camera.py -i "video1.mp4 video2.mp4"
  # 5. (合併) 合併檔案並指定輸出檔名
  ./camera.py -m -f "VID_20240201*" -n my_merged_video.mp4
  # 6. (切片) 切片並指定輸出檔名 (單檔)
  ./camera.py -S 5-15.5 -f video.mp4 -n sliced_clip.mp4
  # 7. (縮短) 縮短檔案長度
  ./camera.py -s 179 -f "20251110*" -n "20251110-割草2.mp4"
  # 8. (合併+縮短) 合併後縮短
  ./camera.py -m -s 45 -f "VID_20240201*"
  # 9. (同步) 從手機 DCIM/Camera 同步新檔案到本地目錄
  ./camera.py -y
  # 10. (縮小) 縮小影片解析度
  ./camera.py --shrink 1024x768 -f "input.mp4 another.mp4"
  # 11. (加字幕) 添加字幕到影片
  ./camera.py --text -f "input.mp4" --subtitle subtitles.srt -n output_with_sub.mp4 --pos bottom-center --size 20 --font /path/to/font.ttc
  # 12. (靜音) 將影片去除音軌
  ./camera.py --mute -f "input.mp4"
```
