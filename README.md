# OpenVoice-MeloTTS

基于 **MeloTTS**（文本转语音）和 **OpenVoice V2**（音色转换）的一体化 TTS HTTP 服务，支持多语言合成与零样本声音克隆。

## 功能特性

- 🗣️ **多语言 TTS** — 支持中文（ZH）、英语（EN/EN_V2）、法语（FR）、日语（JP）、西班牙语（ES）、韩语（KR）
- 🎭 **零样本声音克隆** — 上传参考音频即可克隆音色，无需训练
- 🎛️ **音频参数控制** — 语速、音量、音高、采样率、声道数均可调节
- 📝 **自定义拼音词典** — 通过 JSON 配置修正中文多音字发音
- 🐳 **离线 Docker 部署** — 多阶段构建，运行时完全离线，无需网络
- 🔌 **双监听模式** — 支持 HTTP 和 Unix Socket 两种模式

## 项目结构

```
openvoice-melotts/
├── server.py              # Tornado HTTP 服务主程序
├── API.md                 # HTTP API 接口文档
├── Dockerfile             # 多阶段离线 Docker 镜像
├── docker_build.sh        # 模型下载 + Docker 构建脚本
├── custom_pinyin.json     # 自定义拼音词典（修正多音字）
├── demo_integration.py    # 集成演示脚本
├── MeloTTS/               # MeloTTS 源码（Git submodule）
└── OpenVoice/             # OpenVoice V2 源码（Git submodule）
```

## 技术架构

```
┌──────────────┐
│  HTTP 请求    │
└──────┬───────┘
       ▼
┌──────────────┐     ┌─────────────┐     ┌────────────────────┐
│ Tornado 服务  │────▶│  MeloTTS    │────▶│ OpenVoice V2       │
│ (server.py)  │     │ (文本→语音)   │     │ (音色转换, 仅克隆)  │
└──────────────┘     └─────────────┘     └────────────────────┘
       │
       ▼
┌──────────────┐
│  音频后处理    │  ← 音量/音高/采样率/声道 调整
└──────────────┘
```

## 快速开始

### Docker 部署（推荐）

**1. 下载模型并构建镜像**

```bash
# 默认仅构建中文（ZH），可通过 LANGUAGES 指定多语言
./docker_build.sh

# 构建多语言版本
LANGUAGES="ZH EN JP" ./docker_build.sh
```

构建脚本会自动下载以下模型资源：

**OpenVoice V2 音色转换模型**

| 模型 | HuggingFace Repo | 用途 |
| :--- | :--- | :--- |
| Converter | `myshell-ai/OpenVoiceV2` (`converter/`) | 音色转换核心模型 |
| Base Speakers SE | `myshell-ai/OpenVoiceV2` (`base_speakers/ses/`) | 各语言基础说话人音色向量 |

**MeloTTS 语言模型**（按 `LANGUAGES` 变量选择性下载）

| 语言 | HuggingFace Repo | 文件 |
| :--- | :--- | :--- |
| ZH（中文） | `myshell-ai/MeloTTS-Chinese` | config.json + checkpoint.pth |
| EN（英文） | `myshell-ai/MeloTTS-English` | config.json + checkpoint.pth |
| EN_V2（英文v2） | `myshell-ai/MeloTTS-English-v2` | config.json + checkpoint.pth |
| FR（法语） | `myshell-ai/MeloTTS-French` | config.json + checkpoint.pth |
| JP（日语） | `myshell-ai/MeloTTS-Japanese` | config.json + checkpoint.pth |
| ES（西班牙语） | `myshell-ai/MeloTTS-Spanish` | config.json + checkpoint.pth |
| KR（韩语） | `myshell-ai/MeloTTS-Korean` | config.json + checkpoint.pth |

**BERT 文本特征提取模型**（按语言自动匹配）

| 适用语言 | HuggingFace Repo | 说明 |
| :--- | :--- | :--- |
| ZH | `hfl/chinese-roberta-wwm-ext-large` | 中文 BERT 特征提取 |
| ZH | `bert-base-multilingual-uncased` | 中文混合模式特征提取 |
| EN / EN_V2 | `bert-base-uncased` | 英文 BERT 特征提取 |
| FR | `dbmdz/bert-base-french-europeana-cased` | 法语 BERT 特征提取 |
| JP | `tohoku-nlp/bert-base-japanese-v3` | 日语 BERT 特征提取 |
| ES | `dccuchile/bert-base-spanish-wwm-uncased` | 西班牙语 BERT 特征提取 |
| KR | `kykim/bert-kor-base` | 韩语 BERT 特征提取 |

