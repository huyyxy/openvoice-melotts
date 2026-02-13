## 已识别的运行时下载依赖

构建过程需提前下载以下资源：

| 序号 | 依赖 | 来源 | 用途 |
| :--- | :--- | :--- | :--- |
| 1 | OpenVoice V2 Checkpoints | myshell-ai/OpenVoiceV2 (HuggingFace) | converter + base_speakers/ses |
| 2 | MeloTTS 语言模型 (ZH) | myshell-ai/MeloTTS-Chinese (HuggingFace) | config.json + checkpoint.pth |
| 3 | BERT: hfl/chinese-roberta-wwm-ext-large | HuggingFace | 中文 BERT 特征提取 |
| 4 | BERT: bert-base-multilingual-uncased | HuggingFace | 中文混合模式特征提取 |
| 5 | unidic 字典数据 | GitHub/PyPI | 日语文本处理依赖 |
| 6 | wavmark 模型 | HuggingFace | ToneColorConverter 水印 |
