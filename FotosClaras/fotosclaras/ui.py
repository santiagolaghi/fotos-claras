"""Álbum Editorial: a local library, human review and explicit file actions."""
from __future__ import annotations
import os
import sys
import threading
from pathlib import Path
from PySide6.QtCore import Qt,QThreadPool,QTimer,QUrl,QSize
from PySide6.QtGui import QDesktopServices,QStandardItemModel,QStandardItem,QShortcut,QKeySequence
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QFrame,QLabel,QPushButton,
    QVBoxLayout,QHBoxLayout,QGridLayout,QStackedWidget,QProgressBar,QFileDialog,QMessageBox,
    QDialog,QDialogButtonBox,QListWidget,QListWidgetItem,QComboBox,QLineEdit,QCheckBox,
    QInputDialog,QTableView,QHeaderView,QAbstractItemView,QSplitter,QScrollArea)
from . import __version__
from .db import Catalog,data_dir
from .widgets import Task,Thumbnails,PhotoView,Viewer,Mosaic,FilePlanModel
from .dialogs import FolderPicker,validate_directory
from .jobs import ProcessTask
from .library_view import load_page,PAGE_SIZE
from .people_ui import PersonDialog,CompositionDialog,PhotoIdentityDialog
from .theme import STYLE,icon
from . import indexer,identity,matching,operations,updates


def label(text,name='',wrap=False):
    w=QLabel(text);w.setTextFormat(Qt.PlainText);w.setObjectName(name);w.setWordWrap(wrap);return w


def button(text,fn,primary=False):
    w=QPushButton(text);w.setCursor(Qt.PointingHandCursor)
    if primary:w.setObjectName('primary')
    w.clicked.connect(fn);return w


def card():
    w=QFrame();w.setObjectName('card');layout=QVBoxLayout(w);layout.setContentsMargins(22,20,22,20);return w,layout


