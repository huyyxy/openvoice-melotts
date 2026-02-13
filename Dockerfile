# =============================================================================
# OpenVoice + MeloTTS 离线 Docker 镜像 (多阶段构建)
# 构建前需运行 ./docker_build.sh 下载模型
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — 编译和安装所有 Python 依赖
# ---------------------------------------------------------------------------
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

# 构建时系统依赖（包含编译工具和开发头文件）
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-venv \
    python3.10-dev \
    python3-pip \
    build-essential \
    pkg-config \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    libavfilter-dev \
    libsndfile1 \
    libsox-dev \
    git \
    wget \
    curl \
    && ln -sf /usr/bin/python3.10 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------------------------------------------------------------------------
# 拷贝项目源码（用于 pip install）
# ---------------------------------------------------------------------------
COPY MeloTTS/ /app/MeloTTS/
COPY OpenVoice/ /app/OpenVoice/

# ---------------------------------------------------------------------------
# Python 依赖安装
# ---------------------------------------------------------------------------
# MeloTTS 依赖
RUN pip install --no-cache-dir -r /app/MeloTTS/requirements.txt

# OpenVoice 依赖
RUN pip install --no-cache-dir \
    librosa==0.9.1 \
    pydub==0.25.1 \
    wavmark==0.0.3 \
    soundfile

# Server 额外依赖
RUN pip install --no-cache-dir \
    tornado \
    numpy \
    soundfile

# 预装 av：av 10.0.0 源码与 Cython 3.x 不兼容
# 1. 安装 Cython<3 + 构建所需依赖
# 2. 用 --no-build-isolation 禁止 pip 创建隔离构建环境（隔离环境会安装 Cython 3.x）
RUN pip install --no-cache-dir "Cython<3" setuptools wheel \
    && pip install --no-cache-dir --no-build-isolation av==10.0.0

# 安装 MeloTTS 和 OpenVoice 包（标准安装，非 editable，以便跨阶段拷贝）
RUN cd /app/MeloTTS && pip install --no-cache-dir .
RUN cd /app/OpenVoice && pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# unidic 字典下载（MeloTTS 日语处理需要，数据存入 site-packages/unidic/）
# ---------------------------------------------------------------------------
RUN python -m unidic download

# ---------------------------------------------------------------------------
# jieba 词典初始化（MeloTTS 中文处理需要，首次使用会自动下载词典）
# ---------------------------------------------------------------------------
RUN python -c "\
import jieba; \
import jieba.posseg as pseg; \
print('初始化 jieba 词典...'); \
jieba.initialize(); \
test_text = '欢迎使用结巴中文分词'; \
words = list(jieba.cut(test_text)); \
words_pos = list(pseg.cut(test_text)); \
print(f'jieba 初始化完成: {words}'); \
"

# ---------------------------------------------------------------------------
# Stage 2: Runtime — 仅包含运行时所需内容
# ---------------------------------------------------------------------------
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

# 仅安装运行时系统库（不含编译工具和 -dev 头文件）
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3-setuptools \
    libavformat58 \
    libavcodec58 \
    libavdevice58 \
    libavutil56 \
    libswscale5 \
    libswresample3 \
    libavfilter7 \
    libsndfile1 \
    libsox3 \
    && ln -sf /usr/bin/python3.10 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------------------------------------------------------------------------
# 从 builder 拷贝已编译的 Python 包和脚本
# ---------------------------------------------------------------------------
COPY --from=builder /usr/local/lib/python3.10/dist-packages/ /usr/local/lib/python3.10/dist-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# ---------------------------------------------------------------------------
# 拷贝预下载的模型和数据
# ---------------------------------------------------------------------------

# OpenVoice V2 Checkpoints (converter + base_speakers)
COPY _model_cache/checkpoints_v2/ /app/checkpoints_v2/

# MeloTTS 语言模型
COPY _model_cache/melo_models/ /app/melo_models/

# BERT 模型
COPY _model_cache/bert_models/ /app/bert_models/

# NLTK 数据包（如果存在）
# 使用通配符允许目录不存在时不报错
COPY --chown=root:root _model_cache/nltk_data* /root/nltk_data/

# ---------------------------------------------------------------------------
# 拷贝项目源码
# ---------------------------------------------------------------------------
COPY MeloTTS/ /app/MeloTTS/
COPY OpenVoice/ /app/OpenVoice/
COPY server.py /app/server.py
COPY API.md /app/API.md

