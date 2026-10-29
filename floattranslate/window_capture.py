"""Windows source-window capture, independent of the translation overlay.

Never use an excluded desktop screenshot as evidence of a page change: some
capture paths return black / composited overlay pixels despite affinity success.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import sys

from PIL import Image
from PySide6.QtGui import QGuiApplication


def capture_underlay(rect, ignored=()):
    if sys.platform!='win32' or QGuiApplication.platformName()=='offscreen':
        return None
    screens=[s for s in QGuiApplication.screens() if s.geometry().contains(rect)]
    if len(screens)!=1:
        return None
    screen=screens[0]
    user=ctypes.windll.user32
    gdi=ctypes.windll.gdi32
    class MonitorInfo(ctypes.Structure):
        _fields_=[('cbSize',w.DWORD),('rcMonitor',w.RECT),('rcWork',w.RECT),('dwFlags',w.DWORD),('szDevice',w.WCHAR*32)]
    monitors=[]
    callback_type=ctypes.WINFUNCTYPE(w.BOOL,w.HMONITOR,w.HDC,ctypes.POINTER(w.RECT),w.LPARAM)
    def monitor_callback(monitor,dc,area,param):
        info=MonitorInfo()
        info.cbSize=ctypes.sizeof(info)
        if user.GetMonitorInfoW(monitor,ctypes.byref(info)):
            monitors.append((str(info.szDevice),info.rcMonitor.left,info.rcMonitor.top))
        return True
    callback=callback_type(monitor_callback)
    user.GetMonitorInfoW.argtypes=[w.HMONITOR,ctypes.POINTER(MonitorInfo)]
    user.EnumDisplayMonitors(None,None,callback,0)
    physical=next((m for m in monitors if m[0].casefold()==screen.name().casefold()),None)
    if physical is None:
        if len(monitors)!=1:
            return None
        physical=monitors[0]
    scale=screen.devicePixelRatio()
    x=physical[1]+round((rect.x()-screen.geometry().x())*scale)
    y=physical[2]+round((rect.y()-screen.geometry().y())*scale)
    width,height=round(rect.width()*scale),round(rect.height()*scale)
    center=(x+width//2,y+height//2)
    user.GetTopWindow.argtypes=[w.HWND]
    user.GetTopWindow.restype=w.HWND
    user.GetWindow.argtypes=[w.HWND,w.UINT]
    user.GetWindow.restype=w.HWND
    user.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
    user.IsWindowVisible.argtypes=[w.HWND]
    user.IsIconic.argtypes=[w.HWND]
    user.IsHungAppWindow.argtypes=[w.HWND]
    user.GetWindowLongW.argtypes=[w.HWND,ctypes.c_int]
    ignored=set(ignored)
    target=user.GetTopWindow(None)
    bounds=None
    for _ in range(1000):
        if not target:
            return None
        area=w.RECT()
        if (target not in ignored and user.IsWindowVisible(target) and not user.IsIconic(target)
                and not user.GetWindowLongW(target,-20)&0x20 and user.GetWindowRect(target,ctypes.byref(area))
                and area.left<=center[0]<area.right and area.top<=center[1]<area.bottom):
            if area.left>x or area.top>y or area.right<x+width or area.bottom<y+height:
                return None
            bounds=area
            break
        target=user.GetWindow(target,2)
    if bounds is None or user.IsHungAppWindow(target):
        return None
    bw,bh=bounds.right-bounds.left,bounds.bottom-bounds.top
    if bw<=0 or bh<=0 or bw*bh>24_000_000:
        return None
    class Header(ctypes.Structure):
        _fields_=[('size',w.DWORD),('width',w.LONG),('height',w.LONG),('planes',w.WORD),('bits',w.WORD),
                  ('compression',w.DWORD),('image_size',w.DWORD),('xppm',w.LONG),('yppm',w.LONG),('used',w.DWORD),('important',w.DWORD)]
    class BitmapInfo(ctypes.Structure):
        _fields_=[('header',Header),('colors',w.DWORD*3)]
    info=BitmapInfo()
    info.header=Header(ctypes.sizeof(Header),bw,-bh,1,32,0,0,0,0,0,0)
    user.GetDC.argtypes=[w.HWND]
    user.GetDC.restype=w.HDC
    user.ReleaseDC.argtypes=[w.HWND,w.HDC]
    gdi.CreateCompatibleDC.argtypes=[w.HDC]
    gdi.CreateCompatibleDC.restype=w.HDC
    gdi.CreateDIBSection.argtypes=[w.HDC,ctypes.POINTER(BitmapInfo),w.UINT,ctypes.POINTER(ctypes.c_void_p),w.HANDLE,w.DWORD]
    gdi.CreateDIBSection.restype=w.HBITMAP
    gdi.SelectObject.argtypes=[w.HDC,w.HANDLE]
    gdi.SelectObject.restype=w.HANDLE
    gdi.DeleteObject.argtypes=[w.HANDLE]
    gdi.DeleteDC.argtypes=[w.HDC]
    user.PrintWindow.argtypes=[w.HWND,w.HDC,w.UINT]
    user.PrintWindow.restype=w.BOOL
    dc=user.GetDC(None)
    memory=gdi.CreateCompatibleDC(dc)
    pointer=ctypes.c_void_p()
    bitmap=gdi.CreateDIBSection(dc,ctypes.byref(info),0,ctypes.byref(pointer),None,0)
    previous=None
    try:
        if not bitmap or not memory or not pointer.value:
            return None
        previous=gdi.SelectObject(memory,bitmap)
        if not user.PrintWindow(target,memory,2):
            return None
        data=ctypes.string_at(pointer.value,bw*bh*4)
        image=Image.frombytes('RGB',(bw,bh),data,'raw','BGRX')
        image=image.crop((x-bounds.left,y-bounds.top,x-bounds.left+width,y-bounds.top+height))
        if not image.getbbox():
            return None
        return image,scale,int(target)
    finally:
        if previous:
            gdi.SelectObject(memory,previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if dc:
            user.ReleaseDC(None,dc)
