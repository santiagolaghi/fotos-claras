"""Qt model/view gallery with bounded asynchronous image decoding."""
from __future__ import annotations
import io
import time
import traceback
from collections import OrderedDict
from pathlib import Path
from PySide6.QtCore import Qt,QObject,Signal,QRunnable,QThreadPool,QAbstractListModel,QAbstractTableModel,QModelIndex,QSize,QRectF,QTimer,QItemSelectionModel
from PySide6.QtGui import QImage,QPixmap,QPainter,QColor,QFont,QPainterPath,QPen,QIcon
from PySide6.QtWidgets import (QListView,QStyledItemDelegate,QAbstractItemView,QDialog,QVBoxLayout,
    QHBoxLayout,QPushButton,QLabel,QGraphicsView,QGraphicsScene,QFrame)
from .imaging import open_rgb


def decode_image(path,side):
    image=open_rgb(path,side)
    # QImage is safe in workers; QPixmap and disk decoding stay off the UI.
    return QImage(image.tobytes(),image.width,image.height,image.width*3,QImage.Format_RGB888).copy()


class Signals(QObject):
    progress=Signal(str,int,int)
    finished=Signal(object)
    failed=Signal(str)


class Task(QRunnable):
    def __init__(self,fn):
        super().__init__();self.fn=fn;self.signals=Signals();self.last=0;self.stage=''
    def report(self,stage,done,total):
        now=time.monotonic()
        if stage!=self.stage or now-self.last>.08 or done==total:
            self.last=now;self.stage=stage;self.signals.progress.emit(stage,done,total)
    def run(self):
        try: self.signals.finished.emit(self.fn(self.report))
        except Exception as e:
            import logging
            logging.getLogger('fotosclaras').error(traceback.format_exc())
            self.signals.failed.emit(str(e))


class Thumbnails(QObject):
    ready=Signal(str,object)
    def __init__(self,parent=None):
        super().__init__(parent);self.pool=QThreadPool(self);self.pool.setMaxThreadCount(2)
        self.cache=OrderedDict();self.pending=set();self.ready.connect(self._ready)
        self.tasks={};self.bytes=0;self.budget=48*1024*1024;self.stopping=False
    def request(self,path):
        if not path: return None
        if path in self.cache:
            self.cache.move_to_end(path);return self.cache[path]
        if self.stopping:return None
        # Limit queued work while rapidly scrolling through thousands of images.
        if path not in self.pending and len(self.pending)<36:
            self.pending.add(path)
            def read(_):
                try:
                    return decode_image(path,400)
                except Exception:return QImage()
            task=Task(read);self.tasks[path]=task
            task.signals.finished.connect(lambda result,p=path:self.ready.emit(p,result))
            self.pool.start(task)
        return None
    def _ready(self,path,data):
        self.pending.discard(path);self.tasks.pop(path,None)
        image=data if isinstance(data,QImage) else QImage()
        prior=self.cache.pop(path,None)
        if prior is not None:self.bytes-=prior.sizeInBytes()
        self.cache[path]=image;self.bytes+=image.sizeInBytes()
        while self.bytes>self.budget or len(self.cache)>160:
            _,old=self.cache.popitem(last=False);self.bytes-=old.sizeInBytes()
    def shutdown(self): self.pool.waitForDone()


class PhotoModel(QAbstractListModel):
    def __init__(self,thumbs,people=False,parent=None):
        super().__init__(parent);self.records=[];self.thumbs=thumbs;self.people=people;self.by_path={}
        thumbs.ready.connect(self.changed)
    def rowCount(self,parent=QModelIndex()): return 0 if parent.isValid() else len(self.records)
    def set_records(self,records):
        self.beginResetModel();self.records=records;self.by_path={}
        for i,r in enumerate(records):self.by_path.setdefault(r.get('thumb') or r.get('path'),[]).append(i)
        self.endResetModel()
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or index.row()>=len(self.records): return None
        r=self.records[index.row()]
        if role==Qt.UserRole: return r
        if role==Qt.DisplayRole: return (r.get('name') or '¿Quién es esta persona?') if self.people else (r.get('name') or Path(r.get('path','')).name)
        if role==Qt.ToolTipRole: return r.get('path') or r.get('name') or 'Sin identificar'
        if role==Qt.AccessibleTextRole: return self.data(index,Qt.DisplayRole)
        if role==Qt.DecorationRole: return self.thumbs.request(r.get('thumb') or r.get('path'))
    def changed(self,path,_):
        for i in self.by_path.get(path,[]):
            index=self.index(i);self.dataChanged.emit(index,index,[Qt.DecorationRole])


