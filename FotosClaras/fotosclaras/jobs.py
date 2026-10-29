"""Spawned, low-priority analysis process; Qt only polls small status messages."""
from __future__ import annotations
import multiprocessing as mp
import os
import time
import traceback
from PySide6.QtCore import QObject,QTimer,Signal


def analysis_worker(connection,cancel,kind,path,library):
    # This target must stay importable for Windows spawn and PyInstaller.
    try:
        if os.name=='nt':
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),0x4000)
        else:os.nice(5)
        from .db import Catalog
        from . import identity,indexer
        last=0;previous=''
        def report(stage,done,total):
            nonlocal last,previous
            now=time.monotonic()
            if stage!=previous or now-last>.15 or done==total:
                connection.send(('progress',(stage,done,total)));last=now;previous=stage
        if kind=='index':result=indexer.scan(path,library,cancel,report)
        elif kind=='faces':result=identity.analyze(path,library,cancel,report)
        elif kind=='regroup':
            with Catalog(path) as c:
                job=c.start_job(library,'associations');position=[0,0];checkpoint=[0.]
                def grouped(stage,done,total):
                    position[:]=[done,total];now=time.monotonic()
                    if now-checkpoint[0]>.5 or done==total:
                        c.progress(job,stage,done,total);checkpoint[0]=now
                    report(stage,done,total)
                result=identity.regroup(c,library,cancel,grouped)
                c.progress(job,'Pausado' if cancel.is_set() else 'Finalizado',*position,
                           state='paused' if cancel.is_set() else 'done')
        else:raise ValueError('Trabajo desconocido: '+kind)
        connection.send(('finished',result))
    except BaseException as exc:
        try:
            from .db import Catalog
            with Catalog(path) as c:
                c.log('worker_error',traceback.format_exc())
                with c.db:c.db.execute("UPDATE jobs SET state='error',message=? WHERE library_id=? AND state='running'",(str(exc),library))
        except Exception:pass
        try:connection.send(('failed',str(exc) or 'El proceso se interrumpió. Podés reanudar el análisis.'))
        except (OSError,EOFError):pass
    finally:connection.close()


class ProcessSignals(QObject):
    progress=Signal(str,int,int)
    finished=Signal(object)
    failed=Signal(str)


class ProcessTask(QObject):
    def __init__(self,kind,path,library,parent=None):
        super().__init__(parent);context=mp.get_context('spawn')
        self.signals=ProcessSignals(self);self.cancel=context.Event()
        self.reader,writer=context.Pipe(duplex=False)
        self.process=context.Process(target=analysis_worker,args=(writer,self.cancel,kind,str(path),library),daemon=True)
        self.writer=writer;self.done=False;self.cancelled_at=None
        self.timer=QTimer(self);self.timer.setInterval(40);self.timer.timeout.connect(self.poll)
    def start(self):
        keys=('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')
        previous={k:os.environ.get(k) for k in keys}
        try:
            for key in keys:os.environ[key]='1'
            self.process.start()
        finally:
            for key,value in previous.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value
        self.writer.close();self.timer.start()
    def poll(self):
        try:
            for _ in range(64):
                if not self.reader.poll():break
                event,data=self.reader.recv()
                if event=='progress':self.signals.progress.emit(*data)
                elif event=='finished':self.done=True;self.signals.finished.emit(data)
                else:self.done=True;self.signals.failed.emit(data)
        except (EOFError,OSError):pass
        if self.cancel.is_set() and self.cancelled_at is None:self.cancelled_at=time.monotonic()
        # Only index/face tasks are isolated here; file movements never use
        # forced termination. SQLite rolls back an interrupted transaction.
        if self.cancelled_at and not self.done and time.monotonic()-self.cancelled_at>12 and self.process.is_alive():
            self.process.terminate()
        if not self.process.is_alive():
            self.process.join(timeout=0);self.timer.stop();self.reader.close()
            if not self.done:
                self.done=True
                if self.cancel.is_set():self.signals.finished.emit(dict(state='paused',errors=0))
                else:self.signals.failed.emit('El proceso de análisis se interrumpió. Los archivos completados siguen guardados; podés reanudar.')
            self.process.close();self.deleteLater()
