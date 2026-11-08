"""Read the currently selected chat; never sends messages."""
from wxautox4 import WeChat

wx = WeChat()
print(wx.ChatInfo())
for message in wx.GetAllMessage():
    print(message.type, message.sender, message.content)
