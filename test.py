import os, time
print("start")
time.sleep(0.5)
print("before os._exit")
os._exit(0)
print("after os._exit")   # 永远不应该到这