# ---------------------------------------------------------------------------
# 后备方案：如果 NLTK 数据不存在，在构建时下载
# ---------------------------------------------------------------------------
RUN if [ ! -d "/root/nltk_data/taggers" ]; then \
    echo "NLTK 数据不存在，开始下载..."; \
    python -c "\
import nltk; \
import os; \
nltk_data_dir = '/root/nltk_data'; \
os.makedirs(nltk_data_dir, exist_ok=True); \
packages = ['averaged_perceptron_tagger', 'cmudict', 'punkt', 'stopwords', 'wordnet']; \
for pkg in packages: \
    print(f'下载 NLTK 包: {pkg}'); \
    try: \
        nltk.download(pkg, download_dir=nltk_data_dir, quiet=True); \
    except Exception as e: \
        print(f'警告: {pkg} 下载失败: {e}'); \
print('NLTK 数据包处理完成'); \
"; \
    else \
    echo "NLTK 数据已存在"; \
    fi

# ---------------------------------------------------------------------------
# 设置 HuggingFace 缓存路径（离线变量在验证步骤之后再开启）
# ---------------------------------------------------------------------------
ENV HF_HOME=/app/bert_models

# 将 BERT 模型目录设置为 transformers 缓存路径
# transformers 会在 HF_HOME/hub/models--<org>--<model> 下查找模型
# 我们需要创建符号链接，使 from_pretrained 能离线找到模型
RUN mkdir -p /app/bert_models/hub && \
    for dir in /app/bert_models/*/; do \
    dirname=$(basename "$dir"); \
    # 将 __ 替换为 -- (docker_build.sh 中的命名约定)
    model_dir_name=$(echo "$dirname" | sed 's/__/--/g'); \
    # 创建 transformers 期望的目录结构
    target_dir="/app/bert_models/hub/models--${model_dir_name}"; \
    mkdir -p "${target_dir}/refs" "${target_dir}/snapshots"; \
    echo "main" > "${target_dir}/refs/main"; \
    # 将实际模型文件链接到 snapshot
    ln -sf "$dir" "${target_dir}/snapshots/main"; \
    done

# ---------------------------------------------------------------------------
# 将 MeloTTS 模型设置为 huggingface_hub 缓存路径
# （MeloTTS 通过 hf_hub_download 下载 config.json 和 checkpoint.pth）
# ---------------------------------------------------------------------------
ARG LANGUAGES=ZH
ENV MELO_LANGUAGES=${LANGUAGES}

# 为 MeloTTS 创建 huggingface_hub 缓存符号链接
RUN LANG_REPO_ZH="myshell-ai/MeloTTS-Chinese" && \
    LANG_REPO_EN="myshell-ai/MeloTTS-English" && \
    LANG_REPO_EN_V2="myshell-ai/MeloTTS-English-v2" && \
    LANG_REPO_FR="myshell-ai/MeloTTS-French" && \
    LANG_REPO_JP="myshell-ai/MeloTTS-Japanese" && \
    LANG_REPO_ES="myshell-ai/MeloTTS-Spanish" && \
    LANG_REPO_KR="myshell-ai/MeloTTS-Korean" && \
    for lang in ${LANGUAGES}; do \
    eval "repo=\${LANG_REPO_${lang}:-}"; \
    if [ -z "${repo}" ]; then continue; fi; \
    safe_repo=$(echo "${repo}" | sed 's/\//-/g'); \
    model_dir="/app/bert_models/hub/models--${safe_repo}"; \
    mkdir -p "${model_dir}/refs" "${model_dir}/snapshots"; \
    echo "main" > "${model_dir}/refs/main"; \
    ln -sf "/app/melo_models/${lang}" "${model_dir}/snapshots/main"; \
    done

# ---------------------------------------------------------------------------
# 预热：加载一次模型以验证完整性并生成缓存
# ---------------------------------------------------------------------------
RUN python -c "\
import sys; \
sys.path.insert(0, '/app/MeloTTS'); \
sys.path.insert(0, '/app/OpenVoice'); \
from openvoice.api import ToneColorConverter; \
import os; \
print('验证 ToneColorConverter ...'); \
tc = ToneColorConverter('/app/checkpoints_v2/converter/config.json', device='cpu'); \
tc.load_ckpt('/app/checkpoints_v2/converter/checkpoint.pth'); \
print('ToneColorConverter 验证通过'); \
"

# ---------------------------------------------------------------------------
# 开启 HuggingFace 离线模式（验证已通过，运行时不再需要网络）
# ---------------------------------------------------------------------------
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

# ---------------------------------------------------------------------------
# 运行时配置
# ---------------------------------------------------------------------------
ENV CKPT_CONVERTER_DIR=/app/checkpoints_v2/converter
ENV DEVICE=auto
ENV VOICE_CLONE_DIR=/app/voice_clones

# 端口
EXPOSE 9883

# 入口
CMD ["python", "server.py", "--port", "9883", "--host", "0.0.0.0"]
