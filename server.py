#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenVoice-Melo-TTS HTTP 服务
基于 Tornado 框架，集成 MeloTTS (TTS) 和 OpenVoice V2 (音色转换)。
"""

import os
import sys
import io
import uuid
import json
import wave
import struct
import logging
import tempfile
import argparse
import base64
import hashlib
from pathlib import Path
from urllib.parse import urlparse

import torch
import numpy as np
import librosa
import soundfile as sf
import tornado.ioloop
import tornado.web
import tornado.httputil

# ---------------------------------------------------------------------------
# 路径配置：将 MeloTTS / OpenVoice 加入 sys.path
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR / "MeloTTS"))
sys.path.insert(0, str(ROOT_DIR / "OpenVoice"))

from openvoice.api import ToneColorConverter
from melo.api import TTS as MeloTTS

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("openvoice-melo-tts-server")

# 抑制第三方库的警告和调试信息
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="torch")
warnings.filterwarnings("ignore", message=".*fix_mistral_regex.*")
warnings.filterwarnings("ignore", message=".*tie_word_embeddings.*")

# 抑制 jieba 的 DEBUG 日志
logging.getLogger("jieba").setLevel(logging.WARNING)

# 抑制 transformers 的警告
logging.getLogger("transformers").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SERVICE_NAME = "openvoice-melo-tts-server"
SERVICE_VERSION = "2.0.0"

# MeloTTS 支持的语言列表（对应 download_utils.py 中的键）
MELO_LANGUAGES = {
    "ZH": "chinese",
    "EN": "english",
    "EN_V2": "english_v2",
    "FR": "french",
    "JP": "japanese",
    "ES": "spanish",
    "KR": "korean",
}

# 每种语言对应的 OpenVoice V2 base_speakers SE 文件名
# 路径: checkpoints_v2/base_speakers/ses/<key>.pth
LANG_SE_MAP = {
    "ZH": "zh.pth",
    "EN": "en.pth",
    "EN_V2": "en_v2.pth",
    "FR": "fr.pth",
    "JP": "jp.pth",
    "ES": "es.pth",
    "KR": "kr.pth",
}


# ---------------------------------------------------------------------------
# 自定义拼音词典加载
# ---------------------------------------------------------------------------
def _load_custom_pinyin(dict_path: str):
    """从 JSON 文件加载自定义拼音词典，注入 pypinyin 以修正多音字/发音错误。"""
    from pypinyin import load_phrases_dict

    if not os.path.isfile(dict_path):
        logger.warning("自定义拼音词典文件不存在，跳过: %s", dict_path)
        return

    try:
        with open(dict_path, "r", encoding="utf-8") as f:
            custom_phrases = json.load(f)
        if not isinstance(custom_phrases, dict):
            logger.error("自定义拼音词典格式错误，应为 JSON 对象: %s", dict_path)
            return
        load_phrases_dict(custom_phrases)
        logger.info("已加载自定义拼音词典: %s (%d 条)", dict_path, len(custom_phrases))
    except json.JSONDecodeError as e:
        logger.error("自定义拼音词典 JSON 解析失败: %s - %s", dict_path, e)
    except Exception as e:
        logger.error("加载自定义拼音词典失败: %s - %s", dict_path, e)


# ============================================================================
# TTSEngine：封装 MeloTTS + OpenVoice
# ============================================================================
class TTSEngine:
    """TTS 引擎，管理 MeloTTS 模型、OpenVoice ToneColorConverter 以及已注册的克隆音色。"""

    def __init__(self, ckpt_converter_dir: str, languages: list[str], device: str = "auto", clone_data_dir: str = None):
        # ------------------------------------------------------------------
        # 设备
        # ------------------------------------------------------------------
        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda:0"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        self.device = device
        logger.info("使用设备: %s", self.device)

        # ------------------------------------------------------------------
        # OpenVoice ToneColorConverter
        # ------------------------------------------------------------------
        converter_config = os.path.join(ckpt_converter_dir, "config.json")
        converter_ckpt = os.path.join(ckpt_converter_dir, "checkpoint.pth")
        if not os.path.isfile(converter_config):
            raise FileNotFoundError(f"Converter 配置文件不存在: {converter_config}")
        if not os.path.isfile(converter_ckpt):
            raise FileNotFoundError(f"Converter 权重文件不存在: {converter_ckpt}")

        logger.info("正在加载 ToneColorConverter ...")
        self.tone_color_converter = ToneColorConverter(converter_config, device=self.device)
        self.tone_color_converter.load_ckpt(converter_ckpt)
        logger.info("ToneColorConverter 加载完成")

        # ------------------------------------------------------------------
        # 预计算的 base speaker SE 路径目录
        # ------------------------------------------------------------------
        self.base_se_dir = os.path.join(os.path.dirname(ckpt_converter_dir), "base_speakers", "ses")

        # ------------------------------------------------------------------
        # MeloTTS 模型（按语言加载）
        # ------------------------------------------------------------------
        self.melo_models: dict[str, MeloTTS] = {}
        self.builtin_speakers: dict[str, dict] = {}  # speaker_id -> {lang, spk_id, name}

        for lang in languages:
            lang_upper = lang.upper()
            if lang_upper not in MELO_LANGUAGES:
                logger.warning("不支持的语言，跳过: %s", lang)
                continue
            logger.info("正在加载 MeloTTS 模型: %s ...", lang_upper)
            try:
                model = MeloTTS(
                    language=lang_upper, 
                    device=self.device,
                    config_path=f"/app/melo_models/{lang_upper}/config.json",
                    ckpt_path=f"/app/melo_models/{lang_upper}/checkpoint.pth"
                )
                self.melo_models[lang_upper] = model
                # 获取内置说话人列表
                spk2id = model.hps.data.spk2id
                for spk_name, spk_id in spk2id.items():
                    # 构造唯一的 speaker_id
                    speaker_key = f"{lang_upper}_{spk_name}" if spk_name != lang_upper else spk_name
                    self.builtin_speakers[speaker_key] = {
                        "lang": lang_upper,
                        "spk_id": spk_id,
                        "name": spk_name,
                    }
                logger.info("MeloTTS %s 加载完成，说话人: %s", lang_upper, list(spk2id.keys()))
            except Exception as e:
                logger.error("加载 MeloTTS %s 失败: %s", lang_upper, e)

        if not self.melo_models:
            raise RuntimeError("没有成功加载任何 MeloTTS 模型")

        # ------------------------------------------------------------------
        # 克隆音色存储：speaker_id -> {se: Tensor, lang: str}
        # ------------------------------------------------------------------
        self.cloned_speakers: dict[str, dict] = {}

        # 克隆数据持久化目录
        self.clone_data_dir = clone_data_dir or os.path.join(str(ROOT_DIR), "voice_clones")
        os.makedirs(self.clone_data_dir, exist_ok=True)
        self._load_cloned_speakers()

        logger.info("TTSEngine 初始化完成")

    # ------------------------------------------------------------------
    # 持久化管理
    # ------------------------------------------------------------------
    def _load_cloned_speakers(self):
        """启动时从磁盘加载已持久化的克隆音色。"""
        if not os.path.isdir(self.clone_data_dir):
            return
        for fname in os.listdir(self.clone_data_dir):
            if fname.endswith(".pth"):
                speaker_id = fname[:-4]
                meta_path = os.path.join(self.clone_data_dir, f"{speaker_id}.json")
                se_path = os.path.join(self.clone_data_dir, fname)
                try:
                    se = torch.load(se_path, map_location=self.device)
                    lang = "ZH"  # 默认语言
                    if os.path.isfile(meta_path):
                        with open(meta_path, "r") as f:
                            meta = json.load(f)
                            lang = meta.get("lang", "ZH")
                    self.cloned_speakers[speaker_id] = {"se": se, "lang": lang}
                    logger.info("已加载克隆音色: %s (lang=%s)", speaker_id, lang)
                except Exception as e:
                    logger.warning("加载克隆音色失败 %s: %s", fname, e)

    def _save_cloned_speaker(self, speaker_id: str, se, lang: str):
        """将克隆音色持久化到磁盘。"""
        se_path = os.path.join(self.clone_data_dir, f"{speaker_id}.pth")
        meta_path = os.path.join(self.clone_data_dir, f"{speaker_id}.json")
        torch.save(se.cpu(), se_path)
        with open(meta_path, "w") as f:
            json.dump({"lang": lang}, f)

    # ------------------------------------------------------------------
    # 获取 source SE（MeloTTS base speaker 的音色向量）
    # ------------------------------------------------------------------
    def _get_source_se(self, lang: str):
        """获取 MeloTTS 对应语言的 base speaker SE。"""
        se_filename = LANG_SE_MAP.get(lang)
        if se_filename is None:
            raise ValueError(f"未找到语言 {lang} 对应的 source SE 映射")
        se_path = os.path.join(self.base_se_dir, se_filename)
        if not os.path.isfile(se_path):
            raise FileNotFoundError(f"Source SE 文件不存在: {se_path}")
        return torch.load(se_path, map_location=self.device)

    # ------------------------------------------------------------------
    # 声音克隆：从参考音频提取 SE
    # ------------------------------------------------------------------
    def voice_clone(self, audio_path: str, lang: str = "ZH") -> str:
        """
        从参考音频提取音色向量并注册为新说话人。
        返回 speaker_id。
        """
        speaker_id = str(uuid.uuid4())

        # 使用 ToneColorConverter 的 extract_se 方法直接从音频提取
        # 不走 se_extractor.get_se (避免 whisper/VAD 依赖)
        se = self.tone_color_converter.extract_se([audio_path])

        self.cloned_speakers[speaker_id] = {"se": se, "lang": lang}
        self._save_cloned_speaker(speaker_id, se, lang)
        logger.info("已注册克隆音色: %s", speaker_id)
        return speaker_id

    # ------------------------------------------------------------------
    # 核心 TTS
    # ------------------------------------------------------------------
    def synthesize(
        self,
        text: str,
        speaker_id: str = None,
        speed_ratio: float = 50.0,
        volume_ratio: float = 50.0,
        pitch_ratio: float = 50.0,
        sample_rate: int = 16000,
        channels: int = 1,
        output_format: str = "pcm",
    ) -> bytes:
        """
        合成语音，返回音频字节流。
        """
        logger.info(f"开始合成: text='{text[:20]}...', speaker_id={speaker_id}")
        
        # ----------------------------------------------------------
        # 1. 确定说话人及对应模型
        # ----------------------------------------------------------
        is_cloned = False
        lang = None
        melo_spk_id = None

        if speaker_id and speaker_id in self.cloned_speakers:
            # 克隆音色
            is_cloned = True
            clone_info = self.cloned_speakers[speaker_id]
            lang = clone_info["lang"]
            logger.info(f"使用克隆音色: {speaker_id}, lang={lang}")
            # 克隆音色合成时使用对应语言的默认 base speaker
            model = self.melo_models.get(lang)
            if model is None:
                raise ValueError(f"克隆音色对应的语言模型未加载: {lang}")
            # 使用默认 speaker ID
            spk2id = model.hps.data.spk2id
            melo_spk_id = list(spk2id.values())[0]  # 取第一个（通常只有一个）
        elif speaker_id and speaker_id in self.builtin_speakers:
            # 预设音色
            info = self.builtin_speakers[speaker_id]
            lang = info["lang"]
            melo_spk_id = info["spk_id"]
            logger.info(f"使用预设音色: {speaker_id}, lang={lang}, spk_id={melo_spk_id}")
            model = self.melo_models.get(lang)
            if model is None:
                raise ValueError(f"预设音色对应的语言模型未加载: {lang}")
        else:
            # 未指定或无效 speaker_id，使用第一个加载的模型和默认说话人
            if speaker_id:
                logger.warning("未知 speaker_id: %s，使用默认说话人", speaker_id)
            lang = list(self.melo_models.keys())[0]
            model = self.melo_models[lang]
            spk2id = model.hps.data.spk2id
            melo_spk_id = list(spk2id.values())[0]
            logger.info(f"使用默认音色: lang={lang}, spk_id={melo_spk_id}")

        # ----------------------------------------------------------
        # 2. 参数转换
        # ----------------------------------------------------------
        # speed_ratio: 0-100 -> 实际倍速 (50 = 1.0x, 0 = 0.5x, 100 = 2.0x)
        speed = 0.5 + (speed_ratio / 100.0) * 1.5
        speed = max(0.1, min(3.0, speed))

        # volume_ratio: 0-100 -> 实际倍数 (50 = 1.0x)
        volume_scale = volume_ratio / 50.0
        volume_scale = max(0.0, min(4.0, volume_scale))

        # pitch_ratio: 0-100 -> 半音偏移 (50 = 0, 每单位约 0.24 半音)
        pitch_shift_semitones = (pitch_ratio - 50.0) * 0.24
        logger.info(f"参数: speed={speed:.2f}, volume={volume_scale:.2f}, pitch_shift={pitch_shift_semitones:.2f}半音")

        # ----------------------------------------------------------
        # 3. MeloTTS 合成
        # ----------------------------------------------------------
        logger.info("开始 MeloTTS 合成...")
        audio_np = model.tts_to_file(
            text,
            melo_spk_id,
            output_path=None,
            speed=speed,
            quiet=True,
        )
        model_sr = model.hps.data.sampling_rate  # MeloTTS 原始采样率
        logger.info(f"MeloTTS 合成完成，采样率={model_sr}, 音频长度={len(audio_np)}")

        # ----------------------------------------------------------
        # 4. 音色转换（仅克隆音色需要）
        # ----------------------------------------------------------
        if is_cloned:
            logger.info("开始音色转换...")
            try:
                source_se = self._get_source_se(lang)
                target_se = self.cloned_speakers[speaker_id]["se"]

                # 写入临时文件（ToneColorConverter.convert 需要文件路径）
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_src:
                    sf.write(tmp_src.name, audio_np, model_sr)
                    tmp_src_path = tmp_src.name

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
                    tmp_out_path = tmp_out.name

                self.tone_color_converter.convert(
                    audio_src_path=tmp_src_path,
                    src_se=source_se,
                    tgt_se=target_se,
                    output_path=tmp_out_path,
                    message="@MyShell",
                )

                audio_np, model_sr = sf.read(tmp_out_path)
                audio_np = audio_np.astype(np.float32)

                # 清理临时文件
                os.unlink(tmp_src_path)
                os.unlink(tmp_out_path)
                logger.info("音色转换完成")

            except Exception as e:
                logger.error("音色转换失败，返回原始音频: %s", e)

        # ----------------------------------------------------------
        # 5. 音频后处理
        # ----------------------------------------------------------
        logger.info("开始音频后处理...")
        
        # 音量调整
        if abs(volume_scale - 1.0) > 0.01:
            logger.info(f"调整音量: {volume_scale:.2f}x")
            audio_np = audio_np * volume_scale
            audio_np = np.clip(audio_np, -1.0, 1.0)

        # 音高调整（使用 librosa pitch shift）
        # 注意：pitch_shift 在某些环境下可能很慢，建议阈值设置大一些
        if abs(pitch_shift_semitones) > 0.5:
            logger.info(f"调整音高: {pitch_shift_semitones:.2f} 半音...")
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    audio_np = librosa.effects.pitch_shift(
                        y=audio_np, sr=model_sr, n_steps=pitch_shift_semitones
                    )
                logger.info("音高调整完成")
            except Exception as e:
                logger.warning("音高调整失败: %s", e)
        elif abs(pitch_shift_semitones) > 0.01:
            logger.info(f"音高偏移 {pitch_shift_semitones:.2f} 半音太小，跳过调整")

        # 采样率转换
        if sample_rate != model_sr:
            logger.info(f"转换采样率: {model_sr} -> {sample_rate}")
            audio_np = librosa.resample(audio_np, orig_sr=model_sr, target_sr=sample_rate)

        # 声道处理
        if channels == 2:
            logger.info("转换为双声道")
            audio_np = np.stack([audio_np, audio_np], axis=-1)

        # ----------------------------------------------------------
        # 6. 编码输出
        # ----------------------------------------------------------
        logger.info(f"编码输出格式: {output_format}")
        if output_format == "wav":
            buf = io.BytesIO()
            sf.write(buf, audio_np, sample_rate, format="WAV", subtype="PCM_16")
            result = buf.getvalue()
            logger.info(f"WAV 编码完成，大小: {len(result)} 字节")
            return result
        else:
            # PCM 16-bit
            pcm_data = (audio_np * 32767).astype(np.int16)
            result = pcm_data.tobytes()
            logger.info(f"PCM 编码完成，大小: {len(result)} 字节")
            return result


# ============================================================================
# Tornado Request Handlers
# ============================================================================

def json_response(handler: tornado.web.RequestHandler, code: int, message: str, data: dict = None):
    """统一 JSON 响应格式。"""
    handler.set_header("Content-Type", "application/json; charset=utf-8")
    body = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    handler.write(json.dumps(body, ensure_ascii=False))


def parse_request_params(handler: tornado.web.RequestHandler) -> dict:
    """
    从 JSON body 或 form-data 中统一解析参数。
    返回 dict。
    """
    content_type = handler.request.headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            return json.loads(handler.request.body)
        except (json.JSONDecodeError, ValueError):
            return {}
    else:
        # form-data / x-www-form-urlencoded
        params = {}
        for key in handler.request.arguments:
            val = handler.get_argument(key, default=None)
            if val is not None:
                params[key] = val
        return params


class HealthHandler(tornado.web.RequestHandler):
    """GET /health"""

    def get(self):
        engine: TTSEngine = self.application.engine
        status = "healthy" if engine and engine.melo_models else "degraded"
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps({
            "status": status,
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
        }, ensure_ascii=False))


class TTSHandler(tornado.web.RequestHandler):
    """POST /ticos/tts"""

    def post(self):
        logger.info("收到 TTS 请求")
        engine: TTSEngine = self.application.engine
        if not engine:
            self.set_status(503)
            json_response(self, 503, "模型未加载")
            return

        params = parse_request_params(self)
        text = params.get("text", "").strip()
        logger.info(f"请求参数: text='{text}', speaker_id={params.get('speaker_id')}, format={params.get('format')}")
        
        if not text:
            self.set_status(400)
            json_response(self, 400, "参数错误：text 不能为空", {})
            return

        speaker_id = params.get("speaker_id", None)
        volume_ratio = float(params.get("volume_ratio", 50))
        speed_ratio = float(params.get("speed_ratio", 50))
        pitch_ratio = float(params.get("pitch_ratio", 50))
        sample_rate = int(params.get("sample_rate", 16000))
        channels_val = int(params.get("channels", 1))
        output_format = params.get("format", "pcm").lower()

        # 参数边界检查
        volume_ratio = max(0, min(100, volume_ratio))
        speed_ratio = max(0, min(100, speed_ratio))
        pitch_ratio = max(0, min(100, pitch_ratio))
        channels_val = 1 if channels_val not in (1, 2) else channels_val
        if output_format not in ("pcm", "wav"):
            output_format = "pcm"

        logger.info(f"开始合成语音，参数: speaker_id={speaker_id}, pitch={pitch_ratio}")
        try:
            audio_bytes = engine.synthesize(
                text=text,
                speaker_id=speaker_id,
                speed_ratio=speed_ratio,
                volume_ratio=volume_ratio,
                pitch_ratio=pitch_ratio,
                sample_rate=sample_rate,
                channels=channels_val,
                output_format=output_format,
            )
            logger.info(f"合成完成，音频大小: {len(audio_bytes)} 字节")
        except Exception as e:
            logger.exception("TTS 合成失败")
            self.set_status(500)
            json_response(self, 500, f"合成失败: {e}", {})
            return

        if output_format == "wav":
            self.set_header("Content-Type", "audio/wav")
            self.set_header("Content-Disposition", 'attachment; filename="output.wav"')
        else:
            self.set_header("Content-Type", "audio/pcm")
            self.set_header("Content-Disposition", 'attachment; filename="output.pcm"')

        self.write(audio_bytes)
        logger.info("响应已发送")


class VoiceCloneHandler(tornado.web.RequestHandler):
    """POST /ticos/voice-clone"""

    def post(self):
        engine: TTSEngine = self.application.engine
        if not engine:
            self.set_status(503)
            json_response(self, 503, "模型未加载")
            return

        # ---------------------------------------------------------------
        # 解析 ref_audio
        # ---------------------------------------------------------------
        ref_audio_data = None
        content_type = self.request.headers.get("Content-Type", "")

        if "multipart/form-data" in content_type:
            # form-data 上传文件
            files = self.request.files.get("ref_audio", [])
            if files:
                ref_audio_data = files[0]["body"]
            else:
                # 可能作为普通字段传入 URL 或 base64
                params = parse_request_params(self)
                ref_audio_str = params.get("ref_audio", "")
        else:
            params = parse_request_params(self)
            ref_audio_str = params.get("ref_audio", "")

        if ref_audio_data is None and not ref_audio_str:
            self.set_status(400)
            json_response(self, 400, "参数错误：ref_audio 不能为空")
            return

        # 将 ref_audio 保存为临时文件
        try:
            tmp_audio_path = self._resolve_ref_audio(ref_audio_data, ref_audio_str if ref_audio_data is None else None)
        except Exception as e:
            self.set_status(400)
            json_response(self, 400, f"ref_audio 解析失败: {e}")
            return

        # ---------------------------------------------------------------
        # 执行克隆
        # ---------------------------------------------------------------
        try:
            speaker_id = engine.voice_clone(tmp_audio_path)
        except Exception as e:
            logger.exception("声音克隆失败")
            self.set_status(500)
            json_response(self, 500, f"声音克隆失败: {e}")
            return
        finally:
            # 清理临时文件
            if os.path.isfile(tmp_audio_path):
                os.unlink(tmp_audio_path)

        json_response(self, 0, "成功", {"speaker_id": speaker_id})

    def _resolve_ref_audio(self, raw_bytes=None, ref_str=None) -> str:
        """将 ref_audio (bytes / URL / base64) 解析为本地临时文件路径。"""
        suffix = ".wav"
        if raw_bytes:
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(raw_bytes)
            tmp.close()
            return tmp.name

        if ref_str:
            # base64
            if ref_str.startswith("data:"):
                # data:audio/wav;base64,xxxx
                _, encoded = ref_str.split(",", 1)
                audio_bytes = base64.b64decode(encoded)
                tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                tmp.write(audio_bytes)
                tmp.close()
                return tmp.name
            elif ref_str.startswith(("http://", "https://")):
                # 下载 URL
                import urllib.request
                tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                urllib.request.urlretrieve(ref_str, tmp.name)
                tmp.close()
                return tmp.name
            else:
                # 尝试作为 raw base64
                try:
                    audio_bytes = base64.b64decode(ref_str)
                    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                    tmp.write(audio_bytes)
                    tmp.close()
                    return tmp.name
                except Exception:
                    raise ValueError("ref_audio 格式无法识别，支持: URL / Base64 / 文件上传")

        raise ValueError("ref_audio 为空")


class SpeakersHandler(tornado.web.RequestHandler):
    """GET /ticos/speakers"""

    def get(self):
        engine: TTSEngine = self.application.engine
        if not engine:
            self.set_status(503)
            json_response(self, 503, "模型未加载")
            return

        speakers = []
        # 预设音色
        for sid in engine.builtin_speakers:
            speakers.append({"speaker_id": sid, "type": "builtin"})
        # 克隆音色
        for sid in engine.cloned_speakers:
            speakers.append({"speaker_id": sid, "type": "cloned"})

        json_response(self, 0, "成功", {"speakers": speakers})


class CapabilitiesHandler(tornado.web.RequestHandler):
    """GET /ticos/capabilities"""

    def get(self):
        engine: TTSEngine = self.application.engine
        if not engine:
            self.set_status(503)
            json_response(self, 503, "模型未加载")
            return

        json_response(self, 0, "成功", {
            "model_type": "openvoice_melo",
            "features": ["tts", "voice_clone"],
        })


class LanguagesHandler(tornado.web.RequestHandler):
    """GET /ticos/languages"""

    def get(self):
        engine: TTSEngine = self.application.engine
        if not engine:
            self.set_status(503)
            json_response(self, 503, "模型未加载")
            return

        languages = [MELO_LANGUAGES[lang] for lang in engine.melo_models.keys()]
        json_response(self, 0, "成功", {"languages": languages})


# ============================================================================
# Application & Main
# ============================================================================

def make_app(engine: TTSEngine) -> tornado.web.Application:
    """创建 Tornado Application，挂载路由和引擎实例。"""
    app = tornado.web.Application([
        (r"/health", HealthHandler),
        (r"/ticos/tts", TTSHandler),
        (r"/ticos/voice-clone", VoiceCloneHandler),
        (r"/ticos/speakers", SpeakersHandler),
        (r"/ticos/capabilities", CapabilitiesHandler),
        (r"/ticos/languages", LanguagesHandler),
    ])
    app.engine = engine
    return app


def main():
    parser = argparse.ArgumentParser(description="OpenVoice-Melo-TTS HTTP 服务")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["http", "unix"],
        default="http",
        help="服务器模式: http 或 unix socket (默认: http)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="HTTP 模式下的监听地址",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9883,
        help="HTTP 服务器端口 (默认: 9883)",
    )
    parser.add_argument(
        "--socket-path",
        type=str,
        default="/tmp/ticos_tts.sock",
        help="Unix Socket 路径 (默认: /tmp/ticos_tts.sock)",
    )
    parser.add_argument(
        "--voice-clone-dir",
        type=str,
        default=None,
        help="声音克隆数据持久化目录 (默认: 环境变量 VOICE_CLONE_DIR 或 ./voice_clones)",
    )
    parser.add_argument(
        "--custom-pinyin",
        type=str,
        default=None,
        help="自定义拼音词典 JSON 文件路径 (默认: 环境变量 CUSTOM_PINYIN_DICT 或 ./custom_pinyin.json)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别",
    )

    args = parser.parse_args()

    # 设置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    logger.setLevel(getattr(logging, args.log_level))

    # ---------------------------------------------------------------
    # 从环境变量读取引擎配置
    # ---------------------------------------------------------------
    # 计算设备: DEVICE 环境变量，默认 auto
    device = os.environ.get("DEVICE", "auto")

    # 要加载的语言列表: MELO_LANGUAGES 环境变量，逗号分隔，默认 ZH
    languages_str = os.environ.get("MELO_LANGUAGES", "ZH")
    languages = [lang.strip() for lang in languages_str.split(",") if lang.strip()]

    # OpenVoice V2 Converter 检查点目录
    ckpt_converter_dir = os.environ.get(
        "CKPT_CONVERTER_DIR",
        str(ROOT_DIR / "OpenVoice" / "checkpoints_v2" / "converter"),
    )

    # 声音克隆持久化目录
    voice_clone_dir = args.voice_clone_dir or os.environ.get(
        "VOICE_CLONE_DIR",
        str(ROOT_DIR / "voice_clones"),
    )

    # ---------------------------------------------------------------
    # 加载自定义拼音词典（必须在 TTSEngine 初始化之前）
    # ---------------------------------------------------------------
    custom_pinyin_path = args.custom_pinyin or os.environ.get(
        "CUSTOM_PINYIN_DICT",
        str(ROOT_DIR / "custom_pinyin.json"),
    )
    _load_custom_pinyin(custom_pinyin_path)

    # ---------------------------------------------------------------
    # 初始化引擎
    # ---------------------------------------------------------------
    logger.info("正在初始化 TTSEngine ...")
    engine = TTSEngine(
        ckpt_converter_dir=ckpt_converter_dir,
        languages=languages,
        device=device,
        clone_data_dir=voice_clone_dir,
    )

    app = make_app(engine)

    # ---------------------------------------------------------------
    # 监听
    # ---------------------------------------------------------------
    if args.mode == "unix":
        from tornado.netutil import bind_unix_socket
        from tornado.httpserver import HTTPServer

        # 如果旧 socket 文件存在，先删除
        if os.path.exists(args.socket_path):
            os.unlink(args.socket_path)

        socket = bind_unix_socket(args.socket_path)
        server = HTTPServer(app)
        server.add_socket(socket)
        logger.info("服务已启动，监听 Unix Socket: %s", args.socket_path)
    else:
        app.listen(args.port, address=args.host)
        logger.info("服务已启动，监听 http://%s:%d", args.host, args.port)

    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