class FilePlanModel(QAbstractTableModel):
    """Virtual preview; do not construct 40,000 QStandardItems on the UI thread."""
    def __init__(self,items,parent=None):super().__init__(parent);self.items=items
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.items)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else 2
    def data(self,index,role=Qt.DisplayRole):
        if index.isValid() and role in (Qt.DisplayRole,Qt.ToolTipRole):return self.items[index.row()][('source','target')[index.column()]]
    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if role==Qt.DisplayRole:
            return ('Ubicación actual','Ubicación después de confirmar')[section] if orientation==Qt.Horizontal else section+1


class TileDelegate(QStyledItemDelegate):
    def __init__(self,people=False,parent=None): super().__init__(parent);self.people=people
    def sizeHint(self,*args): return QSize(202,224 if self.people else 186)
    def paint(self,painter,option,index):
        from PySide6.QtWidgets import QStyle
        p=painter;p.save();r=QRectF(option.rect).adjusted(5,5,-5,-5)
        selected=bool(option.state & QStyle.State_Selected)
        p.setRenderHint(QPainter.Antialiasing);p.setPen(Qt.NoPen)
        p.setBrush(QColor('#e5e8d9' if selected else '#fffdf9'));p.drawRoundedRect(r,10,10)
        image=index.data(Qt.DecorationRole)
        photo=QRectF(r.x()+5,r.y()+5,r.width()-10,r.height()-50)
        if self.people:
            size=min(photo.width(),photo.height())-12
            photo=QRectF(r.center().x()-size/2,r.y()+8,size,size)
        clip=QPainterPath()
        if self.people: clip.addEllipse(photo)
        else: clip.addRoundedRect(photo,6,6)
        p.setClipPath(clip);p.fillRect(photo,QColor('#eae6df'))
        if image is not None and not image.isNull():
            scaled=image.scaled(photo.size().toSize(),Qt.KeepAspectRatioByExpanding if self.people else Qt.KeepAspectRatio,Qt.SmoothTransformation)
            if self.people:
                p.drawImage(photo,scaled,QRectF((scaled.width()-photo.width())/2,(scaled.height()-photo.height())/2,photo.width(),photo.height()))
            else:
                p.drawImage(QRectF(photo.center().x()-scaled.width()/2,photo.center().y()-scaled.height()/2,scaled.width(),scaled.height()),scaled)
        else:
            p.setPen(QColor('#899079'));p.drawText(photo,Qt.AlignCenter,'Vista previa')
        p.setClipping(False);p.setPen(QColor('#262a23'));p.setFont(QFont('Segoe UI',10))
        text=index.data(Qt.DisplayRole)
        text=option.fontMetrics.elidedText(text,Qt.ElideRight,int(r.width()-18))
        p.drawText(QRectF(r.x()+9,r.bottom()-41,r.width()-18,20),Qt.AlignCenter if self.people else Qt.AlignLeft,text)
        data=index.data(Qt.UserRole);p.setPen(QColor('#77786e'));p.setFont(QFont('Segoe UI',9))
        subtitle=(str(data.get('photos',0))+' fotografías') if self.people else f"{data.get('width') or '—'} × {data.get('height') or '—'}"
        if data.get('ordinal') is not None:
            state={'confirmed':'Confirmado','automatic':'Coincidencia automática','unknown':'Por identificar'}.get(data.get('match_state'),'')
            subtitle=state or 'Rostro '+str(data['ordinal']+1)
            if data.get('quality',1)<.35:subtitle+=' · baja calidad'
        p.drawText(QRectF(r.x()+9,r.bottom()-22,r.width()-18,17),Qt.AlignCenter if self.people else Qt.AlignLeft,subtitle)
        circle=QRectF(r.right()-28,r.top()+12,18,18)
        p.setPen(QPen(QColor('#fffdf9'),1.5));p.setBrush((QColor('#657047') if selected else QColor(255,255,255,120)));p.drawEllipse(circle)
        if selected: p.setPen(Qt.white);p.drawText(circle,Qt.AlignCenter,'✓')
        if selected: p.setBrush(Qt.NoBrush);p.setPen(QPen(QColor('#657047'),2));p.drawRoundedRect(r,10,10)
        p.restore()


