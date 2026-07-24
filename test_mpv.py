import mpv
import time
player = mpv.MPV()
player.play('tests/fixtures/sync_mock/camera_1.mp4')
time.sleep(1)
print("Estimated frame:", player.estimated_frame_number)
