# AliceReader Desktop

AliceReader Desktop 是 Windows 桌面版朗读工具。它支持在编辑器中输入文本，也可以通过全局快捷键导入其他应用当前选中的文本。

## 支持渠道

- **MiniMax T2A**：MiniMax Voice ID、`language_boost`、`emotion`、`speed`、`volume`、`pitch`、采样率和码率。
- **豆包 Speech**：豆包模型、`speaker` 音色和采样率。
- **阿里百炼**：Qwen3-TTS 或 CosyVoice；根据模型显示对应音色、语言、指令和速率参数。

设置窗口会按渠道动态切换参数，三套配置保存在 `providers.minimax`、`providers.doubao` 和 `providers.alibaba` 下。

## 环境要求

- Windows
- Python 3.10+
- `requests`

安装依赖：

```powershell
pip install requests
```

## 运行

直接双击 `start.vbs`，或运行：

```powershell
python main.py
```

首次启动后点击设置，选择朗读渠道并填写对应 API Key。也可以复制 `config.example.json` 为 `config.json` 后再启动。

## 使用

- 在桌面版编辑器中输入或粘贴文本，点击朗读。
- 在其他应用中选中文本后按 `Ctrl+Shift+S` 导入并朗读。
- 生成的音频会暂存在本地缓存中，历史记录保存在 `records.json`。

## 安全说明

`config.json`、`cache/`、`records.json` 和 `__pycache__/` 已加入 Git 忽略规则。请勿将 API Key 提交到 GitHub。