class PhotoView(QListView):
    def __init__(self,thumbs,people=False,parent=None):
        super().__init__(parent);self.photo_model=PhotoModel(thumbs,people,self);self.setModel(self.photo_model)
        self.setItemDelegate(TileDelegate(people,self));self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust);self.setMovement(QListView.Static);self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.Batched);self.setBatchSize(200);self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection);self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAccessibleName('Personas' if people else 'Galería de fotografías')
        self.setFrameShape(QFrame.NoFrame)
        # Requests beyond the bounded queue are retried when capacity frees up.
        self.repaint_timer=QTimer(self);self.repaint_timer.setSingleShot(True);self.repaint_timer.setInterval(40)
        self.repaint_timer.timeout.connect(self.viewport().update)
        thumbs.ready.connect(self.retry_thumbnails)
    def retry_thumbnails(self,*args):
        if self.isVisible() and not self.repaint_timer.isActive():self.repaint_timer.start()
    def records(self): return self.photo_model.records
    def set_records(self,records): self.photo_model.set_records(records)
    def selected(self): return [self.photo_model.records[i.row()] for i in sorted(self.selectedIndexes(),key=lambda x:x.row())]
    def mousePressEvent(self,event):
        index=self.indexAt(event.position().toPoint())
        if event.button()==Qt.LeftButton and not event.modifiers() and index.isValid():
            self.selectionModel().select(index,QItemSelectionModel.Toggle)
            self.selectionModel().setCurrentIndex(index,QItemSelectionModel.NoUpdate)
            self.clicked.emit(index);return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self,event):
        # Our toggle-on-click handler does not populate QListView's private
        # pressed-index state. Emit activation explicitly for the item under
        # the pointer instead of relying on its default double-click handler.
        index=self.indexAt(event.position().toPoint())
        if event.button()==Qt.LeftButton and index.isValid():
            self.selectionModel().setCurrentIndex(index,QItemSelectionModel.NoUpdate)
            self.doubleClicked.emit(index);event.accept();return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Return,Qt.Key_Enter) and self.currentIndex().isValid():
            self.doubleClicked.emit(self.currentIndex());event.accept();return
        super().keyPressEvent(event)


class ZoomView(QGraphicsView):
    def __init__(self,parent=None):
        super().__init__(parent);self.setScene(QGraphicsScene(self));self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse);self.setBackgroundBrush(QColor('#efebe5'))
        self.setRenderHint(QPainter.SmoothPixmapTransform)
    def image(self,image):
        self.scene().clear();item=self.scene().addPixmap(QPixmap.fromImage(image));self.setSceneRect(item.boundingRect());self.fit()
    def fit(self): self.fitInView(self.sceneRect(),Qt.KeepAspectRatio)
    def wheelEvent(self,event): self.scale(1.2 if event.angleDelta().y()>0 else 1/1.2,1.2 if event.angleDelta().y()>0 else 1/1.2)


