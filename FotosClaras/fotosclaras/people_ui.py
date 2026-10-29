"""Review identities and turn person combinations into live virtual albums."""
from __future__ import annotations
from PySide6.QtCore import Qt,QThreadPool,QTimer,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,
    QTabWidget,QListWidget,QListWidgetItem,QInputDialog,QComboBox)
from .db import Catalog,PHOTO_FIELDS,uid
from .widgets import Task,PhotoView,Viewer
from . import identity


def text(value):
    widget=QLabel(value);widget.setWordWrap(True);widget.setTextFormat(Qt.PlainText);return widget


class AsyncDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1)
        self.tasks={};self.generation=0;self.closing=False;self.completed=False
        self.close_timer=QTimer(self);self.close_timer.setSingleShot(True);self.close_timer.timeout.connect(lambda:self.done(self.close_result))
    def query(self,fn,callback):
        task=Task(lambda _:fn());key=id(task);self.tasks[key]=task
        def ready(result):
            self.tasks.pop(key,None)
            if not self.closing:callback(result)
        def failed(message):
            self.tasks.pop(key,None)
            if not self.closing:self.message.setText(message)
        task.signals.finished.connect(ready);task.signals.failed.connect(failed);self.pool.start(task)
    def done(self,result):
        if self.completed:return
        self.closing=True;self.close_result=result
        if self.pool.activeThreadCount():
            self.hide();self.close_timer.start(40);return
        self.completed=True;self.close_timer.stop()
        super().done(result)
    def closeEvent(self,event):event.ignore();self.done(QDialog.Rejected)


class PersonDialog(AsyncDialog):
    searchRequested=Signal()
    photosRequested=Signal(object)
    def __init__(self,path,library,person,thumbs,parent=None):
        super().__init__(parent);self.path=path;self.library=library;self.person=person;self.offsets=[0,0]
        self.setWindowTitle(person['name'] or '¿Quién es esta persona?');self.resize(1050,760)
        layout=QVBoxLayout(self);heading=text(person['name'] or '¿Quién es esta persona?');heading.setObjectName('title');layout.addWidget(heading)
        self.message=text('Revisá las muestras antes de confirmar. Las coincidencias probables se muestran aparte.');layout.addWidget(self.message)
        row=QHBoxLayout();self.name=QLineEdit(person['name']);self.name.setPlaceholderText('Nombre de esta persona');row.addWidget(self.name,1)
        self.save=QPushButton('Guardar nombre y buscar más coincidencias');self.save.clicked.connect(self.save_name);row.addWidget(self.save);layout.addLayout(row)
        self.tabs=QTabWidget();self.views=[]
        for title in ('Rostros del grupo','Posibles coincidencias'):
            view=PhotoView(thumbs);view.doubleClicked.connect(lambda index,v=view:self.open_photo(v,index.row()))
            self.tabs.addTab(view,title);self.views.append(view)
        layout.addWidget(self.tabs,1);self.tabs.currentChanged.connect(self.load)
        self.page_label=text('Abriendo rostros…');row=QHBoxLayout();row.addWidget(self.page_label);row.addStretch()
        self.previous=QPushButton('← Anteriores');self.previous.clicked.connect(lambda:self.page(-1));row.addWidget(self.previous)
        self.next=QPushButton('Siguientes →');self.next.clicked.connect(lambda:self.page(1));row.addWidget(self.next);layout.addLayout(row)
        self.review_bar=QHBoxLayout();secondary=QHBoxLayout()
        for title,fn in [('Seleccionar página',lambda:self.views[self.tabs.currentIndex()].selectAll()),
                         ('Sí, es esta persona',lambda:self.review(True)),('No es esta persona',lambda:self.review(False)),
                         ('Separar rostros seleccionados',self.split),('Ver todas sus fotografías',self.show_photos),('Cerrar',self.accept)]:
            b=QPushButton(title);b.clicked.connect(fn)
            (secondary if title in ('Separar rostros seleccionados','Ver todas sus fotografías','Cerrar') else self.review_bar).addWidget(b)
        layout.addLayout(self.review_bar);layout.addLayout(secondary);self.total=0;self.save.setEnabled(False);self.load()
    def load(self,*_):
        self.generation+=1;generation=self.generation;tab=self.tabs.currentIndex();offset=self.offsets[tab]
        self.views[tab].set_records([])
        def read():
            with Catalog(self.path) as c:
                fields=','.join('p.'+f for f in PHOTO_FIELDS)
                predicate='f.person_id=?' if tab==0 else 'EXISTS(SELECT 1 FROM face_candidates fc WHERE fc.face_id=f.id AND fc.person_id=?)'
                where=" FROM faces f JOIN photos p ON p.id=f.photo_id WHERE p.library_id=? AND p.state='active' AND p.error IS NULL AND p.face_state='done' AND "+predicate
                args=(self.library,self.person['id'])
                total=c.one('SELECT COUNT(*) n'+where,args)['n']
                rows=c.rows('SELECT '+fields+',f.id face_id,f.ordinal,f.thumb face_thumb,f.match_state,f.quality'+where+' ORDER BY f.locked DESC,f.quality DESC,f.id LIMIT 240 OFFSET ?',(*args,offset))
                for r in rows:r['thumb']=r['face_thumb']
                candidates=c.one("SELECT COUNT(*) n FROM face_candidates fc JOIN faces f ON f.id=fc.face_id JOIN photos p ON p.id=f.photo_id WHERE fc.person_id=? AND p.library_id=? AND p.state='active' AND p.face_state='done' AND p.error IS NULL",(self.person['id'],self.library))['n']
                return rows,total,candidates
        def ready(result):
            if generation!=self.generation:return
            rows,self.total,candidates=result;self.views[tab].set_records(rows);self.save.setEnabled(True)
            self.tabs.setTabText(1,f'Posibles coincidencias ({candidates})')
            self.page_label.setText(f'{min(offset+1,self.total)}–{offset+len(rows)} de {self.total} rostros')
            self.previous.setEnabled(offset>0);self.next.setEnabled(offset+240<self.total)
        self.query(read,ready)
    def page(self,step):
        tab=self.tabs.currentIndex();self.offsets[tab]=max(0,self.offsets[tab]+step*240);self.load()
    def open_photo(self,view,index):Viewer(view.records(),index,self).exec()
    def changed(self,search=True):
        self.accept()
        if search:self.searchRequested.emit()
    def save_name(self):
        name=self.name.text().strip()
        if not name:self.message.setText('Escribí un nombre para esta persona.');return
        self.save.setEnabled(False)
        def save():
            with Catalog(self.path) as c:identity.name_person(c,self.person['id'],name)
        self.query(save,lambda _:self.changed())
    def review(self,confirm):
        tab=self.tabs.currentIndex()
        if tab!=1 and not confirm:
            self.message.setText('Abrí «Posibles coincidencias» para confirmar o rechazar. Para corregir este grupo, seleccioná y separá sus rostros.');return
        ids=[r['face_id'] for r in self.views[tab].selected()]
        def save():
            with Catalog(self.path) as c:return identity.review_matches(c,self.person['id'],ids,confirm)
        self.query(save,lambda _:self.changed() if confirm else self.load())
    def split(self):
        if self.tabs.currentIndex()!=0:return
        ids=[r['face_id'] for r in self.views[0].selected()]
        def save():
            with Catalog(self.path) as c:return identity.split(c,self.person['id'],ids)
        self.query(save,lambda _:self.changed(False))
    def show_photos(self):self.accept();self.photosRequested.emit(self.person)


