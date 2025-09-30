#!/home/wade/venv/bin/python3
import os
import subprocess
import argparse
from datetime import datetime
import ffmpeg

def get_video_duration(video_file):
    """獲取影片檔案的時長（秒）"""
    try:
        probe = ffmpeg.probe(video_file)
        duration = float(probe['format']['duration'])
        return duration
    except ffmpeg.Error as e:
        print(f"Error probing {video_file}: {e.stderr.decode()}")
        return 0

def create_file_list(videos, output_file):
    """創建 ffmpeg 合併所需的檔案清單"""
    with open(output_file, 'w') as f:
        for video in videos:
            f.write(f"file '{video}'\n")

def merge_videos(input_dir, date_prefix, output_file):
    """合併指定日期開頭的影片"""
    # 搜尋符合日期前綴的影片檔案
    videos = [f for f in os.listdir(input_dir) 
             if f.startswith(date_prefix) and f.lower().endswith(('.mp4', '.avi', '.mkv'))]
    
    if not videos:
        print(f"No videos found with prefix {date_prefix} in {input_dir}")
        return False
    
    videos = [os.path.join(input_dir, v) for v in sorted(videos)]
    
    # 創建臨時檔案清單
    file_list = "file_list.txt"
    create_file_list(videos, file_list)
    
    try:
        # 使用 ffmpeg 合併影片
        subprocess.run([
            'ffmpeg', '-f', 'concat', '-safe', '0', 
            '-i', file_list, '-c', 'copy', output_file
        ], check=True)
        print(f"Successfully merged videos to {output_file}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error merging videos: {e}")
        return False
    finally:
        # 清理臨時檔案
        if os.path.exists(file_list):
            os.remove(file_list)

def compress_video_duration(input_file, output_file, target_duration=180):
    """將影片壓縮到指定時長"""
    try:
        # 獲取原始影片時長
        duration = get_video_duration(input_file)
        
        if duration <= target_duration:
            print(f"Video duration ({duration}s) is already under {target_duration}s")
            return input_file
        
        # 計算加速倍數
        speed = duration / target_duration
        
        # 使用 ffmpeg 壓縮時間
        subprocess.run([
            'ffmpeg', '-i', input_file, 
            '-filter:v', f'setpts={1/speed}*PTS',
            '-filter:a', f'atempo={speed}',
            '-c:v', 'libx264', '-c:a', 'aac', 
            output_file
        ], check=True)
        print(f"Successfully compressed video to {output_file} ({target_duration}s)")
        return output_file
    except subprocess.CalledProcessError as e:
        print(f"Error compressing video: {e}")
        return input_file

def main():
    parser = argparse.ArgumentParser(description="Merge videos with specific date prefix and compress if necessary")
    parser.add_argument('input_dir', help="Input directory containing video files")
    parser.add_argument('date_prefix', help="Date prefix for video files (e.g., 20230930)")
    parser.add_argument('output_file', help="Output file name for merged video")
    
    args = parser.parse_args()
    
    # 確保輸入目錄存在
    if not os.path.isdir(args.input_dir):
        print(f"Input directory {args.input_dir} does not exist")
        return
    
    # 合併影片
    temp_output = "temp_merged_video.mp4"
    if merge_videos(args.input_dir, args.date_prefix, temp_output):
        # 檢查並壓縮影片時長
        final_output = compress_video_duration(temp_output, args.output_file)
        
        # 清理臨時檔案
        if final_output != temp_output and os.path.exists(temp_output):
            os.remove(temp_output)

if __name__ == "__main__":
    main()
