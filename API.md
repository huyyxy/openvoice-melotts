# OpenVoice-Melo-TTS HTTP API 文档

本文档描述 OpenVoice-Melo-TTS 服务的 HTTP 接口。服务默认监听 `http://0.0.0.0:9883`，支持 HTTP 与 Unix Socket 两种模式。

---

## 目录

- [健康检查](#健康检查)
- [语音合成](#语音合成-post-ticostts)
- [声音克隆注册](#声音克隆注册-post-ticosvoice-clone)
- [说话人音色列表](#说话人音色列表-get-ticosspeakers)
- [模型能力查询](#模型能力查询-get-ticoscapabilities)
- [支持语言列表](#支持语言列表-get-ticoslanguages)

---

## 健康检查

### GET /health

获取服务健康状态。

**请求**

- 方法：`GET`
- 路径：`/health`
- 无请求体

**响应**

- Content-Type: `application/json`
- 示例：

```json
{
  "status": "healthy",
  "service": "openvoice-melo-tts-server",
  "version": "2.0.0"
}
```

| 字段     | 类型   | 说明 |
|----------|--------|------|
| status   | string | `healthy` 表示模型已加载；`degraded` 表示模型未加载 |
| service  | string | 服务名称 |
| version  | string | 服务版本 |

**示例**

```bash
curl -s http://localhost:9883/health
```

---

## 语音合成 POST /ticos/tts

根据文本与说话人合成语音。`speaker_id` 可以是**预设音色**（CustomVoice 模型自带的说话人）或**声音克隆返回的 speaker_id**（通过 [POST /ticos/voice-clone](#声音克隆注册-post-ticosvoice-clone) 注册得到）。

**请求**

- 方法：`POST`
- 路径：`/ticos/tts`
- Content-Type：`application/json` 或 `multipart/form-data`

**请求参数**

| 参数           | 类型    | 必填 | 默认值  | 说明 |
|----------------|---------|------|---------|------|
| text           | string  | 是   | -       | 要合成的文本内容 |
| speaker_id     | string  | 否*  | -       | 说话人 ID：预设音色名称，或声音克隆接口返回的 `speaker_id`。CustomVoice 模型下未传且无默认时需传 |
| volume_ratio   | number  | 否   | 50      | 音量，0–100，50 为 1.0 倍 |
| speed_ratio    | number  | 否   | 50      | 语速，0–100，50 为 1.0 倍 |
| pitch_ratio    | number  | 否   | 50      | 音高，0–100，50 为无偏移 |
| sample_rate    | integer | 否   | 16000   | 输出采样率（Hz） |
| channels       | integer | 否   | 1       | 声道数，1 或 2 |
| format         | string  | 否   | pcm     | 输出格式：`pcm` 或 `wav` |

**成功响应**

- Content-Type: `audio/wav` 或 `audio/pcm`
- Content-Disposition: `attachment; filename="output.wav"` 或 `output.pcm`
- 响应体：二进制音频流

**错误响应**

- Content-Type: `application/json`
- HTTP 状态码：400（参数错误）、500（服务/模型错误）
- 体例：`{ "code": 400|500, "message": "错误说明", "data": {} }`

**示例**

```bash
# JSON：使用预设说话人
curl -X POST "http://localhost:9883/ticos/tts" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "你好，这是一段测试语音。",
    "speaker_id": "longxiaochun",
    "format": "wav"
  }' --output output.wav

# JSON：使用声音克隆得到的 speaker_id
curl -X POST "http://localhost:9883/ticos/tts" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "用克隆的音色说这句话。",
    "speaker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "format": "wav"
  }' --output output.wav

# form-data
curl -X POST "http://localhost:9883/ticos/tts" \
  -F "text=你好世界" \
  -F "speaker_id=longxiaochun" \
  -F "format=wav" \
  -F "sample_rate=16000" \
  --output output.wav
```

---

## 声音克隆注册 POST /ticos/voice-clone

上传参考音频并注册为可复用的说话人，返回 `speaker_id`。后续在 [POST /ticos/tts](#语音合成-post-ticostts) 中传入该 `speaker_id` 即可使用该克隆音色合成，无需再次上传参考音频。

**请求**

- 方法：`POST`
- 路径：`/ticos/voice-clone`
- Content-Type：`application/json` 或 `multipart/form-data`

**请求参数**

| 参数       | 类型   | 必填 | 说明 |
|------------|--------|------|------|
| ref_audio  | string / file | 是   | 参考音频。支持：语音文件 URL、Base64 编码字符串（可带 `data:audio/...;base64,` 前缀）、或通过 form-data 上传的语音文件。 |

**成功响应**

- Content-Type: `application/json`
- HTTP 状态码：200
- 示例：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "speaker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

| 字段             | 类型   | 说明 |
|------------------|--------|------|
| code             | integer | 0 表示成功 |
| message          | string | 固定为 `成功` |
| data.speaker_id  | string | 注册后的说话人 ID，在 POST /ticos/tts 的 `speaker_id` 参数中使用，即可用该克隆音色合成。 |

**错误响应**

- Content-Type: `application/json`
- 可能状态码：400（参数错误）、500（模型类型不支持或处理失败）
- 体例：`{ "code": 400|500, "message": "错误说明" }`

**示例**

```bash
# JSON：ref_audio 为 URL
curl -s -X POST "http://localhost:9883/ticos/voice-clone" \
  -H "Content-Type: application/json" \
  -d '{
    "ref_audio": "https://example.com/path/to/ref.wav"
  }'

# JSON：ref_audio 为 Base64
curl -s -X POST "http://localhost:9883/ticos/voice-clone" \
  -H "Content-Type: application/json" \
  -d "{
    \"ref_audio\": \"data:audio/wav;base64,<BASE64_STRING>\"
  }"

# form-data：上传本地语音文件
curl -s -X POST "http://localhost:9883/ticos/voice-clone" \
  -F "ref_audio=@/path/to/ref.wav"
```

**与语音合成的配合使用**

1. 调用 `POST /ticos/voice-clone` 注册参考音，得到响应中的 `speaker_id`。
2. 调用 `POST /ticos/tts` 时在参数中传入该 `speaker_id`，即可用该克隆音色合成任意文本，无需再次上传参考音频。

```bash
# 1. 注册
RESP=$(curl -s -X POST "http://localhost:9883/ticos/voice-clone" \
  -H "Content-Type: application/json" \
  -d '{"ref_audio":"https://example.com/ref.wav"}')
SPEAKER_ID=$(echo "$RESP" | jq -r '.speaker_id')

# 2. 使用 speaker_id 合成
curl -X POST "http://localhost:9883/ticos/tts" \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"任意新文本\",\"speaker_id\":\"$SPEAKER_ID\",\"format\":\"wav\"}" \
  --output output.wav
```

---

## 说话人音色列表 GET /ticos/speakers

获取当前服务可用的所有说话人音色，包括模型**预设（内置）音色**和通过声音克隆接口注册的**克隆音色**。

**请求**

- 方法：`GET`
- 路径：`/ticos/speakers`
- 无请求体

**成功响应**

- Content-Type: `application/json`
- HTTP 状态码：200
- 示例：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "speakers": [
      { "speaker_id": "longxiaochun", "type": "builtin" },
      { "speaker_id": "longxiaoxia", "type": "builtin" },
      {
        "speaker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "type": "cloned"
      }
    ]
  }
}
```

| 字段                 | 类型   | 说明 |
|----------------------|--------|------|
| code                 | integer | 0 表示成功 |
| message              | string | 固定为 `成功` |
| data.speakers        | array  | 说话人音色列表（预设音色在前，克隆音色在后） |
| data.speakers[].speaker_id | string | 说话人 ID，可直接用于 POST /ticos/tts 的 `speaker_id` |
| data.speakers[].type | string | 音色来源：`builtin` 预设音色，`cloned` 声音克隆 |


**错误响应**

- HTTP 503：模型未加载
- 体例：`{ "code": 503, "message": "模型未加载" }`

**示例**

```bash
curl -s http://localhost:9883/ticos/speakers | jq .
```

---

## 模型能力查询 GET /ticos/capabilities

获取当前加载模型的类型与支持的功能特性。

**请求**

- 方法：`GET`
- 路径：`/ticos/capabilities`
- 无请求体

**成功响应**

- Content-Type: `application/json`
- HTTP 状态码：200
- 示例：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "model_type": "custom_voice",
    "features": ["tts", "voice_clone"]
  }
}
```

| 字段             | 类型   | 说明 |
|------------------|--------|------|
| code             | integer | 0 表示成功 |
| message          | string | 固定为 `成功` |
| data.model_type  | string | 当前模型类型：`base`、`custom_voice` 或 `voice_design` |
| data.features    | array  | 支持的能力列表。可能包含的值见下表 |

**features 取值说明**

| 值             | 含义 |
|----------------|------|
| tts            | 基础文本到语音合成 |
| voice_clone    | 支持声音克隆（仅 Base 模型） |


**错误响应**

- HTTP 503：模型未加载
- 体例：`{ "code": 503, "message": "模型未加载" }`

**示例**

```bash
curl -s http://localhost:9883/ticos/capabilities | jq .
```

---

## 支持语言列表 GET /ticos/languages

获取当前模型支持的语言列表。

**请求**

- 方法：`GET`
- 路径：`/ticos/languages`
- 无请求体

**成功响应**

- Content-Type: `application/json`
- HTTP 状态码：200
- 示例：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "languages": ["auto", "chinese", "english", "japanese", "korean"]
  }
}
```

| 字段             | 类型  | 说明 |
|------------------|-------|------|
| code             | integer | 0 表示成功 |
| message          | string | 固定为 `成功` |
| data.languages   | array | 支持的语言名称列表（小写）。如果模型无明确的语言限制，则返回空数组 `[]` |

**错误响应**

- HTTP 503：模型未加载
- 体例：`{ "code": 503, "message": "模型未加载" }`

**示例**

```bash
curl -s http://localhost:9883/ticos/languages | jq .
```

---


