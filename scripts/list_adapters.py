import os, glob
for f in sorted(glob.glob('app/capture/adapters/*.py')):
    print(f)