class CompositionDialog(AsyncDialog):
    viewRequested=Signal(object)
    def __init__(self,path,library,people,selected=(),parent=None):
        super().__init__(parent);self.path=path;self.library=library;self.people=people
        self.setWindowTitle('Organizar por personas');self.resize(700,610);layout=QVBoxLayout(self)
        heading=text('¿Quiénes aparecen juntos?');heading.setObjectName('title');layout.addWidget(heading)
        self.message=text('Elegí personas. Los terceros incluyen rostros desconocidos o ignorados. Los resultados dependen de los rostros detectados.');layout.addWidget(self.message)
        self.list=QListWidget();layout.addWidget(self.list,1)
        for p in people:
            item=QListWidgetItem(p['name']);item.setData(Qt.UserRole,p['id']);item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if p['id'] in selected else Qt.Unchecked);self.list.addItem(item)
        self.rows={}
        for mode,title in [('only','Solo estas personas'),('others','Estas personas y terceros'),('all','Todas donde aparecen juntas')]:
            row=QHBoxLayout();info=text(title+' · —');row.addWidget(info,1)
            see=QPushButton('Ver fotos');see.clicked.connect(lambda checked=False,m=mode:self.view(m));row.addWidget(see)
            album=QPushButton('Crear álbum');album.clicked.connect(lambda checked=False,m=mode:self.album(m));row.addWidget(album)
            layout.addLayout(row);self.rows[mode]=(info,see,album,title)
        close=QPushButton('Cerrar');close.clicked.connect(self.accept);layout.addWidget(close)
        self.list.itemChanged.connect(self.update_counts);self.update_counts()
    def selected(self):return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState()==Qt.Checked]
    def update_counts(self,*_):
        self.generation+=1;generation=self.generation;selected=self.selected()
        for info,see,album,title in self.rows.values():info.setText(title+' · …');see.setEnabled(False);album.setEnabled(False)
        if not selected:return
        def read():
            with Catalog(self.path) as c:return c.composition(self.library,selected)
        def ready(counts):
            if generation!=self.generation:return
            for mode,(info,see,album,title) in self.rows.items():
                info.setText(title+f' · {counts[mode]:,} fotos');see.setEnabled(True);album.setEnabled(True)
        self.query(read,ready)
    def rule(self,mode):return dict(include=self.selected(),exclude=[],mode=mode,count=None)
    def view(self,mode):self.viewRequested.emit(self.rule(mode));self.accept()
    def album(self,mode):
        selected=self.selected();names=[p['name'] for p in self.people if p['id'] in selected]
        suggestion=' y '.join(names)+(' y terceros' if mode=='others' else ' · solo' if mode=='only' else '')
        name,ok=QInputDialog.getText(self,'Álbum inteligente','Nombre · se actualizará con futuras coincidencias confirmadas o automáticas',text=suggestion)
        if not ok:return
        rule=self.rule(mode)
        def save():
            with Catalog(self.path) as c:return c.create_album(self.library,name,rule=rule)
        self.query(save,lambda _:self.message.setText('Álbum inteligente creado. Sus fotos mantienen la ubicación original.'))