class MainWindow(QMainWindow):
    def __init__(self,db_path=None):
        super().__init__();self.catalog=Catalog(db_path);self.path=self.catalog.path
        from .legacy import import_state
        import_state(self.catalog)
        self.setWindowTitle('Fotos Claras · '+__version__);self.resize(1400,880);self.setMinimumSize(980,680)
        self.setWindowIcon(icon('album'));self.setStyleSheet(STYLE)
        self.library=None;self.busy=False;self.task=None;self.cancel=threading.Event();self.pending_close=False
        self._folder_picker=None
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1);self.thumbs=Thumbnails(self)
        self.read_pool=QThreadPool(self);self.read_pool.setMaxThreadCount(2)
        self._reads={};self._generation=0;self.rendered_generation=0;self.page_data={};self.page_offset=0;self._closed=False;self._shutting_down=False
        self.close_timer=QTimer(self);self.close_timer.setSingleShot(True);self.close_timer.timeout.connect(self.close)
        self.section=0;self.current_grid=None;self.group_index=0;self.groups=[];self.album_filter=None
        self.filters=dict(include=[],exclude=[],mode='all',count=None,sort='date',favorite=False)
        self._build();key=self.catalog.pref('last_library')
        self.library=self.catalog.one('SELECT * FROM libraries WHERE id=?',(key,)) if key else None
        if self.library:self.load_library()
        else:self.refresh()
        self._heartbeat=QTimer(self);self._heartbeat.timeout.connect(self.heartbeat);self._heartbeat.start(1000);self.elapsed=0
        QShortcut(QKeySequence('Ctrl+O'),self,activated=self.choose_folder)

    def _build(self):
        root=QWidget();self.setCentralWidget(root);layout=QHBoxLayout(root);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(194);nav=QVBoxLayout(side);nav.setContentsMargins(16,22,16,18);nav.setSpacing(5)
        nav.addWidget(label('Fotos Claras','brand'));nav.addSpacing(20);self.nav=[]
        self.names=['Inicio','Galería','Duplicados','Versiones','Personas','Álbumes','Sin rostros','Configuración']
        icons=['home','gallery','copy','versions','people','album','none','settings']
        for i,(name,key) in enumerate(zip(self.names,icons)):
            if i==7:nav.addStretch(1)
            b=button(name,lambda checked=False,n=i:self.navigate(n));b.setObjectName('nav');b.setIcon(icon(key));b.setIconSize(QSize(20,20));b.setCheckable(True)
            nav.addWidget(b);self.nav.append(b)
        nav.addSpacing(12);nav.addWidget(label('LOCAL Y PRIVADO\nTus fotos se quedan en tu PC.','muted',True));nav.addWidget(label('BETA  ·  '+__version__,'eyebrow'))
        layout.addWidget(side)
        workspace=QWidget();body=QVBoxLayout(workspace);body.setContentsMargins(30,22,30,18);body.setSpacing(16)
        top=QHBoxLayout();self.breadcrumb=label('TU BIBLIOTECA','eyebrow');top.addWidget(self.breadcrumb);top.addStretch()
        self.library_button=button('Elegir carpeta',self.choose_folder);top.addWidget(self.library_button)
        self.scan_button=button('Actualizar biblioteca',lambda:self.scan(False));top.addWidget(self.scan_button)
        self.face_button=button('Buscar rostros',self.faces,True);top.addWidget(self.face_button);body.addLayout(top)
        self.stack=QStackedWidget();body.addWidget(self.stack,1)
        self.pages=[]
        for _ in self.names:
            page=QWidget();v=QVBoxLayout(page);v.setContentsMargins(0,0,0,0);v.setSpacing(15);self.pages.append((page,v));self.stack.addWidget(page)
        footer=QHBoxLayout();self.status=label('Elegí una carpeta para empezar.','muted',True);footer.addWidget(self.status,1)
        self.cancel_button=button('Pausar',self.cancel_job);self.cancel_button.hide();footer.addWidget(self.cancel_button)
        body.addLayout(footer);self.progress=QProgressBar();self.progress.setTextVisible(False);self.progress.setRange(0,100);self.progress.setValue(0);body.addWidget(self.progress)
        layout.addWidget(workspace,1)

    def heartbeat(self):
        if self.busy:
            self.elapsed+=1
            if self.elapsed>8:self.status.setText(self.status.text().split('  ·  trabajando')[0]+f'  ·  trabajando ({self.elapsed} s desde el último avance)')

    def cancel_job(self):self.cancel.set();self.cancel_button.setEnabled(False);self.status.setText('Pausando al completar el archivo actual…')

    def run(self,fn,finished=None,failed=None):
        if self.busy:return
        self.busy=True;self.elapsed=0;self.cancel=threading.Event();self.cancel_button.show();self.cancel_button.setEnabled(True)
        self.library_button.setEnabled(False);self.scan_button.setEnabled(False);self.face_button.setEnabled(False)
        self.progress.setRange(0,0);self.task=Task(lambda report:fn(self.cancel,report));self.task.signals.progress.connect(self.on_progress)
        self.task.signals.finished.connect(lambda result:self.job_done(result,finished));self.task.signals.failed.connect(lambda message:self.job_error(message,failed));self.pool.start(self.task)

    def run_analysis(self,kind):
        if self.busy or not self.library:return
        task=ProcessTask(kind,self.path,self.library['id'],self)
        self.busy=True;self.elapsed=0;self.task=task;self.cancel=task.cancel
        self.cancel_button.show();self.cancel_button.setEnabled(True)
        self.library_button.setEnabled(False);self.scan_button.setEnabled(False);self.face_button.setEnabled(False)
        self.progress.setRange(0,0);self.status.setText('Preparando análisis en segundo plano…')
        task.signals.progress.connect(self.on_progress)
        task.signals.finished.connect(lambda result:self.job_done(result,None))
        task.signals.failed.connect(lambda error:self.job_error(error))
        try:task.start()
        except Exception as exc:self.job_error(str(exc))

    def on_progress(self,stage,done,total):
        self.elapsed=0
        if total:self.progress.setRange(0,total);self.progress.setValue(done)
        else:self.progress.setRange(0,0)
        self.status.setText(f'{stage}  ·  {done:,} de {total:,}  ·  faltan {max(0,total-done):,}' if total else f'{stage}  ·  {done:,} encontradas')

    def reset_job(self):
        self.busy=False;self.cancel_button.hide();self.progress.setRange(0,100);self.progress.setValue(100)
        self.library_button.setEnabled(True);self.scan_button.setEnabled(bool(self.library));self.face_button.setEnabled(bool(self.library));self.task=None

    def job_done(self,result,finished):
        paused=self.cancel.is_set();self.reset_job();self.refresh()
        errors=result.get('errors',0) if isinstance(result,dict) else 0
        self.status.setText('Pausado. Podés reanudar sin repetir los archivos completados.' if paused else (f'Análisis completado con {errors} errores. Abrí Configuración para ver los archivos afectados.' if errors else 'Listo. Tus cambios quedaron guardados.'))
        if finished and not paused and not self.pending_close:
            try:finished(result)
            except Exception as exc:self.error(exc)
        if self.pending_close:self.close()

    def job_error(self,message,failed=None):
        paused=self.cancel.is_set()
        self.reset_job();self.refresh();self.status.setText('Selección cancelada.' if paused else 'No se completó la operación. Revisá el detalle.')
        if self.pending_close:self.close();return
        if failed:failed(message)
        elif not paused:self.error(message)

    def error(self,message):QMessageBox.warning(self,'Fotos Claras',str(message))

    def with_catalog(self,fn):
        with Catalog(self.path) as c:return fn(c)

    def choose_folder(self):
        if self.busy:return
        if self._folder_picker is not None:
            self._folder_picker.raise_();self._folder_picker.activateWindow();return
        recent=[r['path'] for r in self.catalog.rows('SELECT path FROM libraries ORDER BY created DESC')]
        picker=FolderPicker(self,initial=self.library['path'] if self.library else '',recent=recent)
        self._folder_picker=picker
        picker.submitted.connect(self.check_folder)
        picker.finished.connect(self.folder_picker_finished)
        picker.open()

    def check_folder(self,path):
        def validate(cancel,report):
            report('Comprobando carpeta',0,1)
            return validate_directory(path,cancel)
        self.run(validate,self.apply_folder,self.folder_failed)

    def apply_folder(self,path):
        picker=self._folder_picker
        if picker is None:return
        try:
            self.library=self.catalog.library(path);self.section=0;self.album_filter=None;self.group_index=0;self.page_offset=0;self.load_library()
        except Exception as exc:
            picker.show_error('No se pudo abrir la biblioteca: '+str(exc));return
        picker.accept()
        self.status.setText('Carpeta elegida. Tocá «Actualizar biblioteca» para buscar tus fotos.')

    def folder_failed(self,message):
        if self._folder_picker is not None:self._folder_picker.show_error(message)

    def folder_picker_finished(self,result):
        picker=self._folder_picker;self._folder_picker=None
        if result!=QDialog.Accepted and self.busy:self.cancel.set()
        if picker is not None:picker.deleteLater()

    def load_library(self):
        self.catalog.set_pref('last_library',self.library['id']);self.breadcrumb.setText(Path(self.library['path']).name.upper() or self.library['path'])
        self.library_button.setText('Cambiar carpeta');self.library_button.setToolTip(self.library['path'])
        self.filters=self.catalog.pref('filters:'+self.library['id'],dict(include=[],exclude=[],mode='all',count=None,sort='date',favorite=False))
        self.scan_button.setEnabled(True);self.face_button.setEnabled(True);self.refresh()
        self.status.setText('Biblioteca abierta desde el catálogo. Elegí continuar o analizar las fotos nuevas.')

    def navigate(self,n):
        self.section=n;self.album_filter=None;self.page_offset=0
        if self.library:self.catalog.set_pref('last_section:'+self.library['id'],n)
        self.refresh()

    def clear_page(self,n):
        layout=self.pages[n][1]
        while layout.count():
            item=layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():self.clear_layout(item.layout())
        return layout
    def clear_layout(self,layout):
        while layout.count():
            i=layout.takeAt(0)
            if i.widget():i.widget().deleteLater()
            elif i.layout():self.clear_layout(i.layout())

    def refresh(self):
        if self._closed or self._shutting_down:return
        self._generation+=1;generation=self._generation
        self.current_grid=None
        for i,b in enumerate(self.nav):b.setChecked(i==self.section)
        self.stack.setCurrentIndex(self.section);layout=self.clear_page(self.section)
        self.scan_button.setEnabled(bool(self.library) and not self.busy);self.face_button.setEnabled(bool(self.library) and not self.busy)
        if not self.library and self.section!=7:
            self.welcome(layout);return
        if not self.library:
            self.page_data=dict(libraries=[],errors=[]);self.settings(layout);return
        layout.addWidget(label('Abriendo '+self.names[self.section].lower()+'…','muted'));layout.addStretch()
        # Debounce navigation/filter changes; discard stale results without ever
        # running a full library query on Qt's event loop.
        section=self.section;library=self.library['id'];filters=dict(self.filters);album=self.album_filter;offset=self.page_offset;group_index=self.group_index
        def begin():
            if generation!=self._generation or self._closed or self._shutting_down:return
            task=Task(lambda report:load_page(self.path,library,section,filters,album,offset,group_index));self._reads[generation]=task
            task.signals.finished.connect(lambda data:self.page_loaded(generation,section,data))
            task.signals.failed.connect(lambda message:self.page_failed(generation,message));self.read_pool.start(task)
        QTimer.singleShot(0,begin)

    def page_loaded(self,generation,section,data):
        self._reads.pop(generation,None)
        if self._closed or self._shutting_down or generation!=self._generation:return
        self.page_data=data
        self.rendered_generation=generation
        if 'offset' in data:self.page_offset=data['offset']
        layout=self.clear_page(section)
        [self.home,self.gallery,self.duplicates,self.versions,self.people,self.albums,self.no_faces,self.settings][section](layout)

    def page_failed(self,generation,message):
        self._reads.pop(generation,None)
        if not self._closed and generation==self._generation:
            layout=self.clear_page(self.section);layout.addWidget(label('No pudimos abrir esta vista: '+message,'muted',True));layout.addWidget(button('Reintentar',self.refresh))

    def welcome(self,v):
        v.addStretch();v.addWidget(label('UN LUGAR PARA TUS RECUERDOS','eyebrow'))
        v.addWidget(label('Tus recuerdos,\nen orden.','hero'));v.addWidget(label('Elegí dónde guardás tus fotos.\nVos decidís qué conservar y cómo organizarlas.','muted',True))
        b=button('Elegir mi biblioteca',self.choose_folder,True);b.setMaximumWidth(280);v.addWidget(b);v.addStretch(2)

    def heading(self,v,title,subtitle):
        v.addWidget(label(title,'title'));v.addWidget(label(subtitle,'muted',True))

    def home(self,v):
        hero,h=card();row=QHBoxLayout();left=QVBoxLayout();left.addWidget(label('REDESCUBRÍ TU BIBLIOTECA','eyebrow'))
        left.addWidget(label('Tus recuerdos,','hero'));left.addWidget(label('en orden.','heroAccent'));left.addWidget(label('Volvé a lo que realmente importa.\nUn espacio tranquilo para tus fotografías.','muted',True));left.addSpacing(12)
        left.addWidget(button('Explorar mis fotografías  →',lambda:self.navigate(1),True));left.addWidget(button('Continuar / analizar fotos nuevas',lambda:self.scan(False)))
        left.addStretch();row.addLayout(left,4)
        records=self.page_data['records']
        mosaic=Mosaic(records[:6],self.thumbs);row.addWidget(mosaic,6);h.addLayout(row);v.addWidget(hero,3)
        stats=self.page_data['stats'];exact=self.page_data['exact'];versions=self.page_data['versions']
        metrics=QHBoxLayout()
        for value,title,n in [(stats['total'],'Fotografías',1),(exact,'Grupos de copias exactas',2),(versions,'Versiones para revisar',3),(self.page_data['people'],'Personas agrupadas',4),(stats['no_faces'] or 0,'Sin rostros detectados',6)]:
            c,l=card();l.addWidget(label(f'{value:,}'.replace(',','.'),'metric'));text=label(title,'muted',True);text.setMinimumWidth(0);l.addWidget(text);c.setCursor(Qt.PointingHandCursor);c.mousePressEvent=lambda event,target=n:self.navigate(target);metrics.addWidget(c,1)
        v.addLayout(metrics)
        job=self.page_data['job']
        message=(f"Último análisis: {job['stage'] or job['kind']} · {job['done']}/{job['total']} · {job['errors']} errores" if job else 'Todavía no analizaste esta carpeta. Podés cambiarla antes de empezar.')
        if job and job['state']=='running' and not self.busy:message+=' · Interrumpido: podés reanudarlo.'
        v.addWidget(label(message,'muted',True))
        if stats['errors'] or stats['face_errors']:v.addWidget(button(f"Revisar errores de lectura ({stats['errors']}) y rostros ({stats['face_errors']})",lambda:self.navigate(7)))
        pending=self.page_data['pending']
        if pending:v.addWidget(button(f'{pending} operaciones requieren revisión →',self.history))

    def scan(self,full=False):
        if not self.library or self.busy:return
        self.run_analysis('index')
    def faces(self):
        if not self.library or self.busy:return
        self.run_analysis('faces')

    def grid(self,v,records,people=False):
        grid=PhotoView(self.thumbs,people);grid.set_records(records);v.addWidget(grid,1)
        if not people:grid.doubleClicked.connect(lambda index:self.open_viewer(grid.records(),index.row()))
        self.current_grid=grid
        return grid

    def open_viewer(self,records,start=0,compare=False):
        if records:
            dialog=Viewer(records,start,self,compare);dialog.exec();dialog.deleteLater()

    def gallery(self,v):
        self.heading(v,'Galería','Tus fotografías, listas para explorar. Un clic selecciona; doble clic amplía.')
        bar=QHBoxLayout();bar.addWidget(button('Filtrar personas y rostros',self.filter_dialog));bar.addWidget(button('Organizar por personas',self.composition_dialog))
        bar.addStretch();v.addLayout(bar);bar=QHBoxLayout()
        order=QComboBox();order.addItems(['Fecha','Nombre','Tamaño','Resolución']);order.setCurrentIndex(['date','name','size','resolution'].index(self.filters.get('sort','date')))
        order.currentIndexChanged.connect(lambda i:self.set_filter('sort',['date','name','size','resolution'][i]));bar.addWidget(order)
        favorites=QCheckBox('Solo favoritos');favorites.setChecked(self.filters.get('favorite',False));favorites.toggled.connect(lambda yes:self.set_filter('favorite',yes));bar.addWidget(favorites);bar.addStretch()
        bar.addWidget(button('Quitar filtros',self.clear_filters));v.addLayout(bar)
        records=self.page_data['records']
        text=f"{self.page_data['total']:,} fotografías"
        if self.filters.get('include') or self.filters.get('exclude') or self.filters.get('count') is not None:text+=' · Filtros activos'
        if self.album_filter:text+=' · Álbum seleccionado'
        summary=QHBoxLayout();summary.addWidget(label(text,'muted'));summary.addStretch()
        summary.addWidget(button('Organizar todos los resultados',self.organize_results));v.addLayout(summary)
        self.grid(v,records);self.pager(v);self.selection_toolbar(v)

    def pager(self,v):
        total=self.page_data['total'];offset=self.page_offset
        if total<=PAGE_SIZE:return
        row=QHBoxLayout()
        back=button('← Anteriores',lambda:self.change_page(-1));back.setEnabled(offset>0);row.addWidget(back)
        row.addWidget(label(f'{offset+1:,}–{min(total,offset+PAGE_SIZE):,} de {total:,}','muted'));row.addStretch()
        next_button=button('Siguientes →',lambda:self.change_page(1));next_button.setEnabled(offset+PAGE_SIZE<total);row.addWidget(next_button);v.addLayout(row)
    def change_page(self,step):self.page_offset=max(0,self.page_offset+step*PAGE_SIZE);self.refresh()

    def set_filter(self,k,value):self.page_offset=0;self.filters[k]=value;self.catalog.set_pref('filters:'+self.library['id'],self.filters);self.refresh()
    def clear_filters(self):self.page_offset=0;self.filters=dict(include=[],exclude=[],mode='all',count=None,sort='date',favorite=False);self.catalog.set_pref('filters:'+self.library['id'],self.filters);self.refresh()

    def filter_dialog(self):
        dialog=QDialog(self);dialog.setWindowTitle('Encontrá a tus personas');dialog.resize(640,550);v=QVBoxLayout(dialog)
        v.addWidget(label('¿Quiénes aparecen?','title'));search=QLineEdit();search.setPlaceholderText('Buscar una persona…');v.addWidget(search)
        row=QHBoxLayout();include=QListWidget();exclude=QListWidget();lists=[]
        for title,view,key in [('Deben aparecer',include,'include'),('No deben aparecer',exclude,'exclude')]:
            column=QVBoxLayout();column.addWidget(label(title));column.addWidget(view);row.addLayout(column)
            lists.append(view)
        v.addLayout(row,1)
        def search_people(text):
            for view in lists:
                for i in range(view.count()):view.item(i).setHidden(text.casefold() not in view.item(i).text().casefold())
        search.textChanged.connect(search_people)
        mode=QComboBox();mode.addItems(['Todas las seleccionadas, aunque haya más','Solo estas personas, sin nadie más','Estas personas con otras personas']);mode.setCurrentIndex(['all','only','others'].index(self.filters.get('mode','all')));v.addWidget(mode)
        count=QComboBox();count.addItems(['Cualquier cantidad de rostros','Ningún rostro','Exactamente 1 rostro','Exactamente 2 rostros','3 o más rostros']);current=self.filters.get('count');count.setCurrentIndex(0 if current is None else current+1);v.addWidget(count)
        v.addWidget(label('«Sin nadie más» se basa en los rostros detectados; puede haber personas que el detector no encontró.','muted',True))
        buttons=QDialogButtonBox(QDialogButtonBox.Apply|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Apply).setText('Ver fotografías');buttons.button(QDialogButtonBox.Apply).clicked.connect(dialog.accept);buttons.rejected.connect(dialog.reject);v.addWidget(buttons)
        apply=buttons.button(QDialogButtonBox.Apply);apply.setEnabled(False);alive=[True];library=self.library['id']
        def read(_):
            with Catalog(self.path) as c:return c.people(library,named=True)
        task=Task(read);key=id(task);self._reads[key]=task
        def ready(people):
            self._reads.pop(key,None)
            if not alive[0]:return
            for view,filter_key in [(include,'include'),(exclude,'exclude')]:
                for p in people:
                    item=QListWidgetItem(p['name']);item.setData(Qt.UserRole,p['id']);item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if p['id'] in self.filters.get(filter_key,[]) else Qt.Unchecked);view.addItem(item)
            apply.setEnabled(True)
        task.signals.finished.connect(ready);task.signals.failed.connect(lambda message:apply.setToolTip(message) if alive[0] else None)
        dialog.finished.connect(lambda _:alive.__setitem__(0,False));self.read_pool.start(task)
        if dialog.exec():
            inc=[include.item(i).data(Qt.UserRole) for i in range(include.count()) if include.item(i).checkState()==Qt.Checked]
            exc=[exclude.item(i).data(Qt.UserRole) for i in range(exclude.count()) if exclude.item(i).checkState()==Qt.Checked]
            if set(inc)&set(exc):self.error('Una persona está marcada para aparecer y para excluir. Ajustá el filtro.');return
            self.page_offset=0;self.filters.update(include=inc,exclude=exc,mode=['all','only','others'][mode.currentIndex()],count=None if count.currentIndex()==0 else count.currentIndex()-1)
            self.catalog.set_pref('filters:'+self.library['id'],self.filters);self.refresh()

    def selection_toolbar(self,v):
        row=QHBoxLayout();self.selection_label=label('Seleccioná fotografías','muted');row.addWidget(self.selection_label);row.addStretch()
        row.addWidget(button('Seleccionar página',lambda:self.current_grid.selectAll()));row.addWidget(button('Favorito',self.favorite))
        row.addWidget(button('Abrir carpeta',self.reveal));row.addWidget(button('Organizar selección',self.organize,True));v.addLayout(row)
        identify=button('Identificar rostros de la foto seleccionada',self.identify_photo);v.addWidget(identify)
        grid=self.current_grid
        grid.selectionModel().selectionChanged.connect(lambda *_:self.selection_label.setText(f'{len(grid.selected())} seleccionadas'))

    def selected(self):return self.current_grid.selected() if self.current_grid else []
    def identify_photo(self):
        if self.busy:return
        records=self.selected()
        if len(records)!=1:self.error('Seleccioná una sola foto para identificar sus rostros.');return
        dialog=PhotoIdentityDialog(self.path,records[0],self.thumbs,self)
        dialog.searchRequested.connect(self.regroup_people);dialog.exec();dialog.deleteLater();self.refresh()
    def favorite(self):
        records=self.selected()
        if self.busy or not records:return
        with self.catalog.db:
            for r in records:self.catalog.db.execute('UPDATE photos SET favorite=? WHERE id=?',(0 if r.get('favorite') else 1,r['id']))
        self.refresh()
    def reveal(self):
        records=self.selected()
        if not records:return
        path=Path(records[0]['path'])
        if os.name=='nt':
            import subprocess
            subprocess.Popen(['explorer.exe','/select,',str(path)])
        else:QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def duplicates(self,v):
        self.heading(v,'Duplicados exactos','Píxeles completos idénticos o secuencias de archivo idénticas. La recomendación nunca mueve fotos por sí sola.')
        self.groups=self.page_data['groups'];self.render_groups(v,False)

    def versions(self,v):
        self.heading(v,'Versiones para revisar','Posibles compresiones o tamaños de una misma foto. Una toma parecida puede aparecer aquí: compará antes de decidir.')
        self.version_pairs=self.page_data['pairs'];self.groups=self.page_data['groups']
        self.render_groups(v,True)

    def render_groups(self,v,versions):
        if not self.groups:
            v.addStretch();v.addWidget(label('Todavía no hay grupos para revisar.','title'));v.addWidget(label('Actualizá la biblioteca para comparar las fotografías.','muted'));v.addStretch();return
        self.group_index=self.page_data['group_index'];group=self.groups[0];total=self.page_data['group_total']
        row=QHBoxLayout();row.addWidget(button('← Anterior',lambda:self.step_group(-1)));row.addWidget(label(f"Grupo {self.group_index+1} de {total}  ·  {self.page_data.get('total',len(group))} archivos"));row.addWidget(button('Siguiente →',lambda:self.step_group(1)));row.addStretch()
        recommended=self.page_data.get('recommended',group[0])
        comparison=[recommended]+[r for r in group if r['id']!=recommended['id']]
        row.addWidget(button('Comparar con zoom',lambda:self.open_viewer(comparison,1 if len(comparison)>1 else 0,True),True));v.addLayout(row)
        if versions:v.addWidget(label('No hay certeza de duplicación: esta coincidencia exige revisión visual.','muted',True))
        else:v.addWidget(label('Sugerida para conservar: '+Path(recommended['path']).name+' · mayor resolución; a igual resolución, mayor tamaño. Revisá fecha y metadatos.','muted',True))
        self.grid(v,group)
        if not versions:self.pager(v)
        self.selection_toolbar(v)
        row=QHBoxLayout()
        if not versions:
            row.addWidget(button('Seleccionar copias sugeridas',self.select_copies))
        else:
            row.addWidget(button('Son fotos diferentes',lambda:self.decide_version('rejected')))
            row.addWidget(button('Confirmar que son versiones',lambda:self.decide_version('confirmed')))
        row.addStretch();row.addWidget(button('Apartar seleccionadas de la biblioteca',self.quarantine));v.addLayout(row)

    def step_group(self,n):
        if self.groups:self.group_index=(self.group_index+n)%self.page_data['group_total'];self.page_offset=0;self.refresh()
    def select_copies(self):
        from PySide6.QtCore import QItemSelectionModel
        self.current_grid.clearSelection()
        for i in range(1 if self.page_offset==0 else 0,len(self.current_grid.records())):self.current_grid.selectionModel().select(self.current_grid.model().index(i),QItemSelectionModel.Select)
    def decide_version(self,decision):
        if self.busy:return
        pair=self.version_pairs[0]
        with self.catalog.db:self.catalog.db.execute("UPDATE pairs SET decision=? WHERE a=? AND b=? AND kind='version'",(decision,pair['a'],pair['b']))
        self.refresh()

    def people(self,v):
        self.heading(v,'Personas','Poné un nombre al grupo una vez. Revisá las muestras y corregí cualquier rostro mezclado.')
        row=QHBoxLayout();row.addWidget(button('Volver a buscar coincidencias',self.regroup_people));row.addWidget(button('Organizar por personas',self.composition_dialog));row.addWidget(button('Ver personas ignoradas',self.ignored_people));row.addStretch();v.addLayout(row)
        records=self.page_data['records'];grid=self.grid(v,records,True);self.pager(v)
        grid.doubleClicked.connect(lambda index:self.person_detail(grid.records()[index.row()]))
        row=QHBoxLayout();row.addWidget(label(f"{self.page_data['total']} grupos · doble clic para ver rostros y fotos",'muted',True));row.addStretch()
        row.addWidget(button('Identificar / revisar persona',self.selected_person,True));row.addWidget(button('Unir grupos',self.merge_people));row.addWidget(button('Ignorar',self.ignore_people));v.addLayout(row)
        if not records:v.addWidget(label('Si todavía no buscaste rostros, usá el botón de arriba. Los fallos de análisis se muestran en Configuración.','muted',True))

    def regroup_people(self):
        if self.busy:return
        self.run_analysis('regroup')
    def selected_person(self):
        rows=self.selected()
        if len(rows)!=1:self.error('Seleccioná una persona para revisar.');return
        self.person_detail(rows[0])

    def person_detail(self,person):
        if self.busy:return
        dialog=PersonDialog(self.path,self.library['id'],person,self.thumbs,self)
        dialog.searchRequested.connect(self.regroup_people)
        dialog.photosRequested.connect(lambda p:self.show_person_photos(p,dialog))
        dialog.exec();dialog.deleteLater();self.refresh()

    def composition_dialog(self):
        if not self.library:return
        library=self.library['id']
        def read(_):
            with Catalog(self.path) as c:return c.people(library,named=True)
        task=Task(read);key=id(task);self._reads[key]=task
        def loaded(people):
            self._reads.pop(key,None)
            if self._closed or not self.library or self.library['id']!=library:return
            if not people:self.error('Primero identificá una persona en Personas.');return
            dialog=CompositionDialog(self.path,library,people,self.filters.get('include',()),self)
            dialog.viewRequested.connect(self.apply_people_rule);dialog.exec();dialog.deleteLater()
        task.signals.finished.connect(loaded);task.signals.failed.connect(lambda message:self.error(message));self.read_pool.start(task)

    def apply_people_rule(self,rule):
        self.filters.update(rule);self.album_filter=None;self.section=1;self.page_offset=0
        self.catalog.set_pref('filters:'+self.library['id'],self.filters);self.refresh()

    def show_person_photos(self,person,dialog):
        self.filters.update(include=[person['id']],exclude=[],mode='all',count=None);dialog.accept();self.section=1
    def merge_people(self):
        if self.busy:return
        rows=self.selected()
        if len(rows)<2:self.error('Seleccioná al menos dos grupos que pertenezcan a la misma persona.');return
        options=[(r['name'] or 'Sin nombre')+' · '+r['id'][:6] for r in rows]
        choice,ok=QInputDialog.getItem(self,'Unir personas','¿Qué grupo conserva el nombre?',options,0,False)
        if not ok:return
        target=rows[options.index(choice)]
        if QMessageBox.question(self,'Unir grupos',f"¿Confirmás que estos {len(rows)} grupos son {target['name'] or 'la misma persona'}?")!=QMessageBox.Yes:return
        try:
            # Validate the whole merge before applying any part.
            ids=[r['id'] for r in rows]
            for i,a in enumerate(ids):
                for b in ids[i+1:]:
                    if self.catalog.one('SELECT 1 FROM faces a JOIN faces b ON a.photo_id=b.photo_id WHERE a.person_id=? AND b.person_id=? LIMIT 1',(a,b)):
                        raise ValueError('Dos grupos aparecen como rostros diferentes en la misma foto. Revisalos antes de unir.')
            for r in rows:
                if r['id']!=target['id']:identity.merge(self.catalog,r['id'],target['id'])
            self.refresh()
        except ValueError as exc:self.error(exc)
    def ignore_people(self):
        if self.busy:return
        for r in self.selected():identity.ignore(self.catalog,r['id'])
        self.refresh()
    def ignored_people(self):
        rows=self.catalog.people(self.library['id'],True)
        if not rows:self.error('No hay personas ignoradas.');return
        options=[(r['name'] or 'Sin nombre')+' · '+r['id'][:6] for r in rows]
        choice,ok=QInputDialog.getItem(self,'Personas ignoradas','Elegí una persona para volver a mostrarla',options,0,False)
        if ok:identity.ignore(self.catalog,rows[options.index(choice)]['id'],False);self.refresh()

    def albums(self,v):
        self.heading(v,'Álbumes','Un álbum virtual reúne fotos sin duplicarlas. Las carpetas representan ubicaciones reales del disco.')
        row=QHBoxLayout();row.addWidget(button('Crear álbum virtual',self.new_album,True));row.addWidget(button('Renombrar álbum',self.rename_album));row.addStretch();v.addLayout(row)
        self.album_list=QListWidget();v.addWidget(self.album_list,1)
        for a in self.page_data['albums']:
            item=QListWidgetItem(icon('album'),f"{a['name']}   ·   {a['n']} fotografías   ·   "+('inteligente' if a['rule'] else 'álbum virtual'));item.setData(Qt.UserRole,dict(kind='virtual',**a));self.album_list.addItem(item)
        for path in self.page_data['parents']:
            item=QListWidgetItem(icon('album'),path+'   ·   carpeta real');item.setData(Qt.UserRole,dict(kind='folder',path=path));self.album_list.addItem(item)
        self.album_list.itemDoubleClicked.connect(self.open_album)
        v.addWidget(label('Doble clic para ver el contenido. Organizá las fotos desde la galería para agregarlas, copiarlas o moverlas.','muted',True))
    def new_album(self):
        if self.busy:return
        name,ok=QInputDialog.getText(self,'Nuevo álbum virtual','Nombre del álbum')
        if ok:
            try:self.catalog.create_album(self.library['id'],name);self.refresh()
            except Exception as exc:self.error(exc)
    def rename_album(self):
        if self.busy:return
        item=self.album_list.currentItem()
        if not item or item.data(Qt.UserRole)['kind']!='virtual':self.error('Seleccioná un álbum virtual. Las carpetas se gestionan desde el Explorador.');return
        a=item.data(Qt.UserRole);name,ok=QInputDialog.getText(self,'Renombrar álbum','Nuevo nombre',text=a['name'])
        if ok and name.strip():
            try:
                with self.catalog.db:self.catalog.db.execute('UPDATE albums SET name=? WHERE id=?',(name.strip(),a['id']))
                self.refresh()
            except Exception as exc:self.error(exc)
    def open_album(self,item):
        a=item.data(Qt.UserRole)
        if a['kind']=='virtual':
            self.filters=dict(include=[],exclude=[],mode='all',count=None,sort='date',favorite=False)
            self.section=1;self.album_filter=a['id'];self.page_offset=0;self.refresh()
        else:
            rows=[r for r in self.catalog.photos(self.library['id']) if str(Path(r['path']).parent)==a['path']]
            dialog=QDialog(self);dialog.setWindowTitle(a['path']);dialog.resize(1000,720);v=QVBoxLayout(dialog);grid=PhotoView(self.thumbs);grid.set_records(rows);v.addWidget(grid);grid.doubleClicked.connect(lambda index:self.open_viewer(rows,index.row()));dialog.exec()

    def no_faces(self,v):
        self.heading(v,'Sin rostros detectados','Solo fotos analizadas correctamente donde el detector no encontró caras. Puede haber personas pequeñas, de perfil u ocultas.')
        stats=self.page_data['stats'];v.addWidget(label(f"Pendientes de analizar: {stats['pending'] or 0} · Errores faciales: {stats['face_errors'] or 0} · Errores de lectura: {stats['errors'] or 0}",'muted',True))
        self.grid(v,self.page_data['records']);self.pager(v);self.selection_toolbar(v)

    def organize_results(self):
        if self.busy or not self.library:return
        library=self.library['id'];filters=dict(self.filters);album=self.album_filter
        def read(cancel,report):
            report('Preparando todas las fotografías del resultado',0,1)
            return self.with_catalog(lambda c:c.photos(library,**filters,album=album))
        self.run(read,self.organize)

    def organize(self,records=None):
        if self.busy:return
        records=records or self.selected()
        if not records:self.error('Seleccioná fotografías para organizar.');return
        dialog=QDialog(self);dialog.setWindowTitle('Organizar fotografías');dialog.resize(590,430);v=QVBoxLayout(dialog)
        v.addWidget(label(f'{len(records)} fotografías seleccionadas','title'))
        mode=QComboBox();mode.addItems(['Agregar a álbum virtual · las fotos quedan donde están','Copiar a una carpeta · conservar originales','Mover a una carpeta · cambiar ubicación real']);v.addWidget(mode)
        albums=self.catalog.rows('SELECT * FROM albums WHERE library_id=? AND rule IS NULL ORDER BY name',(self.library['id'],));album=QComboBox();album.addItems([a['name'] for a in albums]+['Crear un álbum nuevo…']);v.addWidget(album)
        dest=QLineEdit();dest.setPlaceholderText('Carpeta de destino existente o nueva');v.addWidget(dest)
        def choose_dest():
            browser=QFileDialog(dialog,'Elegí la carpeta de destino',self.library['path'])
            browser.setFileMode(QFileDialog.Directory);browser.setOption(QFileDialog.DontUseNativeDialog,True)
            browser.setOption(QFileDialog.DontUseCustomDirectoryIcons,True);browser.setOption(QFileDialog.ShowDirsOnly,True)
            browser.fileSelected.connect(dest.setText);dialog._dest_browser=browser;browser.open()
        choose=button('Elegir carpeta de destino',choose_dest);v.addWidget(choose)
        v.addWidget(label('Para crear una carpeta física, escribí su ruta nueva. Vas a ver cada origen y destino antes de confirmar.','muted',True))
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Ok).setText('Continuar a vista previa');buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);v.addWidget(buttons)
        def mode_changed(i):album.setVisible(i==0);dest.setVisible(i!=0);choose.setVisible(i!=0)
        mode.currentIndexChanged.connect(mode_changed);mode_changed(0)
        if not dialog.exec():return
        ids=[r['id'] for r in records]
        if mode.currentIndex()==0:
            if album.currentIndex()==len(albums):
                name,ok=QInputDialog.getText(self,'Nuevo álbum','Nombre del álbum virtual')
                if not ok:return
                try:key=self.catalog.create_album(self.library['id'],name)
                except Exception as exc:self.error(exc);return
            else:key=albums[album.currentIndex()]['id']
            if QMessageBox.question(self,'Agregar a álbum',f'¿Agregar {len(ids)} fotografías al álbum virtual? Sus archivos conservan la ubicación actual.')==QMessageBox.Yes:
                self.catalog.add_album(key,ids);self.status.setText('Fotografías agregadas al álbum virtual.');self.refresh()
        else:
            if not dest.text().strip():self.error('Elegí o escribí una carpeta de destino.');return
            self.prepare_operation(ids,Path(dest.text()),'copy' if mode.currentIndex()==1 else 'move')

    def quarantine(self):
        if self.busy:return
        ids=[r['id'] for r in self.selected()]
        if not ids:self.error('Seleccioná las fotos que querés apartar.');return
        self.prepare_operation(ids,Path(self.library['path'])/'FotosClaras_ParaRevisar','quarantine')

    def prepare_operation(self,ids,dest,kind):
        library=self.library['id'];self.run(lambda cancel,report:self.with_catalog(lambda c:operations.plan(c,library,ids,dest,kind,preserve_tree=kind=='quarantine',cancel=cancel,report=report)),self.preview_operation)

    def preview_operation(self,plan):
        dialog=QDialog(self);dialog.resize(1100,650);dialog.setWindowTitle('Revisá exactamente qué ocurrirá');v=QVBoxLayout(dialog)
        title={'move':'Mover archivos','copy':'Copiar archivos','quarantine':'Apartar de la biblioteca'}[plan['kind']]
        v.addWidget(label(title,'title'));v.addWidget(label(f"{len(plan['items'])} archivos. No se sobrescribe ningún destino. El lote se registra para recuperar o deshacer.",'muted',True))
        table=QTableView();model=FilePlanModel(plan['items'],table)
        table.setModel(model);table.setEditTriggers(QAbstractItemView.NoEditTriggers);table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);v.addWidget(table,1)
        controls=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);controls.button(QDialogButtonBox.Ok).setText('Confirmar '+title.lower());controls.accepted.connect(dialog.accept);controls.rejected.connect(dialog.reject);v.addWidget(controls)
        if dialog.exec():
            key=operations.save_plan(self.catalog,plan)
            self.run(lambda cancel,report:self.with_catalog(lambda c:operations.execute(c,key,cancel,report)))

    def history(self):
        if self.busy:return
        from .legacy import import_history
        self.run(lambda cancel,report:self.with_catalog(lambda c:import_history(c,self.library['id'])),lambda _:self.show_history())

    def show_history(self):
        rows=self.catalog.rows('SELECT * FROM operations WHERE library_id=? ORDER BY created DESC',(self.library['id'],))
        if not rows:self.error('Todavía no hay operaciones en el historial.');return
        dialog=QDialog(self);dialog.resize(780,480);dialog.setWindowTitle('Historial y recuperación');v=QVBoxLayout(dialog);v.addWidget(label('Historial de archivos','title'));listing=QListWidget();v.addWidget(listing)
        for op in rows:
            count=self.catalog.one('SELECT COUNT(*) n FROM operation_items WHERE operation_id=?',(op['id'],))['n']
            status={'done':'Completado','undone':'Deshecho','running':'Interrumpido','interrupted':'Requiere revisión','paused':'Pausado','planned':'Pendiente','undoing':'Deshacer interrumpido'}.get(op['state'],op['state'])
            item=QListWidgetItem(f"{op['kind']} · {count} archivos · {status}"+((' · '+op['error']) if op['error'] else ''));listing.addItem(item)
        row=QHBoxLayout()
        def selected_op():return rows[listing.currentRow()] if listing.currentRow()>=0 else None
        def resume():
            op=selected_op()
            if op and op['state'] not in ('done','undone','undoing'):
                dialog.accept();self.run(lambda cancel,report:self.with_catalog(lambda c:operations.execute(c,op['id'],cancel,report)))
        def undo_op():
            op=selected_op()
            if not op or op['state']=='undone':return
            items=self.catalog.rows("SELECT * FROM operation_items WHERE operation_id=? AND state IN ('done','undoing')",(op['id'],))
            if not items:self.error('No hay archivos completados para restaurar. Revisá o reanudá la operación.');return
            text='\n'.join(f"{x['target']} → {x['source']}" for x in items[:12])
            if len(items)>12:text+=f'\n… y {len(items)-12} más'
            if op['kind']=='copy':text='Las copias se apartan a una carpeta de recuperación; los originales permanecen donde están.'
            if QMessageBox.question(dialog,'Deshacer operación',f'¿Restaurar {len(items)} archivos? Se comprobarán antes de moverlos.\n\n'+text)!=QMessageBox.Yes:return
            dialog.accept();self.run(lambda cancel,report:self.with_catalog(lambda c:operations.undo(c,op['id'],report)))
        row.addWidget(button('Reanudar operación',resume));row.addWidget(button('Deshacer seleccionada',undo_op));row.addStretch();row.addWidget(button('Cerrar',dialog.accept));v.addLayout(row);dialog.exec()

    def settings(self,v):
        self.heading(v,'Configuración','Tu biblioteca se procesa en esta computadora. Internet se usa para descargar modelos y actualizaciones.')
        c,l=card();l.addWidget(label('Bibliotecas recientes','eyebrow'));libraries=self.page_data['libraries']
        recent=QComboBox();recent.addItems([a['path'] for a in libraries]);l.addWidget(recent)
        def open_recent():
            if self.busy or not libraries:return
            self.library=libraries[recent.currentIndex()];self.section=0;self.load_library()
        l.addWidget(button('Abrir biblioteca seleccionada',open_recent));v.addWidget(c)
        actions=QGridLayout();actions.addWidget(button('Historial y deshacer',self.history),0,0);actions.addWidget(button('Respaldar catálogo',self.backup),0,1);actions.addWidget(button('Buscar actualizaciones',self.check_updates),1,0);actions.addWidget(button('Volver a versión anterior',self.rollback),1,1);v.addLayout(actions)
        v.addWidget(label('Diagnóstico','title'))
        errors=self.page_data['errors']
        listing=QListWidget();listing.setMinimumHeight(100)
        for p in errors:listing.addItem(p['path']+'\n'+(p['error'] or p['face_error'] or ''))
        if not errors:listing.addItem('No hay errores registrados de fotografías en esta biblioteca.')
        v.addWidget(listing,1)
        v.addWidget(label('Versión en prueba. Revisá las sugerencias antes de organizar tus fotos. Si una foto no pudo analizarse, el motivo aparece aquí.','muted',True))
        v.addWidget(label('Base local: '+str(self.path),'muted',True))
        if self.library:v.addWidget(button('Reintentar archivos fallidos / nuevos',lambda:self.scan(False)))
    def backup(self):
        if self.busy:return
        path,_=QFileDialog.getSaveFileName(self,'Guardar respaldo','Fotos-Claras-respaldo.sqlite3','Base SQLite (*.sqlite3)')
        if path:
            if Path(path).resolve()==self.path.resolve():self.error('Elegí otro archivo para el respaldo.');return
            self.run(lambda cancel,report:self.with_catalog(lambda c:c.backup(path)))
    def check_updates(self):
        if self.busy:return
        self.run(lambda cancel,report:updates.check(include_beta=True),self.offer_update)
    def offer_update(self,release):
        if release is None:QMessageBox.information(self,'Actualizaciones','No hay una versión más reciente con instalador publicado.');return
        if os.name!='nt':self.error('El instalador publicado es para Windows.');return
        if not getattr(sys,'frozen',False):self.error('Las actualizaciones automáticas están disponibles en la instalación de Windows. Esta copia se ejecuta desde código fuente.');return
        if QMessageBox.question(self,'Nueva versión',f"Está disponible {release['version']}. ¿Descargar e instalar? La app se cerrará para completar la instalación.")!=QMessageBox.Yes:return
        root=Path(sys.executable).resolve().parent.parent.parent
        def downloaded(path):
            updates.install(path,root);self.close()
        self.run(lambda cancel,report:updates.download(release,self.path.parent/'updates-v1',cancel,report),downloaded)
    def rollback(self):
        if not getattr(sys,'frozen',False) or os.name!='nt':self.error('La recuperación se habilita en la instalación de Windows cuando existe una versión anterior.');return
        script=Path(sys.executable).resolve().parent.parent.parent/'FotosClarasLauncher.exe'
        if script.exists():
            previous=script.parent/'previous-version.txt'
            if self.catalog.db.execute('PRAGMA user_version').fetchone()[0]>=2:
                try:compatible=updates.number(previous.read_text().strip())>=updates.number('0.9.0-beta.3')
                except (OSError,ValueError):compatible=False
                if not compatible:
                    self.error('La versión anterior no puede abrir este catálogo actualizado. Conservamos la versión actual y el respaldo previo; no se descartaron tus correcciones.');return
            import subprocess
            subprocess.Popen([str(script),'--rollback']);self.close()
        else:self.error('No se encontró el recuperador de la instalación.')
    def closeEvent(self,event):
        if self._closed:event.accept();return
        if self.busy:
            self.pending_close=True;self.cancel_job();event.ignore();return
        if self._folder_picker is not None:self._folder_picker.reject()
        self._shutting_down=True;self._generation+=1;self.thumbs.stopping=True
        self.thumbs.pool.clear()
        if self.thumbs.pool.activeThreadCount() or self.read_pool.activeThreadCount():
            self.close_timer.start(60);event.ignore();return
        self.close_timer.stop();self._heartbeat.stop();self._closed=True;self.catalog.close();event.accept()
