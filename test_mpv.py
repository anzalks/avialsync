import sys, os
os.environ["DYLD_LIBRARY_PATH"] = "/opt/homebrew/lib"
import mpv
m = mpv.MPV(vo="libmpv")
print("mpv VO ok")