class PhotoIdentityDialog(AsyncDialog):
    searchRequested=Signal()
    def __init__(self,path,photo,thumbs,parent=None):
        super().__init__(parent);self.path=path;self.photo=photo;self.people=[]
        self.setWindowTitle('Identificar rostros de esta foto');self.resize(920,630);layout=QVBoxLayout(self)
        heading=text('¿Quién aparece en esta foto?');heading.setObjectName('title');layout.addWidget(heading)
        self.message=text('Seleccioná un rostro y confirmá su persona. Esa confirmación servirá para buscar otras fotografías.');layout.addWidget(self.message)
        self.grid=PhotoView(thumbs);self.grid.doubleClicked.connect(lambda index:Viewer([photo],0,self).exec());layout.addWidget(self.grid,1)
        row=QHBoxLayout();self.person=QComboBox();row.addWidget(self.person,1)
        self.confirm=QPushButton('Confirmar persona');self.confirm.setEnabled(False);self.confirm.clicked.connect(self.assign);row.addWidget(self.confirm)
        new=QPushButton('Crear persona');new.clicked.connect(self.new_person);row.addWidget(new)
        close=QPushButton('Cerrar');close.clicked.connect(self.accept);row.addWidget(close);layout.addLayout(row)
        def read():
            with Catalog(path) as c:
                fields=','.join('p.'+f for f in PHOTO_FIELDS)
                faces=c.rows('SELECT '+fields+",f.id face_id,f.ordinal,f.thumb face_thumb,f.match_state,f.quality,pe.name FROM faces f JOIN photos p ON p.id=f.photo_id LEFT JOIN people pe ON pe.id=f.person_id WHERE p.id=? ORDER BY f.ordinal",(photo['id'],))
                for f in faces:f['thumb']=f['face_thumb']
                return faces,c.rows("SELECT id,name FROM people WHERE name<>'' AND ignored=0 ORDER BY name" )
        def ready(result):
            faces,self.people=result;self.grid.set_records(faces);self.person.addItems([p['name'] for p in self.people]);self.confirm.setEnabled(bool(self.people))
            if not faces:self.message.setText('No hay rostros disponibles. Completá «Buscar rostros». Si el detector omitió una cara, esta foto necesita revisión; no podemos asegurar que no haya personas.')
        self.query(read,ready)
    def assign(self):
        if not self.people:return
        self.save(self.people[self.person.currentIndex()]['id'])
    def new_person(self):
        if not self.grid.selected():self.message.setText('Seleccioná primero el rostro que querés identificar.');return
        name,ok=QInputDialog.getText(self,'Nueva persona','Nombre')
        if ok and name.strip():self.save(None,name.strip())
    def save(self,person,name=None):
        ids=[f['face_id'] for f in self.grid.selected()]
        if not ids:self.message.setText('Seleccioná el rostro que querés identificar.');return
        def write():
            with Catalog(self.path) as c:
                target=person or uid()
                with c.db:
                    if person is None:c.db.execute('INSERT INTO people(id,name) VALUES (?,?)',(target,name))
                    identity.review_matches(c,target,ids,True)
        def saved(_):self.accept();self.searchRequested.emit()
        self.query(write,saved)
