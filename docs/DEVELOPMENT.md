# 开发与验证

推荐Python 3.11；纯分析和Web服务只需标准库及时区数据，微信依赖单列。

可选浏览器验收：安装Playwright和其Chromium后运行 `python tools/browser_smoke.py`。使用合成数据验证任务、日志、提示词、预览切换与窄屏布局，不调用模型；截图存入docs/assets。

```bat
python -m pip install -r requirements.txt
python -m unittest discover -v
python local_app.py --no-browser
```

web目录无需构建。local_app.py负责loopback API及进程调度；weekly_chat.py负责采集复用；history_store.py流式导出；gemini_analysis.py负责模型调用与排版；media_enrichment.py负责公开媒体提取缓存。

测试使用合成群名、占位密钥和模拟模型，不调用真实微信或付费API。浏览器验收使用临时合成报告。发布前显式审查文件清单和git暂存差异，不上传运行数据。

GitHub Actions在Windows/Python3.11运行测试，不配置生产密钥。CI不证明微信客户端兼容或商业库激活状态。提交不包含第三方库二进制或授权工具。
