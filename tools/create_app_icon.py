"""Render the native SVG logo into a multi-size Windows icon, without packaging."""
import os
import struct
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QByteArray,QBuffer,QIODevice
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

def main():
    app=QApplication.instance() or QApplication([])
    folder=Path(__file__).resolve().parents[1]/'resources'/'icons'; renderer=QSvgRenderer(str(folder/'tt-creator.svg')); entries=[]
    if not renderer.isValid(): raise ValueError('图标 SVG 无效')
    for size in (16,24,32,48,64,128,256):
        image=QImage(size,size,QImage.Format.Format_ARGB32); image.fill(0); painter=QPainter(image); painter.setRenderHint(QPainter.RenderHint.Antialiasing); renderer.render(painter); painter.end()
        data=QByteArray(); buffer=QBuffer(data); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer,'PNG'): raise ValueError('无法生成图标尺寸 '+str(size))
        entries.append((size,bytes(data)))
    offset=6+16*len(entries); directory=[]; payload=[]
    for size,data in entries:
        directory.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(data),offset)); payload.append(data); offset+=len(data)
    (folder/'tt-creator.ico').write_bytes(struct.pack('<HHH',0,1,len(entries))+b''.join(directory)+b''.join(payload))
    (folder/'tt-creator.png').write_bytes(entries[-1][1]); print('图标资源已生成：7 个尺寸，未构建软件')

if __name__=='__main__': main()
