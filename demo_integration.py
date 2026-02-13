
import os
import torch
import sys
from pathlib import Path

# Add MeloTTS and OpenVoice to sys.path
# 假设当前目录是 /Users/huyiyang/Workspace/myshell-ai
# 根据用户的工作区结构调整路径
current_dir = Path(__file__).parent
sys.path.append(str(current_dir / "MeloTTS"))
sys.path.append(str(current_dir / "OpenVoice"))

try:
    from openvoice import se_extractor
    from openvoice.api import ToneColorConverter
    from melo.api import TTS
except ImportError as e:
    print(f"错误: 无法导入必要的库。请确保 MeloTTS 和 OpenVoice 位于 {current_dir} 目录下。")
    print(f"详细错误: {e}")
    sys.exit(1)

def main():
    # --------------------------------------------------------------------------
    # 1. 配置路径和设备
    # --------------------------------------------------------------------------
    # 检查点目录 (OpenVoice V2)
    ckpt_converter = current_dir / 'OpenVoice' / 'checkpoints_v2' / 'converter'
    
    # 资源目录
    resource_dir = current_dir / 'OpenVoice' / 'resources'
    if not resource_dir.exists():
        print(f"警告: 资源目录不存在: {resource_dir}")
        # 尝试使用 demo_integration.py 同级目录下的 resources (如果用户移动了脚本)
        resource_dir = current_dir / 'resources'
    
    # 输出目录
    output_dir = current_dir / 'outputs_demo'
    output_dir.mkdir(exist_ok=True)

    # 设备配置 (自动检测 GPU/MPS/CPU)
    if torch.cuda.is_available():
        device = "cuda:0"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"使用设备: {device}")

    # --------------------------------------------------------------------------
    # 2. 检查模型文件是否存在
    # --------------------------------------------------------------------------
    if not ckpt_converter.exists():
        print(f"\n错误: 未找到 OpenVoice V2 检查点: {ckpt_converter}")
        print("请下载 'checkpoints_v2_0417.zip' 并解压到 OpenVoice/checkpoints_v2 目录。")
        print("下载链接: https://myshell-public-repo-host.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip")
        return

    # --------------------------------------------------------------------------
    # 3. 初始化模型
    # --------------------------------------------------------------------------
    print("\n正在加载 ToneColorConverter (OpenVoice)...")
    try:
        tone_color_converter = ToneColorConverter(
            f'{ckpt_converter}/config.json', 
            device=device
        )
        tone_color_converter.load_ckpt(f'{ckpt_converter}/checkpoint.pth')
    except Exception as e:
        print(f"加载 ToneColorConverter 失败: {e}")
        return

    # --------------------------------------------------------------------------
    # 4. 准备参考音频 (Reference Audio)
    # --------------------------------------------------------------------------
    # 这里使用 OpenVoice 自带的示例音频
    reference_speaker = resource_dir / 'example_reference.mp3'
    if not reference_speaker.exists():
        print(f"错误: 未找到参考音频文件: {reference_speaker}")
        return
    
    print(f"\n正在从参考音频提取音色: {reference_speaker.name}")
    try:
        # 提取目标音色 (Target Tone Color)
        target_se, audio_name = se_extractor.get_se(
            str(reference_speaker), 
            tone_color_converter, 
            vad=True
        )
    except Exception as e:
        print(f"提取音色失败: {e}")
        return

    # --------------------------------------------------------------------------
    # 5. 使用 MeloTTS 生成基础语音 (Base Audio)
    # --------------------------------------------------------------------------
    text = "大家好，这是一个 OpenVoice 和 MeloTTS 集成的演示。我正在使用克隆的声音说话。"
    language = 'ZH' # 中文
    
    print(f"\n正在使用 MeloTTS 生成基础语音 (语言: {language})...")
    # 初始化 MeloTTS
    # device='auto' 可能导致某些环境问题，这里明确指定
    try:
        model = TTS(language=language, device=device)
    except Exception as e:
        print(f"初始化 MeloTTS 失败: {e}")
        # 如果是字典下载失败，提示用户
        print("如果是字典下载失败，请尝试运行: python -m unidic download")
        return

    speaker_ids = model.hps.data.spk2id
    # 使用默认中文发音人
    speaker_key = 'ZH'
    speaker_id = speaker_ids[speaker_key]
    
    # 临时文件路径
    src_path = output_dir / 'temp_base.wav'
    
    # 生成基础语音
    model.tts_to_file(text, speaker_id, str(src_path), speed=1.0)
    print(f"基础语音已生成: {src_path}")

    # --------------------------------------------------------------------------
    # 6. 音色转换 (Tone Color Conversion)
    # --------------------------------------------------------------------------
    print("\n正在进行音色转换...")
    
    # 加载基础发音人(MeloTTS ZH)的源音色 (Source Tone Color)
    # 注意：OpenVoice V2 提供了常见 MeloTTS 发音人的预计算音色
    # 路径通常在 OpenVoice/checkpoints_v2/base_speakers/ses/zh.pth
    # 注意文件名大小写，MeloTTS ZH 对应 zh.pth
    src_se_path = current_dir / 'OpenVoice' / 'checkpoints_v2' / 'base_speakers' / 'ses' / 'zh.pth'
    
    if not src_se_path.exists():
        print(f"警告: 未找到源音色文件: {src_se_path}")
        print("将尝试直接使用模型内部的 speaker embedding (效果可能不如预计算的好)")
        # 备选方案：如果有提取好的 se 可以用，否则可能需要手动提取
        # 这里为了演示简单，如果找不到文件就退出提示下载
        print("请确保完整下载并解压了 checkpoints_v2_0417.zip")
        return

    try:
        source_se = torch.load(str(src_se_path), map_location=device)
    except Exception as e:
        print(f"加载源音色失败: {e}")
        return

    save_path = output_dir / 'output_cloned.wav'
    encode_message = "@MyShell" # 水印信息

    tone_color_converter.convert(
        audio_src_path=str(src_path), 
        src_se=source_se, 
        tgt_se=target_se, 
        output_path=str(save_path),
        message=encode_message
    )

    print("\n" + "="*50)
    print("演示完成！")
    print(f"生成的克隆音频: {save_path}")
    print("="*50)

if __name__ == "__main__":
    main()