**其他依赖数据**

| 依赖 | 来源 | 用途 |
| :--- | :--- | :--- |
| NLTK 数据包 | NLTK（`averaged_perceptron_tagger`、`cmudict`、`punkt`、`stopwords`、`wordnet`） | 英文文本分词/标注 |
| unidic 字典 | GitHub/PyPI | 日语文本处理（MeCab 形态素解析） |
| wavmark 模型 | HuggingFace（运行时自动加载） | ToneColorConverter 音频水印 |

> [!NOTE]
> 构建前需安装 `huggingface_hub` CLI：`pip install huggingface_hub[cli]`

**2. 运行容器**

```bash
# GPU 加速
docker run --gpus all -p 9883:9883 openvoice-melo-tts:latest

# 离线运行（断网验证）
docker run --gpus all --network=none -p 9883:9883 openvoice-melo-tts:latest
```

### 本地运行

确保已安装 MeloTTS 和 OpenVoice 依赖后：

```bash
# 默认 HTTP 模式，监听 0.0.0.0:9883
python server.py

# 指定端口和日志级别
python server.py --port 8080 --log-level DEBUG

# Unix Socket 模式
python server.py --mode unix --socket-path /tmp/tts.sock
```

## API 接口

服务默认监听 `http://0.0.0.0:9883`，完整接口文档见 [API.md](API.md)。

| 接口 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/health` | GET | 健康检查 |
| `/ticos/tts` | POST | 语音合成 |
| `/ticos/voice-clone` | POST | 声音克隆注册 |
| `/ticos/speakers` | GET | 说话人音色列表 |
| `/ticos/capabilities` | GET | 模型能力查询 |
| `/ticos/languages` | GET | 支持语言列表 |

### 使用示例

**语音合成**

```bash
curl -X POST "http://localhost:9883/ticos/tts" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "你好，这是一段测试语音。",
    "speaker_id": "ZH",
    "format": "wav"
  }' --output output.wav
```

**声音克隆 + 合成**

```bash
# 1. 上传参考音频，注册克隆音色
RESP=$(curl -s -X POST "http://localhost:9883/ticos/voice-clone" \
  -F "ref_audio=@/path/to/ref.wav")

# 2. 使用克隆音色合成
SPEAKER_ID=$(echo "$RESP" | jq -r '.data.speaker_id')
curl -X POST "http://localhost:9883/ticos/tts" \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"用克隆的音色说这句话。\",\"speaker_id\":\"$SPEAKER_ID\",\"format\":\"wav\"}" \
  --output output.wav
```

## 环境变量

| 变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `DEVICE` | `auto` | 计算设备（`auto`/`cuda:0`/`mps`/`cpu`） |
| `MELO_LANGUAGES` | `ZH` | 加载的语言列表，逗号分隔 |
| `CKPT_CONVERTER_DIR` | `./OpenVoice/checkpoints_v2/converter` | OpenVoice V2 Converter 权重目录 |
| `VOICE_CLONE_DIR` | `./voice_clones` | 克隆音色持久化目录 |
| `CUSTOM_PINYIN_DICT` | `./custom_pinyin.json` | 自定义拼音词典路径 |

## 命令行参数

```
python server.py [OPTIONS]

--mode {http,unix}       服务器模式 (默认: http)
--host HOST              HTTP 监听地址 (默认: 0.0.0.0)
--port PORT              HTTP 端口 (默认: 9883)
--socket-path PATH       Unix Socket 路径 (默认: /tmp/ticos_tts.sock)
--voice-clone-dir DIR    克隆数据目录
--custom-pinyin FILE     自定义拼音词典路径
--log-level LEVEL        日志级别: DEBUG/INFO/WARNING/ERROR (默认: INFO)
```

## 自定义拼音词典

通过 `custom_pinyin.json` 可修正中文多音字发音问题。格式示例：

```json
{
  "行长": [["háng"], ["zhǎng"]],
  "还款": [["huán"], ["kuǎn"]],
  "重置": [["chóng"], ["zhì"]]
}
```

词典在服务启动时自动加载，注入 `pypinyin` 以覆盖默认发音。

## 致谢

- [MeloTTS](https://github.com/myshell-ai/MeloTTS) — 高质量多语言 TTS 模型
- [OpenVoice](https://github.com/myshell-ai/OpenVoice) — 即时声音克隆技术
