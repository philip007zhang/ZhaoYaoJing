"""List visible WeChat process windows without reading chat messages."""
import psutil
import win32gui
import win32process


def callback(hwnd, _):
    if not win32gui.IsWindowVisible(hwnd):
        return
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        name = psutil.Process(pid).name().lower()
        if name in ('wechat.exe', 'weixin.exe'):
            print(f'hwnd={hwnd}, pid={pid}, title={win32gui.GetWindowText(hwnd)}')
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


if __name__ == '__main__':
    win32gui.EnumWindows(callback, None)
