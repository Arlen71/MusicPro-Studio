"""One isolated renderer per output; file-based progress and cooperative cancellation."""
import json,sys,time,os
from pathlib import Path
from engine import render,Cancelled
from failures import error_record

def publish_progress(path,value):
    # UI telemetry is best effort. Windows readers may hold the destination open
    # briefly and reject os.replace; a missed update must never abort the render.
    temp=path.with_suffix('.tmp')
    try:
        temp.write_text(str(value),encoding='ascii')
        os.replace(temp,path)
    except OSError:
        pass
class FileStop:
    def __init__(self,path):self.path=Path(path)
    def is_set(self):return self.path.exists()
    def wait(self,seconds):
        time.sleep(seconds)
        return self.is_set()
def main():
    request=Path(sys.argv[1]);d=json.loads(request.read_text(encoding='utf-8'))
    def progress(value):
        publish_progress(request.with_suffix('.progress'),value)
    try:render(d['plan'],d['config'],d['dest'],d['encoder'],FileStop(request.with_suffix('.stop')),progress)
    except Cancelled:return 42
    except Exception as e:
        try:
            result=request.with_suffix('.result');temp=result.with_suffix('.tmp')
            temp.write_text(json.dumps(error_record(e),ensure_ascii=False),encoding='utf-8');os.replace(temp,result)
        except OSError: pass
        print(str(e),file=sys.stderr);return 1
    return 0
if __name__=='__main__':sys.exit(main())
