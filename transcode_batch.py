import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error

FFMPEG = r"C:\Users\guido\AppData\Local\CapCut\Apps\9.5.0.4050\ffmpeg.exe"
DATA_API = "https://topshelfmi.vercel.app/api/data"
UPLOAD_API = "https://topshelfmi.vercel.app/api/upload"

def get_client_token(pathname, content_type):
    payload = {
        "type": "blob.generate-client-token",
        "payload": {
            "pathname": pathname,
            "callbackUrl": UPLOAD_API,
            "clientToken": "batch_transcode"
        }
    }
    req = urllib.request.Request(
        UPLOAD_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["clientToken"]

def upload_file_to_blob(file_path, pathname, content_type):
    token = get_client_token(pathname, content_type)
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    put_url = f"https://blob.vercel-storage.com/?pathname={urllib.parse.quote(pathname)}"
    req = urllib.request.Request(
        put_url,
        data=file_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "x-api-version": "9"
        },
        method="PUT"
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res["url"]

def download_file(url, dest_path):
    print(f"Downloading {url} ...")
    urllib.request.urlretrieve(url, dest_path)
    size_mb = os.path.getsize(dest_path) / (1024 * 1024)
    print(f"Downloaded {size_mb:.2f} MB")

def transcode_video(input_mov, output_mp4, output_jpg):
    print("Transcoding with NVENC...")
    # 1. Video compression: 720p height, 1200k bitrate, faststart, 30fps max
    cmd_vid = [
        FFMPEG, "-y",
        "-i", input_mov,
        "-vcodec", "h264_nvenc",
        "-b:v", "1200k",
        "-maxrate", "1600k",
        "-bufsize", "2400k",
        "-vf", "scale=-2:720",
        "-r", "30",
        "-movflags", "+faststart",
        "-an",
        output_mp4
    ]
    res = subprocess.run(cmd_vid, capture_output=True, text=True)
    if res.returncode != 0:
        print("NVENC failed, trying h264_mf fallback...")
        cmd_vid[4] = "h264_mf"
        subprocess.run(cmd_vid, check=True)

    # 2. Extract crystal-clear JPEG poster frame at 0.5s
    cmd_jpg = [
        FFMPEG, "-y",
        "-ss", "00:00:00.500",
        "-i", output_mp4,
        "-vframes", "1",
        "-q:v", "2",
        output_jpg
    ]
    subprocess.run(cmd_jpg, check=True)

    orig_mb = os.path.getsize(input_mov) / (1024 * 1024)
    new_mb = os.path.getsize(output_mp4) / (1024 * 1024)
    jpg_kb = os.path.getsize(output_jpg) / 1024
    print(f"Original: {orig_mb:.1f} MB -> Compressed MP4: {new_mb:.2f} MB ({new_mb/orig_mb*100:.1f}%) | Poster: {jpg_kb:.1f} KB")

def main():
    test_mode = "--one" in sys.argv
    print(f"Starting batch transcode. Test mode (only 1): {test_mode}")

    # Fetch current data
    req = urllib.request.Request(DATA_API, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req) as resp:
        catalog = json.loads(resp.read().decode("utf-8"))

    products = catalog.get("products", [])
    updated = False

    for idx, p in enumerate(products):
        video_url = p.get("video", "")
        if not video_url.endswith(".mov") or "blob.vercel-storage.com" not in video_url:
            print(f"Skipping [{idx+1}/{len(products)}] {p.get('strain')}: already mp4 or local")
            continue

        print(f"\nProcessing [{idx+1}/{len(products)}] {p.get('strain')} ...")
        tmp_in = "tmp_raw.mov"
        tmp_out = f"opt_{p.get('id')}.mp4"
        tmp_jpg = f"poster_{p.get('id')}.jpg"

        try:
            download_file(video_url, tmp_in)
            transcode_video(tmp_in, tmp_out, tmp_jpg)

            print("Uploading optimized MP4 to Vercel Blob...")
            blob_video_url = upload_file_to_blob(tmp_out, tmp_out, "video/mp4")
            print(f"Uploaded video: {blob_video_url}")

            print("Uploading poster image to Vercel Blob...")
            blob_poster_url = upload_file_to_blob(tmp_jpg, tmp_jpg, "image/jpeg")
            print(f"Uploaded poster: {blob_poster_url}")

            p["video"] = blob_video_url
            p["poster"] = blob_poster_url
            updated = True

            # Save progress immediately after each product!
            save_req = urllib.request.Request(
                DATA_API,
                data=json.dumps(catalog).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(save_req) as s_resp:
                print(f"Progress saved to Vercel catalog! ({p.get('strain')})")

        finally:
            for f in [tmp_in, tmp_out, tmp_jpg]:
                if os.path.exists(f):
                    os.remove(f)

        if test_mode:
            print("Finished single item test!")
            break

    if updated:
        with open("data.json", "w", encoding="utf-8") as f:
            json.dump(catalog, f, indent=2, ensure_ascii=False)
        print("All done and synced with local data.json!")

if __name__ == "__main__":
    main()