class Viewer(QDialog):
    def __init__(self,records,start=0,parent=None,compare=False):
        super().__init__(parent);self.records=records;self.position=start;self.tasks={};self.compare=compare;self.generation=0;self.closing=False;self.completed=False
        self.close_timer=QTimer(self);self.close_timer.setSingleShot(True);self.close_timer.timeout.connect(lambda:self.done(self.close_result))
        self.setWindowTitle('Comparar fotografías' if compare else 'Fotos Claras · Visor');self.resize(1140,800)
        layout=QVBoxLayout(self);bar=QHBoxLayout()
        for text,fn in [('← Anterior',lambda:self.step(-1)),('Siguiente →',lambda:self.step(1)),('Ajustar',self.fit),('Pantalla completa',self.fullscreen),('Cerrar',self.close)]:
            b=QPushButton(text);b.clicked.connect(fn);bar.addWidget(b)
        layout.addLayout(bar);self.info=QLabel();self.info.setWordWrap(True);self.info.setTextInteractionFlags(Qt.TextSelectableByMouse);layout.addWidget(self.info)
        row=QHBoxLayout();self.left=ZoomView();row.addWidget(self.left);self.right=ZoomView() if compare else None
        if compare: row.addWidget(self.right)
        layout.addLayout(row,1);self.note=QLabel('Rueda: zoom · Arrastrá para recorrer · ← → para navegar · Esc para cerrar');layout.addWidget(self.note)
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1);self.show_photo()
    def fit(self):
        self.left.fit()
        if self.right: self.right.fit()
    def fullscreen(self): self.showNormal() if self.isFullScreen() else self.showFullScreen()
    def step(self,n): self.position=(self.position+n)%len(self.records);self.show_photo()
    def show_photo(self):
        if not self.records: return
        self.generation+=1;generation=self.generation
        current=self.records[self.position];pairs=[(current,self.right if self.compare else self.left)]
        if self.compare: pairs.insert(0,(self.records[0],self.left))
        self.info.setText('\n'.join(f"{r['path']}  ·  {r.get('width','—')} × {r.get('height','—')}  ·  {(r.get('size') or 0)/1048576:.2f} MB  ·  {r.get('format') or ''}  ·  {r.get('captured') or ''}" for r,_ in pairs))
        for r,view in pairs:
            def read(_,path=r['path']):
                if generation!=self.generation or self.closing:return QImage()
                return decode_image(path,6000)
            task=Task(read);key=id(task);self.tasks[key]=task
            task.signals.finished.connect(lambda data,v=view,g=generation,k=key:self.loaded(data,v,g,k))
            task.signals.failed.connect(lambda err,k=key:self.load_failed(err,k));self.pool.start(task)
    def loaded(self,data,view,generation,key):
        self.tasks.pop(key,None)
        if generation==self.generation and not self.closing:view.image(data)
    def load_failed(self,error,key):
        self.tasks.pop(key,None)
        if not self.closing:self.note.setText('No se pudo abrir: '+error)
    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Right:self.step(1)
        elif event.key()==Qt.Key_Left:self.step(-1)
        elif event.key()==Qt.Key_F11:self.fullscreen()
        else:super().keyPressEvent(event)
    def done(self,result):
        if self.completed:return
        self.closing=True;self.generation+=1;self.close_result=result
        if self.pool.activeThreadCount():
            self.hide();self.close_timer.start(50);return
        self.completed=True;self.close_timer.stop()
        super().done(result)
    def closeEvent(self,event):
        event.ignore();self.done(QDialog.Rejected)


class Mosaic(QFrame):
    """Editorial collage of actual library thumbnails; no extra image decoding in UI."""
    def __init__(self,records,thumbs,parent=None):
        super().__init__(parent);self.records=records[:6];self.thumbs=thumbs
        self.setMinimumSize(240,240);thumbs.ready.connect(self.on_ready)
    def on_ready(self,*args):self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);w,h=self.width(),self.height();gap=5
        cells=[(0,0,.61,.55),(.61,0,.39,.36),(.61,.36,.39,.64),(0,.55,.29,.45),(.29,.55,.32,.23),(.29,.78,.32,.22)]
        for i,(x,y,rw,rh) in enumerate(cells):
            r=QRectF(x*w+gap/2,y*h+gap/2,rw*w-gap,rh*h-gap);clip=QPainterPath();clip.addRoundedRect(r,5,5);p.setClipPath(clip);p.fillRect(r,QColor('#e9e5d9'))
            if self.records:
                item=self.records[i%len(self.records)];image=self.thumbs.request(item.get('thumb') or item['path'])
                if image is not None and not image.isNull():
                    src=QRectF(image.rect());scale=max(r.width()/src.width(),r.height()/src.height());sw,sh=r.width()/scale,r.height()/scale
                    # Portraits favor the top third where faces are usually located.
                    top=max(0,(src.height()-sh)*.18)
                    p.drawImage(r,image,QRectF((src.width()-sw)/2,top,sw,sh))
            p.setClipping(False)
        p.end()
